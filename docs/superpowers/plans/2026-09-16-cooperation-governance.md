# Cooperation Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver explicit contact authorization, parallel/exclusive inventory control, assisted-operation follow-up, structured cooperation outcomes, and per-notification read workflows.

**Architecture:** PostgreSQL migrations add independent content inventory fields, operational fields on `cooperation_intent`, and a one-to-one `cooperation_outcome` table. Service-layer transactional transitions reserve or release inventory, validate outcome/close reasons, and emit notification records. FastAPI routes expose focused operations; Vue/uni-app consume notification lists while summary polling remains lightweight.

**Tech Stack:** FastAPI, psycopg2/PostgreSQL, Vue 3/Vite, uni-app, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-16-cooperation-governance-design.md`

## Global Constraints

- `contactShareConsent` is accepted only when it is Boolean `true`.
- New content defaults to `parallel` and `unlimited`; `exclusive` requires one limited slot.
- Inventory updates occur through guarded SQL in the same transaction as the intent transition.
- Summary polling is 5 seconds and must not load notification detail data.
- Existing records remain valid without inventory reservation or outcome rows.

---

### Task 1: Data-model migration and repository primitives

**Files:**
- Create: `tech-transfer-service/migrations/pg/014_cooperation_governance.sql`
- Modify: `tech-transfer-service/modules/cooperation/service.py`
- Test: `tech-transfer-service/test_cooperation_governance.py`

**Interfaces:**
- Produces content columns `cooperation_policy`, `inventory_mode`, `inventory_total`, `available_slots`, `manual_offline_at`.
- Produces intent columns `last_contact_at`, `next_followup_at`, `attempt_count`, `sla_due_at`, `inventory_reserved_at`, `close_reason_code`, `close_reason_note`.
- Produces `cooperation_outcome(intent_id UNIQUE, outcome_type, contract_signed, final_cooperation_mode, deal_amount_wan, failure_reason_code, failure_reason_note, recorded_by_user_id, recorded_at)`.

- [ ] **Step 1: Write failing migration-contract tests**

```python
def test_contact_consent_requires_literal_true():
    with pytest.raises(BizError):
        create_intent(USER_1, 'u1', {'targetType': 'demand', 'targetId': 1})

def test_limited_inventory_accepts_only_remaining_slots():
    assert reserve_inventory(cur, 'demand', DEMAND_ID) is True
    assert reserve_inventory(cur, 'demand', DEMAND_ID) is False
```

- [ ] **Step 2: Run the targeted test module and confirm authorization and reservation failures.**

Run: `python -m pytest test_cooperation_governance.py -q`

- [ ] **Step 3: Add idempotent migration and pure service helpers.**

```python
def reserve_inventory(cur, target_type, target_id):
    cur.execute(f"UPDATE {table} SET available_slots=available_slots-1 "
                "WHERE id=%s AND inventory_mode='limited' AND available_slots>0 RETURNING id", (target_id,))
    return cur.fetchone() is not None
