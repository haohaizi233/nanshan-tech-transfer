-- 026_ai_chat_turns.sql
-- Idempotent per-user AI chat turn state for client write-ahead recovery.

CREATE TABLE IF NOT EXISTS public.ai_chat_turn (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
    turn_id        VARCHAR(64) NOT NULL,
    status         VARCHAR(16) NOT NULL DEFAULT 'running',
    user_message   TEXT NOT NULL,
    reply          TEXT,
    cards          JSONB,
    error_message  TEXT,
    error_code     VARCHAR(32),
    error_status   INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ,
    CONSTRAINT uq_ai_chat_turn_user_turn UNIQUE (user_id, turn_id),
    CONSTRAINT ck_ai_chat_turn_status CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT ck_ai_chat_turn_error_status CHECK (error_status IS NULL OR error_status BETWEEN 400 AND 599)
);

CREATE INDEX IF NOT EXISTS idx_ai_chat_turn_user_updated
    ON public.ai_chat_turn(user_id, updated_at DESC);
