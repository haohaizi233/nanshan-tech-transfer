-- 017: 内容关闭/下线原因保留为枚举 + 补充说明，便于业务分析与推荐负反馈。
ALTER TABLE public.demand
    ADD COLUMN IF NOT EXISTS closure_reason_code VARCHAR(32) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS closure_reason_note VARCHAR(500) DEFAULT NULL;
ALTER TABLE public.achievement
    ADD COLUMN IF NOT EXISTS offline_reason_code VARCHAR(32) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS offline_reason_note VARCHAR(500) DEFAULT NULL;
ALTER TABLE public.demand DROP CONSTRAINT IF EXISTS chk_demand_closure_reason;
ALTER TABLE public.demand ADD CONSTRAINT chk_demand_closure_reason CHECK (
    closure_reason_code IS NULL OR closure_reason_code IN ('fulfilled', 'budget_changed', 'timeline_changed', 'duplicate', 'no_longer_needed', 'other')
);
ALTER TABLE public.achievement DROP CONSTRAINT IF EXISTS chk_achievement_offline_reason;
ALTER TABLE public.achievement ADD CONSTRAINT chk_achievement_offline_reason CHECK (
    offline_reason_code IS NULL OR offline_reason_code IN ('cooperated', 'expired', 'superseded', 'duplicate', 'no_longer_available', 'other')
);
