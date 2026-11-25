-- ========================================================
-- 038_phase_r_final_security.sql —— Phase R-Final 安全不变量收敛与执行权治理
--
-- 1. 扩展 auth_challenge：补充 session_version、source_contact_fingerprint、send_owner、send_claimed_at；
--    安全取消缺失完整上下文的活跃 step_up_auth 历史挑战（不删除、不伪造上下文），并加 CHECK 约束；
-- 2. 扩展 security_delivery_request：补充 execution_owner、execution_stage、challenge_id、idem_claimed_at；
--    加 execution_stage 合法值约束；安全收敛超时 idem_pending 与历史终态残留 PII；
-- 3. 收敛 step_up_grant：撤销缺失 session_id 或 target_fingerprint 的存量活跃邮箱授权；
-- 4. 增补复合索引 idx_auth_session_user_sid_status 与 idx_sdr_state_created。
-- 全部 DDL 严格增量、幂等、可安全重跑。
-- ========================================================

BEGIN;

-- 1. 扩展 auth_challenge（发送执行权 + Step-up 完整上下文强绑定）
ALTER TABLE public.auth_challenge
    ADD COLUMN IF NOT EXISTS session_version INTEGER DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS source_contact_fingerprint VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS send_owner VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS send_claimed_at TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN public.auth_challenge.session_version IS 'Step-up Challenge 绑定签发时的 app_user.session_version';
COMMENT ON COLUMN public.auth_challenge.source_contact_fingerprint IS 'Step-up Challenge 绑定的原已确权安全联系方式盲索引';
COMMENT ON COLUMN public.auth_challenge.send_owner IS '取得 reserved -> sending 外部发送执行权的 Worker/请求唯一标识';
COMMENT ON COLUMN public.auth_challenge.send_claimed_at IS '成功取得 sending 发送执行权的数据库时间戳';

-- 安全收敛：取消缺失完整安全上下文的历史活跃 Step-up Challenge（保留审计记录，绝不伪造 SID/来源/目标）
UPDATE public.auth_challenge
SET status = 'cancelled'
WHERE purpose = 'step_up_auth'
  AND status IN ('pending_send', 'pending', 'verified')
  AND (
      session_id IS NULL
      OR session_version IS NULL
      OR sub_purpose IS NULL
      OR sub_purpose NOT IN ('bind_email', 'rebind_email', 'bind_phone', 'rebind_phone')
      OR length(COALESCE(source_contact_fingerprint, '')) = 0
      OR (
          sub_purpose IN ('bind_email', 'rebind_email')
          AND length(COALESCE(target_fingerprint, '')) = 0
      )
  );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_auth_challenge_stepup_context'
          AND conrelid = 'public.auth_challenge'::regclass
    ) THEN
        ALTER TABLE public.auth_challenge
            ADD CONSTRAINT chk_auth_challenge_stepup_context
            CHECK (
                purpose <> 'step_up_auth'
                OR status NOT IN ('pending_send', 'pending', 'verified')
                OR (
                    session_id IS NOT NULL
                    AND session_version IS NOT NULL
                    AND sub_purpose IN ('bind_email', 'rebind_email', 'bind_phone', 'rebind_phone')
                    AND length(COALESCE(source_contact_fingerprint, '')) > 0
                    AND (
                        sub_purpose NOT IN ('bind_email', 'rebind_email')
                        OR length(COALESCE(target_fingerprint, '')) > 0
                    )
                )
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_auth_challenge_sending_claimed
    ON public.auth_challenge (send_claimed_at)
    WHERE send_state = 'sending';

-- 2. 扩展 security_delivery_request（幂等执行所有权与外部副作用阶段持久化事实）
ALTER TABLE public.security_delivery_request
    ADD COLUMN IF NOT EXISTS execution_owner VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS execution_stage VARCHAR(32) NOT NULL DEFAULT 'pre_provider',
    ADD COLUMN IF NOT EXISTS challenge_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS idem_claimed_at TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN public.security_delivery_request.execution_owner IS '当前持有 HTTP 幂等占位/执行权的请求所有者标识';
COMMENT ON COLUMN public.security_delivery_request.execution_stage IS '持久化执行阶段：pre_provider / send_claimed / provider_called / provider_accepted / provider_rejected / provider_unknown / response_persisted';
COMMENT ON COLUMN public.security_delivery_request.challenge_id IS '关联的 auth_challenge.id';
COMMENT ON COLUMN public.security_delivery_request.idem_claimed_at IS 'HTTP 幂等占位时间';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_sdr_execution_stage'
          AND conrelid = 'public.security_delivery_request'::regclass
    ) THEN
        ALTER TABLE public.security_delivery_request
            ADD CONSTRAINT chk_sdr_execution_stage
            CHECK (
                execution_stage IN (
                    'pre_provider',
                    'send_claimed',
                    'provider_called',
                    'provider_accepted',
                    'provider_rejected',
                    'provider_unknown',
                    'response_persisted'
                )
            );
    END IF;
