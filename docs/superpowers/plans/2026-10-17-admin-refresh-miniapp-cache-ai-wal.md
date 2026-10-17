# 管理端行级刷新、小程序缓存与 AI WAL 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理端变更只刷新目标行，小程序切页恢复有时效的页面状态，AI 对话通过客户端 WAL 与服务端幂等 turn 记录安全恢复，并将各批变更推送到 `origin/master`。

**Architecture:** 管理端用共享纯函数处理行合并、筛选失配和计数，由页面按已有详情 API 获取目标记录。小程序新增账号隔离、TTL 和显式失效的页面状态缓存，表单草稿复用现有草稿工具并补齐身份与时效约束。AI turn 在客户端发送前写 WAL，后端以用户和 turnId 唯一约束提供持久状态与幂等查询。

**Tech Stack:** Vue 3/Vite、uni-app/Vue、小程序 `uni` storage、FastAPI、PostgreSQL、pytest、Node.js `node:test`。

**Spec:** `docs/superpowers/specs/2026-10-17-admin-row-refresh-miniapp-cache-ai-wal-design.md`

## Global Constraints

- 保留现有登录/授权边界，不在页面缓存或 WAL 中保存认证凭证。
- 页面缓存按登录用户隔离；切换用户和退出时清除或隔离旧命名空间。
- 数据缓存 TTL：动态列表 2 分钟、详情 5 分钟、字典 30 分钟、草稿 24 小时。
- 页面切换继续使用当前导航栈策略，不改为无限堆叠页面。
- AI 重复 turnId 不重复调用模型；聊天记录清空同时清理 turn 状态。
- 不提交工作区中与本计划无关的修改，包括本地环境配置和其他未跟踪文件。

## Review Focus

- 管理操作改变状态/分类/关键词后，当前筛选行和计数需要同时正确更新。
- 创建记录发生在非第一页或不匹配筛选时，不能错误插行或重置分页。
- 同一设备切换用户后不能显示另一个账号的缓存或草稿。
- 缓存过期、损坏、存储失败或网络刷新失败时不能清空仍可用的页面状态。
- AI turn 恢复、重复 POST、清空聊天和失败重试不能重复生成或重复落消息。

---

### Task 1: 管理后台表单行级刷新

**Files:**
- Create: `nanshan-frontend/src/utils/adminRowRefresh.js`
- Test: `nanshan-frontend/src/utils/adminRowRefresh.test.mjs`
- Modify: `nanshan-frontend/src/views/admin/AchievementView.vue`
- Modify: `nanshan-frontend/src/views/admin/RequirementView.vue`
- Modify: `nanshan-frontend/src/views/admin/RequirementDetailView.vue`
- Modify: `nanshan-frontend/src/views/admin/CapitalView.vue`
- Modify: `nanshan-frontend/src/views/admin/InstitutionView.vue`
- Modify: `nanshan-frontend/src/views/admin/MembershipReviewView.vue`
- Modify: `nanshan-frontend/src/views/admin/UserView.vue`

**Interfaces:**
- Produces `mergeAdminRow(rows, updated)` and `rowMatchesAdminFilters(row, filters, keywordFields)` with immutable array results.
- Produces `insertAdminRow(rows, created, pageSize)` and `removeAdminRow(rows, id)` so page adapters can update rows without a list request.
- Pages retain list reloads for search, reset, paging, retry and explicit filter changes; mutation completion uses detail-by-ID or mutation response data.

- [x] **Step 1: Write failing utility tests** for merge-by-ID, preserving untouched row data, filters, row removal, insertion and count deltas.
- [x] **Step 2: Run `node --test src/utils/adminRowRefresh.test.mjs`** from `nanshan-frontend`; confirm the missing behavior fails.
- [x] **Step 3: Implement the pure row-refresh utility** and add per-page adapters that reload just the affected record, update/remove the row, and adjust pagination/counts.
- [x] **Step 4: Convert all listed data-management pages** so successful saves and status actions do not call the full list loader.
- [x] **Step 5: Run the focused utility tests and `npm run build`** from `nanshan-frontend`; confirm both pass.
- [x] **Step 6: Commit** as `fix: refresh admin records row by row`.

### Task 2: Account-scoped mini-app page-state cache

