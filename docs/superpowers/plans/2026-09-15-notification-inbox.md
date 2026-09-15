# Notification Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为管理后台与小程序提供持久化未读通知、200ms 轻量角标刷新和按时间倒序的待办队列。

**Architecture:** 新增后端通知收件箱模块，状态流转在原事务中写入去重通知；两个摘要接口仅返回数量。后台布局和小程序 App 各自维护单例且无重入的摘要轮询，业务详情只在用户进入目标页面时加载并消费对应分类未读。

**Tech Stack:** FastAPI、PostgreSQL、Vue 3 管理后台、uni-app Vue 2、小程序 tab bar、Python/Node 回归测试。

**Spec:** `docs/superpowers/specs/2026-09-15-notification-inbox-design.md`

## Global Constraints

- 摘要轮询间隔固定为 200ms，只返回数字，不得请求业务详情或列表。
- 同一客户端同一时刻只允许一条摘要请求；页面/应用隐藏即停止。
- 通知写入与业务状态变更在同一事务，使用 `dedupe_key` 唯一约束。
- 仅成功加载对应业务页后才能将该类别标为已读。
- 待办与通知按 `occurred_at DESC, id DESC` 排列。

---

### Task 1: 通知收件箱持久化与用户摘要 API

**Files:**
- Create: `tech-transfer-service/migrations/pg/012_notification_inbox.sql`
- Create: `tech-transfer-service/modules/notification/service.py`
- Create: `tech-transfer-service/routes/notification.py`
- Modify: `tech-transfer-service/app.py`
- Test: `tech-transfer-service/test_notification_inbox.py`

**Interfaces:**
- Produces `emit_notification(cur, *, recipient_user_id, category, event_type, source_type, source_id, title, body, target_path, occurred_at)`。
- Produces `GET /me/notifications/summary` and `POST /me/notifications/read`.

- [ ] **Step 1: Write the failing integration test**

```python
created = emit_notification(cur, recipient_user_id=user_id, category="review",
    event_type="demand.approved", source_type="demand", source_id=42,
    title="需求审核已通过", body=None, target_path="/pages/mine-publications/mine-publications")
assert created["created"] is True
assert get_notification_summary(user_id) == {"total": 1, "categories": {"review": 1}}
assert mark_notification_category_read(user_id, "review")["updated"] == 1
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python test_notification_inbox.py`
Expected: FAIL because the migration, emitter and routes do not exist.

- [ ] **Step 3: Implement migration and service**

Create `notification_inbox` with recipient/category/event/source fields, `read_at`, `occurred_at`, and unique `dedupe_key`; create recipient/read/category indexes. Implement `emit_notification` with `INSERT ... ON CONFLICT (dedupe_key) DO NOTHING`, summary grouping only unread rows, and category-only read update guarded by `recipient_user_id`.

- [ ] **Step 4: Register guarded routes**

Use `identity` in `routes/notification.py`, return existing `success()` envelopes, and include the router in `app.py`.

- [ ] **Step 5: Run the test and verify GREEN**

Run: `python test_notification_inbox.py`
Expected: PASS including dedupe, per-user isolation and category-only read tests.

### Task 2: Emit user notifications from existing state machines

**Files:**
- Modify: `tech-transfer-service/modules/admin/service.py`
- Modify: `tech-transfer-service/modules/cooperation/service.py`
- Modify: `tech-transfer-service/modules/institution_registration/service.py`
- Modify: `tech-transfer-service/modules/organization_membership/service.py`
- Test: `tech-transfer-service/test_notification_inbox.py`

**Interfaces:**
- Consumes `emit_notification()` from Task 1 and an existing transaction cursor.
- Produces exactly one notification for each review, cooperation, organization and membership status transition.

- [ ] **Step 1: Extend the failing test with representative transitions**

```python
approve_demand(...)
assert unread_for(owner_id, "review") == 1
create_intent(initiator_id, ...)
assert unread_for(target_owner_id, "cooperation") == 1
accept_intent(target_owner_id, ...)
assert unread_for(initiator_id, "cooperation") == 1
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python test_notification_inbox.py`
Expected: FAIL because status actions do not emit inbox rows.

- [ ] **Step 3: Emit within the existing transactions**

