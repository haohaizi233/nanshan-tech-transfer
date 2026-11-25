-- ========================================================
-- 037_phase_r_security_hardening.sql —— Email Security Gateway Phase R 安全加固
--
-- 1. 扩展 auth_session：新增 auth_time 与 sid（稳定逻辑会话标识），禁止回填历史行
-- 2. 扩展 step_up_grant：新增 session_id，撤销无目标绑定的存量活跃邮箱授权，增加强约束
-- 3. 扩展 security_delivery_request：支持带作用域的请求级幂等、参数摘要与响应缓存
-- 4. 扩展 auth_challenge：持久化服务商配置指纹、Step-up 挑战上下文绑定字段
-- 所有 DDL 严格增量、幂等、可安全重跑。
-- ========================================================

BEGIN;

-- 1. 扩展 auth_session（历史行保持 NULL，不伪造认证时间与会话标识）
ALTER TABLE public.auth_session
    ADD COLUMN IF NOT EXISTS auth_time TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS sid UUID DEFAULT NULL;

COMMENT ON COLUMN public.auth_session.auth_time IS '真实身份认证时间戳（仅登录/显式重认证更新，Refresh 保持不变）';
COMMENT ON COLUMN public.auth_session.sid IS '稳定逻辑会话标识，同一会话多次 Refresh Token 保持一致';

CREATE INDEX IF NOT EXISTS idx_auth_session_user_sid
    ON public.auth_session (user_id, sid)
    WHERE sid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auth_session_sid_active
    ON public.auth_session (sid)
    WHERE status = 'active' AND sid IS NOT NULL;

-- 2. 扩展 step_up_grant 与目标邮箱强约束
ALTER TABLE public.step_up_grant
    ADD COLUMN IF NOT EXISTS session_id UUID DEFAULT NULL;

COMMENT ON COLUMN public.step_up_grant.session_id IS '绑定的稳定逻辑会话 sid（用于会话注销与跨会话防护）';

CREATE INDEX IF NOT EXISTS idx_step_up_grant_session
    ON public.step_up_grant (session_id)
    WHERE session_id IS NOT NULL;

-- 安全收敛：撤销历史未绑定目标地址且仍处于 active 的邮箱敏感操作授权，保留历史 consumed 记录用于审计
UPDATE public.step_up_grant
SET status = 'revoked'
WHERE status = 'active'
  AND purpose IN ('bind_email', 'rebind_email')
  AND (target_fingerprint IS NULL OR length(target_fingerprint) = 0);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_step_up_grant_email_target'
          AND conrelid = 'public.step_up_grant'::regclass
    ) THEN
        ALTER TABLE public.step_up_grant
            ADD CONSTRAINT chk_step_up_grant_email_target
            CHECK (
                status <> 'active'
                OR purpose NOT IN ('bind_email', 'rebind_email')
                OR (target_fingerprint IS NOT NULL AND length(target_fingerprint) > 0)
            );
    END IF;
END $$;

-- 3. 扩展 security_delivery_request（持久化 HTTP 请求级幂等）
ALTER TABLE public.security_delivery_request
    ALTER COLUMN state TYPE VARCHAR(32);

ALTER TABLE public.security_delivery_request
    ADD COLUMN IF NOT EXISTS idempotency_scope VARCHAR(128) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS idempotency_expires_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS response_payload JSONB DEFAULT NULL;

COMMENT ON COLUMN public.security_delivery_request.idempotency_scope IS '幂等作用域（端点 + 用户/匿名请求隔离维度）';
COMMENT ON COLUMN public.security_delivery_request.idempotency_key IS '客户端请求级幂等键（Idempotency-Key 头）';
COMMENT ON COLUMN public.security_delivery_request.request_hash IS '规范化业务请求 SHA-256 摘要，用于检测同 Key 参数冲突 (409)';
COMMENT ON COLUMN public.security_delivery_request.idempotency_expires_at IS '幂等记录过期时间（过期后允许新请求轮转）';
COMMENT ON COLUMN public.security_delivery_request.response_payload IS '脱敏公开响应缓存（仅用于安全重放受理结果）';

DROP INDEX IF EXISTS public.uk_security_delivery_request_idempotency;

CREATE UNIQUE INDEX IF NOT EXISTS uk_security_delivery_request_idempotency_scoped
    ON public.security_delivery_request (idempotency_scope, idempotency_key)
    WHERE idempotency_key IS NOT NULL AND idempotency_scope IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_security_delivery_request_idempotency_cleanup
    ON public.security_delivery_request (idempotency_expires_at)
    WHERE idempotency_key IS NOT NULL;

-- 4. 扩展 auth_challenge（服务商配置身份指纹 + Step-up 挑战上下文绑定）
ALTER TABLE public.auth_challenge
    ADD COLUMN IF NOT EXISTS provider_config_id VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS session_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS sub_purpose VARCHAR(32) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS target_fingerprint VARCHAR(64) DEFAULT NULL;

COMMENT ON COLUMN public.auth_challenge.provider_config_id IS '历史投递使用的非敏感配置实例指纹，防止切换配置后误查状态';
COMMENT ON COLUMN public.auth_challenge.session_id IS 'Step-up Challenge 绑定的逻辑会话 sid';
COMMENT ON COLUMN public.auth_challenge.sub_purpose IS 'Step-up Challenge 绑定的敏感业务子用途（如 bind_email/rebind_email）';
COMMENT ON COLUMN public.auth_challenge.target_fingerprint IS 'Step-up Challenge 绑定的目标联系方式盲索引';

COMMIT;
