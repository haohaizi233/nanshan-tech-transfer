-- 024: auth_session 增加 consumed_at，refresh 令牌轮转时记录消费时间

BEGIN;

ALTER TABLE public.auth_session
    ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMPTZ DEFAULT NULL;

COMMIT;
