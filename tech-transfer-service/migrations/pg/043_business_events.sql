-- P3-10 产品业务分析事件表（与安全审计日志 audit_log / security_audit_log 严格隔离）
BEGIN;

CREATE TABLE IF NOT EXISTS public.product_event (
    id BIGSERIAL PRIMARY KEY,
    event_name VARCHAR(64) NOT NULL,
    actor_user_id BIGINT,
    target_type VARCHAR(32),
    target_id BIGINT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_event_name_created_at
    ON public.product_event (event_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_product_event_created_at
    ON public.product_event (created_at DESC);

COMMIT;
