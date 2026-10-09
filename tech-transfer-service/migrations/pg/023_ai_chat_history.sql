-- 023_ai_chat_history.sql
-- AI 聊天记录入库（快照）。
-- 切页/重登后历史不丢；推荐卡片存完整快照，加载即开即用、零回查。

CREATE TABLE IF NOT EXISTS public.ai_chat_message (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
    role       VARCHAR(16) NOT NULL,                -- 'user' | 'assistant'
    content    TEXT NOT NULL DEFAULT '',            -- 文本内容
    cards      JSONB,                               -- assistant 推荐卡片时存完整卡片快照数组
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_chat_msg_user_id ON public.ai_chat_message(user_id, id);