Call `emit_notification(cur, ...)` after successful state updates and before committing. Map review results to content owners, direct cooperation transitions to the other participant, assisted transitions to the initiator, and organization/membership application actions to administrators and applicants as specified.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python test_notification_inbox.py`
Expected: PASS with no duplicate row after a retried event.

### Task 3: 后台待办排序、摘要与导航角标

**Files:**
- Modify: `tech-transfer-service/modules/admin/service.py`
- Modify: `tech-transfer-service/routes/admin_ops.py`
- Modify: `nanshan-frontend/src/components/layout/AdminHeader.vue`
- Modify: `nanshan-frontend/src/components/layout/AdminSidebar.vue`
- Modify: `nanshan-frontend/src/layouts/AdminLayout.vue`
- Modify: `nanshan-frontend/src/views/admin/OverviewView.vue`
- Test: `tech-transfer-service/test_admin_dashboard.py`
- Test: `nanshan-frontend/src/**/__tests__/admin-notification-summary.test.js`

**Interfaces:**
- Produces `GET /admin/notifications/summary` with `{ total, categories: { review, cooperation, organization, membership } }`.
- Consumes the summary through one layout-level poller.

- [ ] **Step 1: Write failing backend and frontend tests**

```python
assert dashboard_todos(100)["list"][0]["createdAt"] >= dashboard_todos(100)["list"][1]["createdAt"]
assert admin_notification_summary()["categories"]["review"] == 2
```

```js
expect(source).toContain("/admin/notifications/summary")
expect(source).toContain('200')
expect(source).toContain('inFlight')
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python test_admin_dashboard.py` and the frontend test command used by `nanshan-frontend/package.json`.
Expected: FAIL because no summary endpoint or layout poller exists and todos sort oldest first.

- [ ] **Step 3: Implement backend summary and newest-first queue**

Add a single count query for each category under `admin_identity`; change `dashboard_todos()` ordering to `created_at DESC, id DESC` while preserving its `limit` cap.

- [ ] **Step 4: Implement layout-owned badge polling**

Create the poller in `AdminLayout.vue`, with an in-flight guard and lifecycle cleanup. Pass the reactive category counts to header/sidebar; render the bell total and badges on cooperation, membership review, and relevant review menus. Do not call `loadSummary`, `loadTrend`, `loadTodo`, or any table loader from this poller.

- [ ] **Step 5: Make the overview queue scroll independently**

Load up to 100 initial todo rows in `OverviewView.vue`; apply fixed maximum height and `overflow-y: auto` to `.todo-list` without altering the page layout.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `python test_admin_dashboard.py` and the frontend test command used by `nanshan-frontend/package.json`.
Expected: PASS.

### Task 4: 小程序摘要轮询、tab 角标与分类已读

**Files:**
- Create: `南山小程序/南山/subpackages/tech-transfer/api/notifications.js`
- Create: `南山小程序/南山/utils/notification-poller.js`
- Modify: `南山小程序/南山/App.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue`
- Modify: relevant publication, cooperation, institution application and membership application pages
- Test: `南山小程序/南山/tests/notification-poller.test.mjs`

**Interfaces:**
- Produces `startNotificationPolling()`, `stopNotificationPolling()`, `refreshNotificationSummary()` and `markNotificationCategoryRead(category)`.
- Uses `uni.setTabBarBadge({ index: 1, text })` and `uni.removeTabBarBadge({ index: 1 })`.

- [ ] **Step 1: Write failing unit/source tests**

```js
assert.equal(formatTabBadge(0), '')
assert.equal(formatTabBadge(100), '99+')
assert.match(appSource, /startNotificationPolling\(\)/)
assert.match(appSource, /stopNotificationPolling\(\)/)
assert.match(pollerSource, /200/)
assert.match(pollerSource, /inFlight/)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/notification-poller.test.mjs`
Expected: FAIL because no notification API or poller exists.

- [ ] **Step 3: Implement the lightweight singleton**

Implement the summary API and a timer that schedules every 200ms only after the previous request settles. Update only tab badge state; keep the last successful counts after errors. Start in `App.onShow`, stop in `App.onHide`, and trigger one immediate refresh on return.

- [ ] **Step 4: Consume notifications only after detail loads**

On the relevant page `onShow`/successful load methods, call `markNotificationCategoryRead(category)` and then `refreshNotificationSummary()`. Do not add a detail-list call to the poller.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `node --test tests/notification-poller.test.mjs tests/product-backlog-fixes.test.mjs tests/fixed-navigation-and-mine-visuals.test.mjs`
Expected: PASS.

### Task 5: Cross-system verification

**Files:**
- Verify only: notification migration, backend routes, admin layout, mini-program poller

- [ ] **Step 1: Run backend notification and existing cooperation regressions**

Run: `python test_notification_inbox.py; python test_assisted_cooperation.py`
Expected: both suites PASS.

- [ ] **Step 2: Run admin frontend tests and mini-program regressions**

Run: the configured `nanshan-frontend` test script and `node --test tests/notification-poller.test.mjs tests/product-backlog-fixes.test.mjs tests/fixed-navigation-and-mine-visuals.test.mjs` from `南山小程序/南山`.
Expected: all PASS.

- [ ] **Step 3: Inspect exact diff**

Run: `git diff --check; git diff --stat`
Expected: no whitespace errors; the 200ms code only targets summary endpoints.
