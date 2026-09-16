-- 016: 对接治理——并行/限额库存、运营跟进、结构化结果与通知中心索引
-- 默认 parallel + NULL（不限量）；exclusive 强制单席位。

ALTER TABLE public.demand
    ADD COLUMN IF NOT EXISTS cooperation_policy VARCHAR(16) NOT NULL DEFAULT 'parallel',
    ADD COLUMN IF NOT EXISTS cooperation_capacity INT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS cooperation_remaining INT DEFAULT NULL;
ALTER TABLE public.achievement
    ADD COLUMN IF NOT EXISTS cooperation_policy VARCHAR(16) NOT NULL DEFAULT 'parallel',
    ADD COLUMN IF NOT EXISTS cooperation_capacity INT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS cooperation_remaining INT DEFAULT NULL;

ALTER TABLE public.demand DROP CONSTRAINT IF EXISTS chk_demand_cooperation_capacity;
ALTER TABLE public.demand ADD CONSTRAINT chk_demand_cooperation_capacity CHECK (
    cooperation_policy IN ('parallel', 'exclusive')
    AND (cooperation_capacity IS NULL OR cooperation_capacity > 0)
    AND (cooperation_remaining IS NULL OR cooperation_remaining >= 0)
    AND (cooperation_capacity IS NULL OR cooperation_remaining IS NULL OR cooperation_remaining <= cooperation_capacity)
    AND (cooperation_policy <> 'exclusive' OR cooperation_capacity IS NULL OR cooperation_capacity = 1)
);
ALTER TABLE public.achievement DROP CONSTRAINT IF EXISTS chk_achievement_cooperation_capacity;
ALTER TABLE public.achievement ADD CONSTRAINT chk_achievement_cooperation_capacity CHECK (
    cooperation_policy IN ('parallel', 'exclusive')
    AND (cooperation_capacity IS NULL OR cooperation_capacity > 0)
    AND (cooperation_remaining IS NULL OR cooperation_remaining >= 0)
    AND (cooperation_capacity IS NULL OR cooperation_remaining IS NULL OR cooperation_remaining <= cooperation_capacity)
    AND (cooperation_policy <> 'exclusive' OR cooperation_capacity IS NULL OR cooperation_capacity = 1)
);

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS slot_reserved BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_contact_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS next_followup_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS outcome_status VARCHAR(32) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS outcome_cooperation_mode VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS outcome_signed BOOLEAN DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS outcome_amount_wan NUMERIC(14,2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS outcome_failure_reason VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS outcome_note VARCHAR(1000) DEFAULT NULL;
ALTER TABLE public.cooperation_intent DROP CONSTRAINT IF EXISTS chk_coop_outcome_status;
ALTER TABLE public.cooperation_intent ADD CONSTRAINT chk_coop_outcome_status CHECK (
    outcome_status IS NULL OR outcome_status IN ('cooperated', 'not_cooperated', 'unknown')
);
CREATE INDEX IF NOT EXISTS idx_coop_followup_due
    ON public.cooperation_intent (next_followup_at ASC)
    WHERE handling_mode='assisted' AND status='pending';
CREATE INDEX IF NOT EXISTS idx_notification_inbox_recipient_time
    ON public.notification_inbox (recipient_user_id, occurred_at DESC);