**Files:**
- Create: `南山小程序/南山/subpackages/tech-transfer/api/page-state-cache.mjs`
- Test: `南山小程序/南山/tests/page-state-cache.test.mjs`
- Modify: `南山小程序/南山/subpackages/tech-transfer/api/publish-draft.mjs`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/home/home.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/achievement-list/achievement-list.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/search/search.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/patent-list/patent-list.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/my-list/my-list.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/capital-list/capital-list.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/dock-detail/dock-detail.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/achievement-detail/achievement-detail.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/patent-detail/patent-detail.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/post-demand/post-demand.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/post-result/post-result.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/org-manage/org-manage.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/org-join/org-join.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/org-apply/org-apply.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/ai-eval-detail/ai-eval-detail.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/fee-detail/fee-detail.vue`
- Modify: `南山小程序/南山/subpackages/tech-transfer/api/user.js`

**Interfaces:**
- Cache utility exposes `readPageState(key, scope, dataClass, storage, now)`, returning a cached value and fresh/stale marker or `null`; `writePageState(key, scope, dataClass, value, storage, now)` and `invalidatePageState(key, scope, storage)` persist or invalidate entries.
- Existing publication draft functions keep their public API while adding user scope, expiry, and immediate/debounced persistence.

- [x] **Step 1: Write failing tests** for fresh/stale/expired entries, malformed values, namespace separation, invalidation and storage exceptions.
- [x] **Step 2: Run `node --test tests/page-state-cache.test.mjs`** from `南山小程序/南山`; confirm expected failures.
- [x] **Step 3: Implement the shared cache utility** with the spec TTLs, scoped keys and safe storage fallback.
- [x] **Step 4: Restore snapshots before network requests** on the listed browse/detail pages, then revalidate only stale data; preserve filters, pages, search mode and scroll position where present.
- [x] **Step 5: Extend publication drafts** to persist changes with debounce, expire after 24 hours, remain user-scoped and clear after successful publish/logout.
- [x] **Step 6: Add invalidation at successful mutation points** affecting home/list/detail data and account changes.
- [x] **Step 7: Run focused cache tests and the mini-app syntax/build check** used by this repository; confirm no cached auth credentials or binary files.
- [x] **Step 8: Commit** as `feat: preserve miniapp page state with scoped cache`.

### Task 3: Backend AI turn persistence and idempotency

**Files:**
- Create: `tech-transfer-service/migrations/pg/026_ai_chat_turns.sql`
- Modify: `tech-transfer-service/core/request_schemas.py`
- Modify: `tech-transfer-service/modules/ai/chat_store.py`
- Modify: `tech-transfer-service/routes/ai.py`
- Test: `tech-transfer-service/tests/test_ai_chat_history.py`
- Test: `tech-transfer-service/tests/test_ai_modules.py`

**Interfaces:**
- `AiChatRequest` accepts backward-compatible optional `turnId` with bounded length/format.
- Chat store adds `start_turn`, `get_turn`, and atomic `complete_turn`/`fail_turn` operations keyed by `(user_id, turn_id)`.
- `GET /ai/chat/turns/{turnId}` returns only the authenticated user's state/result.

- [x] **Step 1: Add failing API/store tests** for new, running, succeeded, failed, duplicate POST, cross-user access, atomic chat persistence and history clearing.
- [x] **Step 2: Run focused AI tests** and confirm they fail on the missing schema/store/route behavior.
- [x] **Step 3: Add the migration** with a per-user unique turn key, status constraints, timestamps, reply and cards snapshot.
- [x] **Step 4: Implement transactional turn operations** so success and the user/assistant message pair commit atomically, and repeated turn IDs read existing state without model execution.
- [x] **Step 5: Add the authenticated turn-status route** and make chat-history deletion clear both messages and turns.
- [x] **Step 6: Run focused API tests and the relevant backend test suite**; confirm duplicate requests do not invoke AI twice.
- [x] **Step 7: Commit** as `feat: persist idempotent AI chat turns`.

### Task 4: Mini-app AI write-ahead log and turn recovery

**Files:**
- Create: `南山小程序/南山/subpackages/tech-transfer/api/ai-chat-wal.mjs`
- Test: `南山小程序/南山/tests/ai-chat-wal.test.mjs`
- Modify: `南山小程序/南山/subpackages/tech-transfer/api/ai.js`
- Modify: `南山小程序/南山/subpackages/tech-transfer/api/ai-chat-queue.mjs`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/ai-match/ai-match.vue`
- Modify: `南山小程序/南山/tests/ai-chat.test.mjs`

**Interfaces:**
- WAL exposes `beginTurn`, `saveTurnResult`, `loadActiveTurn`, `acknowledgeTurn`, and `clearTurns`, namespaced by authenticated user and turnId.
- `chatWithAgent(message, turnId)` sends the same `turnId`; `getChatTurn(turnId)` queries server state.

- [ ] **Step 1: Write failing WAL tests** for write-before-send state, completion recovery, acknowledgement, account scoping, malformed data and storage failure.
- [ ] **Step 2: Run focused Node tests** and confirm expected failures.
- [ ] **Step 3: Implement the WAL utility** and send queue integration without changing FIFO behavior.
- [ ] **Step 4: Update AI page lifecycle** to restore cached conversation immediately, reconcile active turn by ID, poll running turns, store completed result before rendering, and never resend an unresolved turn automatically.
- [ ] **Step 5: Test navigation/reload recovery paths** including a finished server turn, ongoing turn, failed turn, duplicate request and cleared history.
- [ ] **Step 6: Run focused AI tests and mini-app syntax/build checks**; confirm one user/assistant pair per turn.
- [ ] **Step 7: Commit** as `fix: recover AI chat turns across page switches`.

### Task 5: Integration review and remote push

**Files:**
- Review all files above, migration order, local configuration diffs and current branch state.

- [ ] **Step 1: Run the agreed frontend, mini-app and backend verification commands** after all three implementation commits.
- [ ] **Step 2: Review the full diff** for accidental environment files, stale-cache leaks, migration omissions and unchanged filters/pagination behavior.
- [ ] **Step 3: Push the implementation commits and approved design/plan commits** to `origin/master` in the task's separate batches.
- [ ] **Step 4: Confirm remote branch commit IDs** and report each pushed batch.

---

