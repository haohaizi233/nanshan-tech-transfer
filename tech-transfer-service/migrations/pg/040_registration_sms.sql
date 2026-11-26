BEGIN;

ALTER TABLE public.auth_challenge ALTER COLUMN user_id DROP NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.auth_challenge'::regclass
          AND conname = 'ck_auth_challenge_registration_owner'
    ) THEN
        ALTER TABLE public.auth_challenge
            ADD CONSTRAINT ck_auth_challenge_registration_owner
            CHECK (user_id IS NOT NULL OR
                   (purpose = 'register' AND channel = 'sms' AND status <> 'consumed'));
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uk_auth_challenge_active_registration_phone
    ON public.auth_challenge (destination_fingerprint)
    WHERE purpose = 'register' AND user_id IS NULL AND status IN ('pending_send', 'pending');

COMMIT;