```

Migration checks preserve defaults, require positive totals for limited content, and create lookup indexes for available content, overdue follow-up, and outcome reporting.

- [ ] **Step 4: Run migration-contract tests and SQL syntax check.**

Run: `python -m pytest test_cooperation_governance.py -q`

### Task 2: Intent state transitions, authorization, inventory and outcomes

**Files:**
- Modify: `tech-transfer-service/modules/cooperation/service.py`
- Modify: `tech-transfer-service/routes/cooperation.py`
- Modify: `tech-transfer-service/test_assisted_cooperation.py`
- Modify: `tech-transfer-service/test_cooperation_governance.py`

**Interfaces:**
- Consumes Task 1 inventory and outcome columns.
- Produces `complete_intent(..., outcome: dict)` and validated `reasonCode` / `reasonNote` transition bodies.
- Produces `cooperationPolicy`, `inventoryMode`, `availableSlots`, `outcome`, `closeReasonCode` and `closeReasonNote` in intent detail.

- [ ] **Step 1: Add failing lifecycle tests.**

```python
def test_parallel_accept_does_not_auto_reject_other_pending(): ...
def test_exclusive_accept_auto_rejects_other_pending(): ...
def test_cancelled_reserved_intent_returns_slot(): ...
def test_completed_signed_intent_consumes_slot_and_persists_outcome(): ...
def test_close_reason_other_requires_note(): ...
```

- [ ] **Step 2: Run lifecycle tests and confirm each fails against current behavior.**

Run: `python -m pytest test_assisted_cooperation.py test_cooperation_governance.py -q`

- [ ] **Step 3: Implement guarded state effects.**

`accept` loads policy under row lock, reserves limited inventory before changing status, and only auto-rejects when policy is `exclusive`. `cancel`, `reject`, and failed outcomes release an existing reservation once. `complete` validates a structured outcome and keeps a success reservation consumed.

- [ ] **Step 4: Run lifecycle tests and compile service/routes.**

Run: `python -m pytest test_assisted_cooperation.py test_cooperation_governance.py -q && python -m py_compile modules/cooperation/service.py routes/cooperation.py`

### Task 3: Assisted-operation follow-up and SLA

**Files:**
- Modify: `tech-transfer-service/modules/cooperation/service.py`
- Modify: `tech-transfer-service/modules/admin/service.py`
- Modify: `tech-transfer-service/routes/admin_ops.py`
- Modify: `nanshan-frontend/src/views/admin/CooperationView.vue`
- Test: `tech-transfer-service/test_cooperation_governance.py`

**Interfaces:**
- Produces admin operation `update_assist_followup(intent_id, actor, {assistStatus, note, nextFollowupAt, slaDueAt, contacted})`.
- Consumes Task 1 fields and returns `lastContactAt`, `nextFollowupAt`, `attemptCount`, `slaDueAt`, and `isOverdue`.

- [ ] **Step 1: Write failing follow-up tests.**

```python
def test_contacted_follow_up_increments_attempts_and_sets_last_contact(): ...
def test_overdue_assisted_items_sort_before_non_overdue_items(): ...
```

- [ ] **Step 2: Run the follow-up tests and confirm failure.**

Run: `python -m pytest test_cooperation_governance.py -q`

- [ ] **Step 3: Add admin endpoint and UI controls.**

The endpoint validates assisted ownership and future timestamps, increments attempts only when `contacted` is true, and returns updated row state. The admin list exposes next follow-up, attempt count and an overdue filter; no ordinary user response includes internal notes.

- [ ] **Step 4: Run backend tests and `npm run build` for the admin frontend.**

Run: `python -m pytest test_cooperation_governance.py -q && npm run build`

### Task 4: Notification record APIs and clients

**Files:**
- Modify: `tech-transfer-service/modules/notification/service.py`
- Modify: `tech-transfer-service/routes/notification.py`
- Modify: `tech-transfer-service/migrations/pg/012_notification_inbox.sql`
- Modify: `南山小程序/南山/utils/notification-poller.js`
- Create: `南山小程序/南山/subpackages/tech-transfer/pages/notifications/notifications.vue`
- Modify: `南山小程序/南山/pages.json`
- Modify: `nanshan-frontend/src/components/layout/AdminHeader.vue`
- Test: `tech-transfer-service/test_notification_api.py`
- Test: `南山小程序/南山/tests/notification-poller.test.mjs`

**Interfaces:**
- Produces list, one-read and read-all notification methods; list cursor is `(occurred_at, id)`.
- Produces mini-program client functions `listNotifications`, `markNotificationRead`, `markAllNotificationsRead` from a subpackage page-local API module.

- [ ] **Step 1: Write failing ownership/read-state and polling-interval tests.**

```python
def test_notification_list_never_returns_another_users_row(): ...
def test_mark_one_notification_read_is_idempotent(): ...
```

```js
assert.match(source, /setInterval\(refreshNotificationBadge, 5000\)/)
```

- [ ] **Step 2: Run the new tests and confirm their expected failure.**

Run: `python -m pytest test_notification_api.py -q && node --test tests/notification-poller.test.mjs`

- [ ] **Step 3: Implement notification APIs and page interactions.**

Single read uses `recipient_user_id` in its UPDATE predicate; read-all supports an optional valid category. The mini-program notification page marks a clicked row before navigating to `targetPath`; its API stays inside the subpackage so `App.vue` remains free of subpackage imports. The admin header opens a list drawer. Both pollers use 5000 ms and retain in-flight guards.

- [ ] **Step 4: Run notification tests, mini-program source tests and admin production build.**

Run: `python -m pytest test_notification_api.py -q && node --test tests/notification-poller.test.mjs tests/product-backlog-fixes.test.mjs && npm run build`

### Task 5: Content publication UI, compatibility checks and final verification

**Files:**
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/post-demand/post-demand.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/post-result/post-result.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/dock-detail/dock-detail.vue`
- Modify: `nanshan-frontend/src/views/admin/RequirementDetailView.vue`
- Modify: `nanshan-frontend/src/views/admin/AchievementDetailView.vue`
- Test: `南山小程序/南山/tests/cooperation-governance.test.mjs`
- Test: `tech-transfer-service/test_cooperation_governance.py`

**Interfaces:**
- Consumes content policy and inventory fields from Task 1 and intent detail from Task 2.
- Produces publication payload fields `cooperationPolicy`, `inventoryMode`, `inventoryTotal` and explicit current inventory display.

- [ ] **Step 1: Write failing UI-source tests.**

```js
assert.match(postDemand, /cooperationPolicy/)
assert.match(postResult, /inventoryMode/)
assert.match(dockDetail, /availableSlots/)
```

- [ ] **Step 2: Run the source tests and confirm failure.**

Run: `node --test tests/cooperation-governance.test.mjs`

- [ ] **Step 3: Add publication controls and detail presentation.**

New forms initialize `parallel/unlimited`; selecting `exclusive` forces a single limited slot. Detail cards show remaining slots only for limited listings and suppress the new-intent action at zero availability. Admin detail shows policy, inventory and structured outcome without exposing contacts before the existing authorization threshold.

- [ ] **Step 4: Run all focused checks and inspect changes.**

Run: `python -m pytest test_assisted_cooperation.py test_cooperation_governance.py test_notification_api.py -q && node --test tests/notification-poller.test.mjs tests/product-backlog-fixes.test.mjs tests/cooperation-governance.test.mjs && npm run build && git diff --check`
