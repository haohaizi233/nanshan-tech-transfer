CREATE TABLE IF NOT EXISTS public.ai_chat_session (
    user_id BIGINT PRIMARY KEY REFERENCES public.app_user(id) ON DELETE CASCADE,
    generation BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.ai_chat_turn
    ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(16) NOT NULL DEFAULT 'sync',
    ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS execution_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS worker_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS reference JSONB,
    ADD COLUMN IF NOT EXISTS stage VARCHAR(24) NOT NULL DEFAULT 'routing',
    ADD COLUMN IF NOT EXISTS stage_seq BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS queue_deadline TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_deadline TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS context_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS query_plan JSONB,
    ADD COLUMN IF NOT EXISTS user_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS assistant_message_id BIGINT;

ALTER TABLE public.ai_chat_turn DROP CONSTRAINT IF EXISTS ck_ai_chat_turn_status;
ALTER TABLE public.ai_chat_turn ADD CONSTRAINT ck_ai_chat_turn_status
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed'));

ALTER TABLE public.ai_chat_message
    ADD COLUMN IF NOT EXISTS turn_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_ai_chat_turn_queue ON public.ai_chat_turn(id)
    WHERE execution_mode = 'durable' AND status = 'queued';

CREATE TABLE IF NOT EXISTS public.ai_chat_execution_slot (
    slot_id INTEGER PRIMARY KEY CHECK (slot_id > 0),
    execution_id VARCHAR(64),
    lease_until TIMESTAMPTZ
);
INSERT INTO public.ai_chat_execution_slot(slot_id)
    SELECT generate_series(1, 4) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ai_chat_worker (
    worker_id VARCHAR(64) PRIMARY KEY,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent_reachable BOOLEAN NOT NULL DEFAULT false,
    capacity INTEGER NOT NULL DEFAULT 4
);

CREATE TABLE IF NOT EXISTS public.ai_chat_tombstone (
    user_id BIGINT NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
    turn_id VARCHAR(64) NOT NULL,
    request_hash VARCHAR(64),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '7 days'),
    PRIMARY KEY(user_id, turn_id)
);
CREATE INDEX IF NOT EXISTS idx_ai_chat_tombstone_expiry ON public.ai_chat_tombstone(expires_at);
