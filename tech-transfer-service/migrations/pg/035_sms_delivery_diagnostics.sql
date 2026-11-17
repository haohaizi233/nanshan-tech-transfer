BEGIN;
ALTER TABLE public.security_delivery_request
    ADD COLUMN IF NOT EXISTS request_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS outcome VARCHAR(32),
    ADD COLUMN IF NOT EXISTS failure_stage VARCHAR(32),
    ADD COLUMN IF NOT EXISTS failure_reason VARCHAR(64),
    ADD COLUMN IF NOT EXISTS provider_status INT,
    ADD COLUMN IF NOT EXISTS risk_rule_id VARCHAR(96),
    ADD COLUMN IF NOT EXISTS provider_ids JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS outcome_unknown BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS retryable BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS elapsed_ms INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS provider_called BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_security_delivery_request_request_id
    ON public.security_delivery_request(request_id);
-- Backfill correlation only, never infer success for old 'finished' records.
UPDATE public.security_delivery_request SET request_id=LEFT(payload->>'request_id',64)
    WHERE request_id IS NULL;
UPDATE public.security_delivery_request SET state='legacy_finished_unknown',
    outcome='INTERNAL_ERROR',failure_stage='legacy',failure_reason='legacy_outcome_not_recorded'
    WHERE state='finished';
ALTER TABLE public.auth_challenge
    ADD COLUMN IF NOT EXISTS delivery_status_code INT,
    ADD COLUMN IF NOT EXISTS delivery_reason_code VARCHAR(32);
COMMIT;
