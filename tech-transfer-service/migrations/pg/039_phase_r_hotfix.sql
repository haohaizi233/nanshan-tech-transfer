-- ========================================================
-- 039_phase_r_hotfix.sql —— Phase R-Hotfix 最终安全收敛与状态协调
--
-- 1. security_delivery_request:
--    - 新增 stage_provenance ('explicit' / 'legacy_proven_not_sent' / 'legacy_proven_sent' / 'legacy_unknown')
--    - 扩展 chk_sdr_execution_stage 支持 'legacy_unknown'，防止 038 默认 'pre_provider' 误判历史发送阶段
--    - 首次升级保守分类历史存量行：仅在存在明确证据时标记已发/未发，否则标记 legacy_unknown，绝不伪造已清理幂等键
-- 2. auth_challenge:
--    - 新增持久化 Redis 风控状态协调列 (risk_sync_state / risk_sync_target /
--      risk_sync_attempts / risk_sync_next_retry_at / risk_sync_last_error_code /
--      risk_sync_claimed_at / risk_sync_updated_at) 及检查约束、待补偿部分索引
-- 3. 全脚本严格增量、幂等，严禁修改 033-038 历史迁移脚本
-- ========================================================

BEGIN;

-- 1. 扩展 security_delivery_request 执行阶段约束并保守回填历史阶段来源
ALTER TABLE public.security_delivery_request
    DROP CONSTRAINT IF EXISTS chk_sdr_execution_stage;

ALTER TABLE public.security_delivery_request
    ADD CONSTRAINT chk_sdr_execution_stage
    CHECK (execution_stage IN (
        'pre_provider',
        'send_claimed',
        'provider_called',
        'provider_accepted',
        'provider_rejected',
        'provider_unknown',
        'response_persisted',
        'legacy_unknown'
    ));

DO $$
DECLARE
    v_has_stage_provenance BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'security_delivery_request'
          AND column_name = 'stage_provenance'
    ) INTO v_has_stage_provenance;

    ALTER TABLE public.security_delivery_request
        ADD COLUMN IF NOT EXISTS stage_provenance VARCHAR(32) NOT NULL DEFAULT 'explicit';

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_sdr_stage_provenance'
          AND conrelid = 'public.security_delivery_request'::regclass
    ) THEN
        ALTER TABLE public.security_delivery_request
            ADD CONSTRAINT chk_sdr_stage_provenance
            CHECK (stage_provenance IN (
                'explicit',
                'legacy_proven_not_sent',
                'legacy_proven_sent',
                'legacy_unknown'
            ));
    END IF;

    -- 仅在首次应用 039（stage_provenance 列此前不存在）时对历史存量记录做保守分类
    IF NOT v_has_stage_provenance THEN
        -- 1a. 具备明确已调用外部 Provider 证据的历史行（provider_called=true 或有 provider_ids）
        UPDATE public.security_delivery_request
        SET provider_called = true,
            execution_stage = CASE
                WHEN state = 'completed' AND NOT outcome_unknown THEN
                    CASE
                        WHEN response_payload IS NOT NULL THEN 'response_persisted'
                        ELSE 'provider_accepted'
                    END
                WHEN state = 'failed' AND outcome = 'PROVIDER_REJECTED' THEN 'provider_rejected'
                WHEN state = 'failed' AND outcome = 'DELIVERY_FAILED' THEN 'provider_accepted'
                WHEN state IN ('unknown', 'legacy_unknown')
                     OR outcome_unknown = true
                     OR outcome = 'PROVIDER_UNKNOWN' THEN 'provider_unknown'
                ELSE 'provider_unknown'
            END,
            state = CASE
                WHEN state IN ('completed', 'failed', 'unknown', 'legacy_unknown') THEN state
                ELSE 'unknown'
            END,
            outcome_unknown = CASE
                WHEN state IN ('completed', 'failed') AND outcome IN ('COMPLETED', 'PROVIDER_REJECTED', 'DELIVERY_FAILED') THEN outcome_unknown
                ELSE true
            END,
            stage_provenance = CASE
                WHEN state IN ('completed', 'failed', 'unknown', 'legacy_unknown')
                     AND (
                         outcome IN ('COMPLETED', 'PROVIDER_REJECTED', 'DELIVERY_FAILED', 'PROVIDER_UNKNOWN')
                         OR state IN ('unknown', 'legacy_unknown')
                     ) THEN 'legacy_proven_sent'
                ELSE 'legacy_unknown'
            END,
            finished_at = COALESCE(finished_at, NOW())
        WHERE execution_stage = 'pre_provider'
          AND (
              provider_called = true
              OR jsonb_array_length(COALESCE(provider_ids, '[]'::jsonb)) > 0
          );

        -- 1b. 具备明确前置阻断/未入外部调用证据的历史行（非幂等默认过期推断）
        UPDATE public.security_delivery_request
        SET execution_stage = 'pre_provider',
            stage_provenance = 'legacy_proven_not_sent'
        WHERE execution_stage = 'pre_provider'
          AND provider_called = false
          AND jsonb_array_length(COALESCE(provider_ids, '[]'::jsonb)) = 0
          AND (
              state IN ('blocked', 'config_error', 'ineligible')
              OR outcome IN ('RISK_BLOCKED', 'CONFIG_ERROR', 'INELIGIBLE')
              OR failure_stage IN ('risk', 'config', 'eligibility', 'queue')
          );

        -- 1c. 其余所有无显式执行权/占用证明且继承了 038 默认 'pre_provider' 或旧 'finished' 的历史模糊行：
        --     一律保守降级为 execution_stage='legacy_unknown' / stage_provenance='legacy_unknown'，
        --     不触发发信，不伪造已释放的 idempotency_key。
        UPDATE public.security_delivery_request
        SET execution_stage = 'legacy_unknown',
            stage_provenance = 'legacy_unknown',
            state = CASE
                WHEN state IN ('idem_pending', 'idempotent_pending', 'processing', 'finished') THEN 'legacy_unknown'
                ELSE state
            END,
            outcome_unknown = CASE
                WHEN state IN ('unknown', 'legacy_unknown', 'idem_pending', 'idempotent_pending', 'processing', 'finished') THEN true
                ELSE outcome_unknown
            END,
            failure_reason = CASE
                WHEN state = 'finished' AND failure_reason IS NULL THEN 'legacy_outcome_not_recorded'
                ELSE failure_reason
            END,
            finished_at = COALESCE(finished_at, NOW())
        WHERE stage_provenance = 'explicit'
          AND execution_owner IS NULL
          AND idem_claimed_at IS NULL
          AND execution_stage = 'pre_provider'
          AND (
              state <> 'queued'
              OR created_at < NOW() - INTERVAL '5 minutes'
          );
    END IF;
