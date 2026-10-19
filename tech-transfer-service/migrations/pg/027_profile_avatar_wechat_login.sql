BEGIN;
ALTER TABLE public.user_profile
    ADD COLUMN IF NOT EXISTS avatar_file_id BIGINT REFERENCES public.file_object(id) ON DELETE RESTRICT;
ALTER TABLE public.user_credential
    ADD COLUMN IF NOT EXISTS password_configured BOOLEAN NOT NULL DEFAULT TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS uk_wechat_user_binding
    ON public.external_identity (tenant_id, user_id)
    WHERE issuer = 'wechat-mini' AND unlinked_at IS NULL;
COMMIT;
