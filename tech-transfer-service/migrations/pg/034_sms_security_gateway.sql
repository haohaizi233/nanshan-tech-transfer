-- Add send metadata to the existing challenge; never store raw OTPs.
BEGIN;
-- 033 auto-backfilled credential phones without a verifiable ownership source.
-- Do not infer ownership from the presence of a phone number or timestamp.
ALTER TABLE public.account_contact ADD COLUMN IF NOT EXISTS verification_method VARCHAR(24) NOT NULL DEFAULT 'legacy_unknown';
COMMENT ON COLUMN public.account_contact.verification_method IS
    'legacy_unknown (not recovery eligible) / sms / email / wechat / manual; promote legacy rows only after audited proof';
ALTER TABLE public.auth_challenge ADD COLUMN IF NOT EXISTS send_request_id VARCHAR(128);
ALTER TABLE public.auth_challenge ADD COLUMN IF NOT EXISTS send_state VARCHAR(24);
ALTER TABLE public.auth_challenge ADD COLUMN IF NOT EXISTS provider_message_ids JSONB NOT NULL DEFAULT '[]';
CREATE UNIQUE INDEX IF NOT EXISTS uk_auth_challenge_send_request
    ON public.auth_challenge(send_request_id) WHERE send_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auth_challenge_send_state
    ON public.auth_challenge(send_state, created_at) WHERE channel='sms';
COMMENT ON COLUMN public.auth_challenge.send_state IS
    'reserved / accepted / rejected / unknown / delivered / delivery_failed; accepted is not delivered';
-- Uniform public requests are persisted before account lookup. This is a work
-- queue, not a second OTP/challenge store. No plaintext verification code.
CREATE TABLE IF NOT EXISTS public.security_delivery_request (
    id UUID PRIMARY KEY,
    payload JSONB NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_security_delivery_request_queued
    ON public.security_delivery_request(created_at) WHERE state='queued';
COMMENT ON TABLE public.security_delivery_request IS
    'Internal recovery delivery queue; restricted PII, retain max 7 days, no public status endpoint';
COMMIT;