END $$;

COMMENT ON COLUMN public.security_delivery_request.stage_provenance IS
    '执行阶段证据来源：explicit(显式状态机记录) / legacy_proven_not_sent(明确前置拦截未发送) / legacy_proven_sent(明确已调用Provider) / legacy_unknown(历史阶段证据不足)';

CREATE INDEX IF NOT EXISTS idx_sdr_unknown_retention
    ON public.security_delivery_request (execution_stage, stage_provenance, finished_at)
    WHERE idempotency_key IS NOT NULL;

-- 2. 扩展 auth_challenge：持久化 Redis 风控状态协调intent与退避重试元数据
ALTER TABLE public.auth_challenge
    ADD COLUMN IF NOT EXISTS risk_sync_state VARCHAR(32) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS risk_sync_target VARCHAR(24) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS risk_sync_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS risk_sync_next_retry_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS risk_sync_last_error_code VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS risk_sync_claimed_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS risk_sync_updated_at TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN public.auth_challenge.risk_sync_state IS
    'Redis风控状态协调状态：none / sync_pending / retryable_failure / synced / reservation_missing / conflict / manual_review_required';
COMMENT ON COLUMN public.auth_challenge.risk_sync_target IS
    '待同步到Redis风控预占键的目标状态：accepted / rejected / unknown / delivered';
COMMENT ON COLUMN public.auth_challenge.risk_sync_attempts IS
    'Redis风控状态补偿同步累计尝试次数';
COMMENT ON COLUMN public.auth_challenge.risk_sync_next_retry_at IS
    'Redis风控补偿下次允许重试时间戳（指数退避）';
COMMENT ON COLUMN public.auth_challenge.risk_sync_last_error_code IS
    'Redis风控状态协调最近一次标准化失败原因码（不含PII）';
COMMENT ON COLUMN public.auth_challenge.risk_sync_claimed_at IS
    '补偿Worker短租约占用时间（防止长持DB锁期间执行Redis网络I/O）';
COMMENT ON COLUMN public.auth_challenge.risk_sync_updated_at IS
    'Redis风控协调状态最近更新时间';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_auth_challenge_risk_sync_state'
          AND conrelid = 'public.auth_challenge'::regclass
    ) THEN
        ALTER TABLE public.auth_challenge
            ADD CONSTRAINT chk_auth_challenge_risk_sync_state
            CHECK (risk_sync_state IN (
                'none',
                'sync_pending',
                'retryable_failure',
                'synced',
                'reservation_missing',
                'conflict',
                'manual_review_required'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_auth_challenge_risk_sync_target'
          AND conrelid = 'public.auth_challenge'::regclass
    ) THEN
        ALTER TABLE public.auth_challenge
            ADD CONSTRAINT chk_auth_challenge_risk_sync_target
            CHECK (risk_sync_target IS NULL OR risk_sync_target IN (
                'accepted', 'rejected', 'unknown', 'delivered'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_auth_challenge_risk_sync_pending
    ON public.auth_challenge (risk_sync_state, risk_sync_next_retry_at, created_at)
    WHERE risk_sync_state IN ('sync_pending', 'retryable_failure');

COMMIT;
