# SMS Security Gateway Implementation Plan

**Goal:** Harden existing SMS recovery and binding without duplicating Auth.
**Architecture:** Reuse auth_challenge/account_contact/recovery_grant/auth_session/audit_log. Add an isolated Redis atomic risk/quota module and request-security component. Harden SendCloud via an idempotent task interface. Public recovery queues work after a uniform opaque response.
**Spec:** User attachment 7693d981-8158-40f0-9a35-8370438f2b99, SMS Security Gateway.

## Constraints and rulings
- Existing HEAD b5bfb69; working tree initially clean. User authorizes immediate actual development using existing branch; no production deployment, no real SMS tests.
- Preserve existing authentication and role semantics. Only reset_password and bind_phone SMS uses enabled; internal password_recovery maps to reset_password at provider boundary.
- Use real Redis and isolated PostgreSQL schemas for concurrency tests if available; never mutate business rows.
- Risk adapter defaults to CHALLENGE for soft NAT/device anomalies; without a configured human-verification adapter this fails closed.
- API acceptance and final delivery are distinct. Unknown provider outcomes retain quota.

## Tasks
- [x] Atomic Redis risk engine: phone/IP/device/account/pair/distinct dimensions, keyed digests, business timezone day TTL, idempotent quota transitions.
- [x] Provider hardening: sendRequestId, structured receipt/errors, controlled retries, status query, no sensitive SMS logs.
- [x] Request security: bounded JSON schema, source and HTTPS/origin checks, HMAC method/path/body/time/nonce/client authentication with atomic replay guard.
- [x] Integrate existing recovery/binding, safe business eligibility, uniform durable queued recovery response, pending-send lifecycle and audit; repair expiry/attempt persistence and transaction consumption.
- [x] Real dependency concurrent integration tests, 514-test regression, rules and deployment/report documentation, final security review.

## Execution evidence and rulings
- Initial regression proved 7 preexisting failures (strict schemas, OTP/grant expiry, rolled-back failed attempts, cross-purpose binding); repaired with green tests.
- Redis uses isolated Windows Redis 5.0.14.1 on 16379 for tests only; PostgreSQL uses random disposable schemas with actual 033/034 migrations. Both dependencies exercised, no business rows altered.
- Ruling: new contact verification provenance defaults to legacy_unknown because 033 backfilled credential phones without ownership proof. Historical users need re-verification/audited proof; availability cost is intentional.
- Ruling: nonce default effective TTL601 covers the full +/-300-second signature validity window; simple TTL300 permits future-timestamp replay after nonce expiry.
- Ruling: BackgroundTasks only triggers a durable work queue; recovery outbox is persisted uniformly before account lookup, atomic queued-to-processing claim, no automatic resend of a processing/unknown task.
- Ruling: human-verification provider is unspecified and unconfigured, so CHALLENGE fails closed. Platform attestation requires a configured server adapter. No claim of live validation.
- Final implementation/test/deployment report: docs/auth/06-sms-security-gateway.md. No commit/push/deploy, real SMS test disabled; known SendCloud 590/4121 remains external acceptance work.

## Review focus
- Request exception rolls back verification attempt updates.
- Public response shape/timing reveals account binding.
- Provider timeout duplicates paid sends or frees unknown quota.
- Account changes after challenge issuance bypass recovery eligibility.
- Redis outage or proxy spoofing bypasses controls.
