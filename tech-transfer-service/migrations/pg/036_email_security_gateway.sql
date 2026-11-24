-- ========================================================
-- 036_email_security_gateway.sql —— Email Security Gateway 增量迁移
--
-- 1. 扩展 auth_challenge：支持摘要版本、服务商标识、投递失败原因、状态检查约束及活跃单挑部分唯一索引
-- 2. 扩展 security_delivery_request：补全渠道/用途/服务商诊断列及索引
-- 3. 新增 step_up_grant：邮箱换绑等高风险操作二次认证短期单次授权表
-- 4. 新增清理与查询索引（严格增量、幂等、零历史数据破坏）
-- ========================================================

BEGIN;

-- 1. 扩展 auth_challenge
ALTER TABLE public.auth_challenge
    ADD COLUMN IF NOT EXISTS code_hash_version SMALLINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS provider_name VARCHAR(32) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS delivery_failure_reason VARCHAR(64) DEFAULT NULL;

COMMENT ON COLUMN public.auth_challenge.code_hash_version IS '验证码摘要算法版本：1=legacy HMAC；2=独立密钥上下文绑定 HMAC';
COMMENT ON COLUMN public.auth_challenge.provider_name IS '执行本次投递的服务商名称（smtp / tencent / sendcloud / mock）';
COMMENT ON COLUMN public.auth_challenge.delivery_failure_reason IS '标准化投递失败分类原因码（脱敏）';

-- 安全收敛历史残留：已过期或重复激活的挑战先归一化，再建立约束与部分唯一索引
UPDATE public.auth_challenge
SET status = 'expired'
WHERE status IN ('pending_send', 'pending')
  AND expires_at <= NOW();

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY user_id, purpose, channel
               ORDER BY created_at DESC, id DESC
           ) AS rn
    FROM public.auth_challenge
    WHERE user_id IS NOT NULL
      AND status IN ('pending_send', 'pending')
)
UPDATE public.auth_challenge ac
SET status = 'cancelled'
FROM ranked r
WHERE ac.id = r.id
  AND r.rn > 1;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_auth_challenge_status'
          AND conrelid = 'public.auth_challenge'::regclass
    ) THEN
        ALTER TABLE public.auth_challenge
            ADD CONSTRAINT chk_auth_challenge_status
            CHECK (status IN (
                'pending_send', 'pending', 'verified', 'consumed',
                'expired', 'locked', 'failed', 'cancelled'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_auth_challenge_send_state'
          AND conrelid = 'public.auth_challenge'::regclass
    ) THEN
        ALTER TABLE public.auth_challenge
            ADD CONSTRAINT chk_auth_challenge_send_state
            CHECK (send_state IS NULL OR send_state IN (
                'reserved', 'sending', 'accepted', 'rejected',
                'unknown', 'delivered', 'bounced', 'delivery_failed'
            ));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uk_auth_challenge_active_user_purpose_channel
    ON public.auth_challenge (user_id, purpose, channel)
    WHERE user_id IS NOT NULL AND status IN ('pending_send', 'pending');

CREATE INDEX IF NOT EXISTS idx_auth_challenge_email_send_state
    ON public.auth_challenge (send_state, created_at)
    WHERE channel IN ('email_otp', 'email_link');

CREATE INDEX IF NOT EXISTS idx_auth_challenge_cleanup
    ON public.auth_challenge (expires_at, status)
    WHERE status IN ('pending_send', 'pending', 'verified');

-- 2. 扩展 security_delivery_request
ALTER TABLE public.security_delivery_request
    ADD COLUMN IF NOT EXISTS channel VARCHAR(16) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS purpose VARCHAR(32) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32) DEFAULT NULL;

COMMENT ON COLUMN public.security_delivery_request.channel IS '投递渠道（sms / email_otp / email_link）';
COMMENT ON COLUMN public.security_delivery_request.purpose IS '业务用途（password_recovery / bind_email / bind_phone）';
COMMENT ON COLUMN public.security_delivery_request.provider IS '实际投递使用的服务商标识';

UPDATE public.security_delivery_request
SET channel = NULLIF(LEFT(payload->>'channel', 16), '')
WHERE channel IS NULL
  AND payload ? 'channel';

CREATE INDEX IF NOT EXISTS idx_security_delivery_request_channel_state
    ON public.security_delivery_request (channel, state, created_at);

CREATE INDEX IF NOT EXISTS idx_security_delivery_request_cleanup
    ON public.security_delivery_request (created_at, state);

-- 3. 新增 step_up_grant：敏感操作二次认证短期授权
CREATE TABLE IF NOT EXISTS public.step_up_grant (
    id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
    purpose VARCHAR(32) NOT NULL,
    method VARCHAR(24) NOT NULL,
    session_fingerprint VARCHAR(64) NOT NULL,
    target_fingerprint VARCHAR(64) DEFAULT NULL,
    grant_hash VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'consumed', 'revoked', 'expired')),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE public.step_up_grant IS '安全操作二次认证短期单次授权（换绑邮箱等场景）';
COMMENT ON COLUMN public.step_up_grant.session_fingerprint IS '绑定当前登录会话摘要，防止跨会话盗用';
COMMENT ON COLUMN public.step_up_grant.target_fingerprint IS '可选绑定目标联系方式盲索引';
COMMENT ON COLUMN public.step_up_grant.grant_hash IS 'Step-up Grant SHA-256 摘要';

CREATE UNIQUE INDEX IF NOT EXISTS uk_step_up_grant_hash
    ON public.step_up_grant (grant_hash);

CREATE INDEX IF NOT EXISTS idx_step_up_grant_user_purpose_status
    ON public.step_up_grant (user_id, purpose, status);

CREATE INDEX IF NOT EXISTS idx_step_up_grant_cleanup
    ON public.step_up_grant (expires_at, status)
    WHERE status = 'active';

DROP TRIGGER IF EXISTS trg_step_up_grant_updated_at ON public.step_up_grant;
CREATE TRIGGER trg_step_up_grant_updated_at BEFORE UPDATE ON public.step_up_grant
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 4. recovery_grant 清理索引
CREATE INDEX IF NOT EXISTS idx_recovery_grant_cleanup
    ON public.recovery_grant (expires_at, status)
    WHERE status = 'active';

COMMIT;