END $$;

-- 历史超时的 idem_pending 占位安全收敛（未取得发送权前过期；若已可能触发外部调用则保守记为 unknown 且保留幂等键）
UPDATE public.security_delivery_request
SET idempotency_key = CASE
        WHEN execution_stage = 'pre_provider' AND provider_called = false THEN NULL
        ELSE idempotency_key
    END,
    idempotency_scope = CASE
        WHEN execution_stage = 'pre_provider' AND provider_called = false THEN NULL
        ELSE idempotency_scope
    END,
    state = CASE
        WHEN execution_stage = 'pre_provider' AND provider_called = false THEN 'expired'
        ELSE 'unknown'
    END,
    outcome = CASE
        WHEN execution_stage = 'pre_provider' AND provider_called = false THEN COALESCE(outcome, 'INTERNAL_ERROR')
        ELSE 'PROVIDER_UNKNOWN'
    END,
    failure_stage = COALESCE(failure_stage, 'idempotency'),
    failure_reason = COALESCE(failure_reason, 'idem_pending_expired_on_migration'),
    outcome_unknown = CASE
        WHEN execution_stage = 'pre_provider' AND provider_called = false THEN outcome_unknown
        ELSE true
    END,
    finished_at = COALESCE(finished_at, NOW()),
    payload = COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
WHERE state IN ('idem_pending', 'idempotent_pending')
  AND COALESCE(idem_claimed_at, created_at) < NOW() - INTERVAL '10 minutes';

-- 清理历史已终止/未知任务残留明文 PII（绝不触碰活跃执行中的 idem_pending / queued / processing）
UPDATE public.security_delivery_request
SET payload = COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
WHERE state IN (
    'completed', 'failed', 'failed_internal', 'ineligible',
    'blocked', 'config_error', 'expired', 'unknown', 'legacy_unknown'
)
  AND (
      payload ? 'account'
      OR payload ? 'ip'
      OR payload ? 'device_id'
      OR payload ? 'destination'
  );

CREATE INDEX IF NOT EXISTS idx_sdr_state_created
    ON public.security_delivery_request (state, created_at);

-- 3. 收敛 step_up_grant：撤销历史缺失 session_id 或 target_fingerprint 的活跃邮箱敏感操作授权
UPDATE public.step_up_grant
SET status = 'revoked'
WHERE status = 'active'
  AND purpose IN ('bind_email', 'rebind_email')
  AND (
      session_id IS NULL
      OR target_fingerprint IS NULL
      OR length(target_fingerprint) = 0
  );

-- 4. 会话校验高频联合索引
CREATE INDEX IF NOT EXISTS idx_auth_session_user_sid_status
    ON public.auth_session (user_id, sid, status)
    WHERE sid IS NOT NULL;

COMMIT;
