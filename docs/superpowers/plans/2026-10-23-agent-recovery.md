# Agent command and recovery repair

Goal: preserve local changes while integrating origin/master; restore evaluation commands and resumable progress without replaying uncertain writes.

Architecture: existing durable chat turns remain authoritative. Evaluation tasks retain their own IDs. SSE is a transport, never proof of task failure. WAL is scoped by account and turn.

Constraints: current worktree, no new framework, no deployment or automatic replay of unknown submissions.

- [x] Merge upstream and restore local hardening changes, retaining stash backup.
- [x] Add failing contract tests using actual Agent RouteResult payloads; align backend validation.
- [x] Add recovery and command parsing regressions; retain pending WAL after transport timeouts.
- [x] Link evaluation task IDs to chat cards and report navigation.
- [x] Verify streaming transport behavior and add mini-program chunk support with fallback.
- [x] Run focused Python and Node regressions and frontend builds; report remaining limitations.

Verification: Agent 73 tests plus 27 subtests; backend 84 tests; frontend command/recovery/stream tests and H5/Weixin builds pass. Device validation and deployment have not been performed. Evaluation deltas remain process-local, with authoritative database polling fallback for separate workers. Chat renders evaluation task links; report deltas render on the report page, not inside the chat bubble.

The original local changes remain uncommitted. The pre-merge stash is retained. Commands are currently deterministic for evaluation; search retains its existing language routing and match retains the published-demand picker. No automatic replay was added for unknown submissions.
