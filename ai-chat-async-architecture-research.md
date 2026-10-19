# AI 聊天「发送到后台、前端等回传」架构调研与落地方案

> 目标：解决「AI 生成过程中切换页面，前端永远卡在『人工智能正在生成』」的问题。
> 现状：前端 `POST /ai/chat` 同步发消息 → 后端同步处理 → 前端轮询 `getChatTurn(turnId)` 取结果。
> 技术栈：FastAPI 后端（tech-transfer-service + nanshan-ai-agent）+ uni-app H5 前端。

---

## 0. 结论速览（TL;DR）

- **病根不是「轮询」本身，而是「同步阻塞式 POST + 脆弱的轮询状态机」这个混合体**：
  1. `POST /ai/chat` 让 HTTP 连接挂住最长 60~70s 等结果，切页面时该请求被中断/超时，链路陷入不确定状态；
  2. 轮询循环 `waitForTurnStatus()` 一旦发现 `!this._visible` 就 `return 'paused'`，而**所有调用方只在 `pollResult === 'pending'` 时才 `scheduleTurnRecovery()`**，`'paused'` 不触发任何续跑 → 切走后彻底停摆；
  3. `runAgentChat` 的 `finally` 里又无条件把 `typing=true / recoveringTurn=true` 复位回去 → 永远显示「人工智能正在生成…」。
- **业界标准做法 = 「异步任务(Run) + 状态查询 + 结果订阅」三层解耦**（OpenAI Assistants 的 `Run` 状态机是范本）：
  发送接口**立即返回** `202 + turnId`（fire-and-forget），真实生成由**后台任务**独立完成并落库；前端用「轮询 + （可选）SSE 推送」订阅结果，且轮询循环**永不因页面隐藏而丢弃续跑责任**，只做「暂停/恢复」而非「中断/放弃」。
- **推荐改造（最小改动、最贴合现状）**：保留现有 `ai_chat_turn` 表与轮询，但
  (A) 把 `/ai/chat` 从「同步等结果」改成「受理即返回 202 + 后台跑」；
  (B) 修前端轮询状态机：`paused` 也要登记续跑，`onShow`/`visibilitychange` 统一恢复，去掉 `finally` 里盲目的 `typing=true`；
  (C) 增加 `GET /ai/chat/turns/{id}` 的「未终态心跳/超时判定」由**服务端**给出 `stale`，而不是前端 2 分钟硬清。

---

## 1. 现状诊断（精确定位卡死链路）

### 1.1 端到端链路

```
前端 ai-match.vue runAgentChat(text)
  ├─ beginTurn({turnId, message})            // ①先写 WAL（本地），保证"问题不丢"
  ├─ chatWithAgent(text, turnId)             // ②POST /ai/chat （同步，最长 AI_CHAT_TIMEOUT_MS=70s）
  │      └─ 后端 routes/ai.py ai_chat()
  │            ├─ start_turn() → status='running' 落库
  │            ├─ _forward_to_agent()        // ③urllib 同步转发 nanshan-ai-agent /api/ai/chat
  │            │      └─ agent: run_in_executor + is_disconnected() 轮询（60s 超时）
  │            └─ complete_turn()/fail_turn() // ④终态落库
  ├─ 若 res.status === 'running' → waitForTurnStatus()   // ⑤轮询 GET /ai/chat/turns/{turnId}
  └─ saveTurnResult / presentSavedTurn / finishTurn      // ⑥呈现 + 清 WAL
```

### 1.2 三处致命缺陷

**缺陷 A：同步 POST 挂长连接，切页面即中断（transport 层）**

`chatWithAgent` 用一个最长 70s 的请求等完整回答。切换页面/后台时：
- uni-app H5 底层是 `XMLHttpRequest`，页面卸载/隐藏时请求可能被浏览器取消或超时；
- 后端 `def ai_chat` 是**同步** handler（FastAPI 跑线程池），客户端断开后仍会继续跑，但 `nanshan-ai-agent` 侧 `await http_request.is_disconnected()` 会**主动 `future.cancel()` 并返回 499**（见 `app/main.py:123-125`）——即**用户切走可能直接把生成掐断**。
- 结果：`complete_turn/fail_turn` 可能没被调用，`ai_chat_turn` 永远停在 `running`。

**缺陷 B：轮询 `paused` 分支丢掉续跑责任（状态机层）**

`waitForTurnStatus()`（`ai-match.vue:471-494`）：
```js
while (this._alive && Date.now() < deadline) {
  if (!this._visible) return 'paused'      // ← 切走直接返回 paused
  ...
}
```
而调用方（`733/741/753` 三处）统一写法：
```js
const pollResult = await this.waitForTurnStatus(turnId, text)
if (pollResult === 'pending' && this._alive) this.scheduleTurnRecovery()  // ← 只认 'pending'
```
`'paused' !== 'pending'` → **切走后没有任何定时器再拉起轮询**。

**缺陷 C：`finally` 盲目复位「生成中」（UI 层）**

`runAgentChat` 的 `finally`（`755-763`）：
```js
this._requestInFlight = false
if (this._alive && this.inflightTurnId === turnId) {
  this.typing = true          // ← 无论 paused/pending，一律又显示"生成中"
  this.recoveringTurn = true
}
```
即使已经 `paused`，UI 仍被置回「人工智能正在生成…」，且无人再驱动它结束。

> **卡死 = A（结果没回来/被掐断） + B（没人再轮询） + C（UI 永远显示生成中）三者叠加。**
> 现有 2 分钟硬清（`525/353`）只是把卡住的 turn 删掉并提示"已自动清理"——治标且会**丢答案**。

---

## 2. 业界模式调研

### 2.1 OpenAI / ChatGPT 的消息发送机制

OpenAI 官方 API（Assistants / Responses / Realtime）几乎都是「**任务化 + 订阅/轮询**」，而非「一条 HTTP 挂到底」：

**(a) Assistants API —— `Run` 状态机（最标准的 fire-and-forget + 轮询范式）**
- 创建 Thread → 添加 Message → `POST /threads/{tid}/runs` **立即返回** `Run` 对象（`status: queued`）。
- 后台真正跑模型，`Run.status` 走状态机：
  `queued → in_progress → (completed | failed | expired | cancelled | incomplete | requires_action)`。
- 客户端**二选一取结果**：
  - `GET /threads/{tid}/runs/{rid}` **轮询** status；或
  - `GET /threads/{tid}/runs/{rid}/events`（或 SDK 的 `.stream()`）**SSE 流式订阅**。
- 关键点：**结果的生命周期由服务端 `Run` 承载，与"发消息那条 HTTP 连接"彻底解耦**。切页面、断网、杀进程都不影响 `Run` 继续跑；回来后重新拉 Thread/Run 即可拿到已完成的结果。

**(b) ChatGPT 网页端**
- 发送后是一个**服务端会话任务**；前端用 SSE/WebSocket 流式渲染 token。
- 切走时流式连接断开，但**服务端继续生成**；回到会话时**重新拉取 thread 消息**，已完成的直接展示，未完成/被中断的显示「已停止/继续生成」。
- 不会因为"前端那条连接断了"就把生成标记为失败。

**(c) Realtime API（语音/低延迟）** —— 走 **WebSocket**（双向、长连接），适合持续对话流。

**可借鉴的核心思想**：把「一次问答」建模成服务端的**一等实体（Run/Turn）**，有明确状态机与终态；传输层（HTTP 阻塞 / SSE / WS / 轮询）只是「怎么拿到结果」，与「结果是否生成」无关。

### 2.2 SSE vs WebSocket vs 轮询 —— 对比与选型

| 维度 | 轮询 (Polling) | SSE (Server-Sent Events) | WebSocket |
|---|---|---|---|
| 方向 | 客户端主动拉 | 服务器→客户端 单向推 | 双向 |
| 连接 | 短连接，每次新建 | 一条长连接（HTTP） | 一条长连接（升级协议） |
| 实时性 | 取决于间隔（秒级） | 准实时（毫秒级推送） | 实时 |
| 自动重连 | 需自己实现 | **浏览器内置**（`retry` 字段 + `Last-Event-ID` 续传） | 需自己实现（心跳/重连） |
| 断线恢复 | 天然幂等（按 `turnId` 查状态即可） | 事件带 `id:`，重连自动带 `Last-Event-ID` 断点续 | 需自己做序号/重放 |
| 服务端复杂度 | 低 | 中（StreamingResponse，连接数管理） | 高（连接管理、心跳、鉴权、水平扩容） |
| 穿透代理/CDN | 最好 | 好（但需关闭缓冲） | 一般（易被代理掐） |
| 连接数限制 | 无 | **非 HTTP/2 时每浏览器每域仅 6 条** | 每域若干 |
| 适用 | 低频状态查询、任务进度、**兜底** | **AI 流式输出、任务进度推送** | 双向交互、协同、语音 |

**选型建议（贴合本项目）**：
- **主用「异步任务 + 轮询」**：改动最小，天然幂等，页面切回来按 `turnId` 一查即得——这正是解决卡死的关键。
- **可选叠加 SSE**：用于生成过程中的 **token 流式渲染** 或 **进度推送**，提升体验；但**必须以轮询为兜底**（SSE 断了、浏览器 6 连接限制、后台被回收时靠轮询补状态）。
- **暂不引入 WebSocket**：本场景是「一问一答 + 卡片」，无需双向；WS 复杂度（心跳、重连、鉴权、扩容）远超收益。
- **uni-app H5 注意**：小程序/App 端无原生 `EventSource`，SSE 需条件编译或用 `uni.request` 的 `enableChunked`（小程序）/ `fetch` 流（H5）。**轮询在所有端行为一致，是最稳的跨端兜底。**

### 2.3 后端异步任务 + 状态查询接口设计模式（核心）

标准三段式（业界通用，OpenAI `Run`、Celery task、Job queue 皆同构）：

1. **受理（Accept）**：`POST` 只做「校验 + 建任务 + 落库 `running/queued`」，**立即返回 `202` + `taskId/turnId`**。不做重活。
2. **执行（Execute）**：真正的耗时调用放到**后台**（`BackgroundTasks` / 线程池 / 任务队列 / 独立 worker），完成后把结果与终态写回任务表。
3. **查询（Query）**：`GET /tasks/{id}` 返回 `{status, result?, error?, progress?}`，前端据此渲染。

**幂等**：`turnId` 由客户端生成并**发送前先持久化**（本项目已有 WAL，做得对），重复提交/重复查询都安全——`start_turn` 的 `ON CONFLICT DO NOTHING` 已具备幂等基础。

**状态机（建议收敛为）**：
```
queued ─▶ running ─▶ succeeded
                   └▶ failed
任意非终态 ─超时/看门狗─▶ expired(或 failed)
```
- 终态只有 `succeeded | failed | expired`，前端只认终态。
- **未终态要有「服务端心跳」**：`updated_at` 定期刷新或 `expires_at` 字段；`GET` 时若发现 `running` 但 `updated_at` 超过阈值，由**服务端**回 `status=stale/expired`，别让前端拍脑袋 2 分钟硬清。

### 2.4 页面可见性（visibilitychange / onShow / onHide）优雅暂停/恢复

原则：**暂停轮询 ≠ 放弃任务**。隐藏时降低/暂停网络活动以省电省流量；恢复时立即补一次状态查询。

- **H5**：`document.addEventListener('visibilitychange', ...)`，`document.hidden` 为真→暂停定时器；为假→立即 `poll()` 一次并恢复。
- **uni-app**：用 `onShow`（恢复）/ `onHide`（暂停）/ `onUnload`（销毁）生命周期，**跨端一致**，优于 `visibilitychange`。
- **关键**：暂停时**只 `clearTimeout`，不要 `return 'paused'` 后撒手不管**；恢复时统一入口 `resumePolling()` 立刻查一次并重新排定下一次。
- 顺带：后台标签页 `setTimeout` 会被浏览器节流到 ≥1s 甚至挂起，所以**不能依赖后台定时器持续轮询**——恢复时的"立即补一次查询"必须可靠。

### 2.5 AbortController 在页面卸载时的正确使用

- **用途**：`onUnload`/`beforeunload` 时 `controller.abort()`，取消**已经没有意义的在飞请求**，避免泄漏与竞态。
- **注意（重要）**：
  - AbortController 是 **DOM/fetch** 能力；`uni.request` 不直接吃它（H5 底层是 XHR，用 `requestTask.abort()`）。封装层需暴露 `abort`。
  - **不要**把"取消请求"当成"取消任务"。前端 abort 只影响**这条连接**，后台任务应继续跑（否则就回到"切走=掐断生成"的坑）。
  - `sendBeacon` / `keepalive` 用于卸载时补发"我离开了"的轻量信号，但同样不应中断后台生成。
- **正确姿势**：`onUnload` → `abort()` 前台请求 + 保留 WAL 中 `pending` 的 `turnId`；下次进页面凭 `turnId` 查询终态即可。

### 2.6 业界标准「fire-and-forget + result polling」模式

```
客户端：
  turnId = uuid(); persist(turnId)        // 先落地，防丢
  res = POST /chat  { message, turnId }   // 立刻拿到 202 {turnId, status}
  loop:
    status = GET /chat/turns/{turnId}
    if terminal: render(result); cleanup(); break
    sleep(backoff)                        // 指数退避 + 抖动，隐藏时暂停，显示时恢复

服务端：
  POST /chat:  幂等建 running turn → 丢后台任务 → return 202
  后台任务:    跑模型 → complete_turn / fail_turn （写终态 + 结果）
  GET  /turns/{id}:  读状态 + 结果；running 但 stale 时回 expired
```
**这是「已解决的问题」**——别自己发明传输层，照搬「任务实体 + 状态机 + 订阅/轮询」即可。本项目 WAL + `ai_chat_turn` 已具备 80% 基础，缺的是"受理与执行解耦"和"轮询状态机不丢续跑"。

---

## 3. 推荐架构方案

### 3.1 后端接口设计

#### (1) `POST /ai/chat` —— 受理即返回（改造核心）

```python
# routes/ai.py
from fastapi import BackgroundTasks

@router.post("/ai/chat", status_code=202)
def ai_chat(body: AiChatRequest, background: BackgroundTasks, user: dict = Depends(identity)):
    check_user_rate(user["userId"], "ai_chat", limit=30, window_s=300)
    user_message = (body.as_dict().get("message") or "").strip()
    if not user_message:
        raise bad_request("message 不能为空")
    turn_id = body.as_dict().get("turnId")
    if not turn_id:
        raise bad_request("turnId 不能为空")   # 强制幂等键

    turn, is_new = start_turn(user["userId"], turn_id, user_message)
    # 幂等重放：已终态直接回结果；运行中直接回 202（不重复触发）
    if not is_new:
        if turn["status"] == "succeeded":
            return success({"turnId": turn_id, "status": "succeeded",
                            "message": turn.get("reply") or "", "data": turn.get("cards") or []})
        if turn["status"] == "failed":
            raise BizError(turn.get("errorCode") or "TT_AI_50301",
                           turn.get("errorMessage") or "AI 助手暂时不可用，请稍后重试",
                           turn.get("errorStatus") or 503)
        return JSONResponse(status_code=202,
            content=success({"turnId": turn_id, "status": "running"}, "AI 回答仍在生成中"))

    # ★ 关键：把耗时调用丢到后台，立即返回 202
    background.add_task(_run_chat_turn, user["userId"], turn_id, user_message)
    return JSONResponse(status_code=202,
        content=success({"turnId": turn_id, "status": "running"}, "AI 回答生成中"))
```

```python
# 后台任务：独立跑完整链路，无论前台连接是否还在，都把 turn 写到终态
def _run_chat_turn(user_id: int, turn_id: str, user_message: str) -> None:
    try:
        if not settings.AI_AGENT_URL:
            raise ai_unavailable("AI 助手未配置")
        result = _forward_to_agent(user_message, exclude_user_id=user_id)
        agent_message = (result or {}).get("message") or ""
        data = (result or {}).get("data")
        cards = [c for c in data if isinstance(c, dict)] if isinstance(data, list) else None
        complete_turn(user_id, turn_id, user_message, agent_message, cards=cards)
    except BizError as exc:
        fail_turn(user_id, turn_id, user_message, exc.message, exc.code, exc.http_status)
    except Exception:
        fail_turn(user_id, turn_id, user_message,
                  "AI 助手暂时不可用，请稍后重试", "TT_COMMON_50001", 500)
```

> 说明：FastAPI `BackgroundTasks` 在**同进程**后台跑，前台 HTTP 立即返回。生产可平滑迁移到 **任务队列（Celery/RQ/ARQ）或独立 worker**（与 `evaluation-tasks` 的 `queued→running→succeeded|failed` 现成模式对齐）。
> **重要**：`nanshan-ai-agent` 侧应**移除/放宽 `is_disconnected()` 主动 cancel**（`main.py:123-125`），否则后台任务的上游若被误判断开会自断生成。后台任务里没有"前台连接"概念，不应因 disconnect 取消。

#### (2) `GET /ai/chat/turns/{turn_id}` —— 状态查询（增加服务端超时判定）

```python
@router.get("/ai/chat/turns/{turn_id}")
def ai_chat_turn_detail(turn_id: str, user: dict = Depends(identity)):
    turn = get_chat_turn(user["userId"], turn_id)
    if not turn:
        raise BizError("TT_AI_40401", "AI 问答轮次不存在", 404)
    # ★ 服务端判定 stale：running 超过阈值仍未终态 → 交给看门狗置 expired/failed
    if turn["status"] == "running" and _turn_is_stale(turn):
        turn = fail_turn(user["userId"], turn_id, "", "生成超时，请重新发送",
                         "TT_AI_50401", 504) or turn
    return success(turn)
```

```python
# chat_store.py 建议新增：服务端超时判定（替代前端 2 分钟硬清）
def _turn_is_stale(turn: dict, max_running_seconds: int = 180) -> bool:
    updated = turn.get("updatedAt")
    if not updated:
        return False
    from datetime import datetime, timezone
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    return age > max_running_seconds
```

> 前端那句「pending 超 2 分钟强清并提示已自动清理」可以删掉，改由服务端统一判定，避免误杀慢答案、避免丢答案。

#### (3) 可选：`GET /ai/chat/turns/{turn_id}/events` —— SSE 推送（增强体验，非必需）

```python
from fastapi.responses import StreamingResponse

@router.get("/ai/chat/turns/{turn_id}/events")
def stream_turn(turn_id: str, user: dict = Depends(identity)):
    def gen():
        last = None
        while True:
            turn = get_chat_turn(user["userId"], turn_id)
            if not turn:
                yield "event: error\ndata: {\"message\":\"not found\"}\n\n"; return
            snap = json.dumps({"status": turn["status"], "reply": turn.get("reply"),
                               "cards": turn.get("cards")}, ensure_ascii=False)
            if snap != last:
                yield f"id: {turn.get('updatedAt')}\ndata: {snap}\n\n"   # id: 便于 Last-Event-ID 续传
                last = snap
            if turn["status"] in ("succeeded", "failed", "expired"):
                yield "event: done\ndata: {}\n\n"; return
            time.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```
> SSE 只是「把每次轮询的响应变成推送」，**底层仍是查 `ai_chat_turn`**，所以即使 SSE 不可用，前端退回轮询也完全一致。**必须保留轮询兜底。**

### 3.2 前端状态管理（修复卡死的关键）

**原则**：
1. 发送后立刻拿到 `turnId` 并进入 `pending`；**不要用一条挂 70s 的 POST 等结果**。
2. 轮询循环只「暂停/恢复」，**永不丢续跑责任**：隐藏→暂停定时器；显示→立即补查一次 + 恢复定时器。
3. `typing` 由**唯一状态源**（`ai_chat_turn` 终态 / WAL active turn）驱动，不在 `finally` 里盲置。

**(a) 统一的轮询控制器（替换 `waitForTurnStatus` + `scheduleTurnRecovery`）**

```js
// 集中管理：一个 inflight turn 的生命周期，只负责"查状态 + 触发呈现 + 续跑"
startPollingTurn(turnId, message) {
  this._poll = { turnId, message, timer: null, deadline: Date.now() + INFLIGHT_WAIT_MS }
  this.typing = true
  this.inflightTurnId = turnId
  this.inflightText = message
  this.persistQueue()
  this._tickPoll()                 // 立即查一次
},
_tickPoll() {
  const p = this._poll
  if (!p || !this._alive) return
  if (Date.now() > p.deadline) { this._onTurnTimeout(p.turnId); return }
  if (!this._visible) return        // 隐藏：不排下一次，但保留 this._poll，等 resumePolling 恢复
  getChatTurn(p.turnId).then(turn => {
    if (!this._alive || !this._poll || this._poll.turnId !== p.turnId) return
    if (isTerminal(turn.status)) { this._settleTurn(turn); return }
    p.timer = setTimeout(() => this._tickPoll(), INFLIGHT_POLL_MS)   // 未终态 → 续跑
  }).catch(() => {
    if (!this._alive || !this._poll) return
    p.timer = setTimeout(() => this._tickPoll(), INFLIGHT_POLL_MS)   // 出错也继续，别撒手
  })
},
resumePolling() {                    // onShow / visibilitychange(visible) 调用
  const p = this._poll
  if (!p) return
  if (p.timer) { clearTimeout(p.timer); p.timer = null }
  this._tickPoll()                   // 立即补查一次
},
pausePolling() {                     // onHide / visibilitychange(hidden) 调用
  const p = this._poll
  if (p && p.timer) { clearTimeout(p.timer); p.timer = null }
  // 注意：不删 this._poll，恢复时继续
},
_settleTurn(turn) {
  this.saveServerTurn(turn).then(() => {
    this._poll = null
    this.finishTurn()               // typing=false, 清 WAL, pumpQueue
    this.loadHistory()              // 从服务端回放，切回来也能对齐
  })
}
```

**(b) 生命周期接线（uni-app 跨端）**

```js
onShow() {
  this._visible = true
  // 有在飞 turn 就恢复轮询；没有就按 WAL 恢复待办
  if (this._poll) { this.resumePolling(); return }
  const active = loadActiveTurn(uni, this._scope)
  if (active && active.status === 'pending') {
    this.startPollingTurn(active.turnId, active.message)   // 凭 turnId 补查
  }
},
onHide() {
  this._visible = false
  this.pausePolling()          // 只暂停，不放弃
  this.persistQueue()
},
onUnload() {
  this._alive = false
  this.pausePolling()
  // 可选：abort 在飞请求（仅前台请求，不涉及后台任务）
  this.persistQueue()          // WAL 保留 pending turnId，下次进来补查
}
```

> **H5 附加**：`document.addEventListener('visibilitychange', () => document.hidden ? this.pausePolling() : this.resumePolling())`，覆盖"同页面切标签"场景（uni-app 生命周期只管页面栈）。

**(c) 发送即受理（fire-and-forget）**

```js
async runAgentChat(text) {
  const turnId = createTurnId()
  if (!beginTurn({ turnId, message: text }, uni, this._scope)) { /* ... */ return }
  this.ensureLocalUserMessage(text)
  try {
    await chatWithAgent(text, turnId)      // 后端已改 202，几乎立刻返回 {turnId, status}
  } catch (e) {
    // 网络抖动也不算失败：turnId 已持久化，交给轮询补查
  }
  this.startPollingTurn(turnId, text)       // 无论 send 成败，都进入轮询（幂等按 turnId 查）
}
```

> 因为 `chatWithAgent` 后端现在**立即返回**，"切页面时这条长请求被掐断"的问题消失——请求 200ms 内就结束了，之后完全靠 `turnId` 轮询/订阅，天生对页面切换免疫。

### 3.3 AbortController / 请求卸载（针对 uni-app 的实操）

- H5：封装 `apiRequest` 暴露 `{ promise, abort() }`，`onUnload` 调 `abort()` 取消**前台在飞请求**（此时 turnId 已在 WAL，不影响后台任务）。
- 小程序：`const task = uni.request(...); task.abort()`。
- **切记**：abort 的是"连接"，不是"任务"；后台 `_run_chat_turn` 照跑，结果照落库。

---

## 4. 与当前轮询方案的对比

| 方面 | 当前方案 | 推荐方案 |
|---|---|---|
| 发送语义 | 同步 POST 挂 60~70s 等完整结果 | **受理即 202**，后台跑，前端只等 `turnId` |
| 切页面影响 | 长请求被掐/超时，agent 可 `is_disconnected` 取消生成 | 请求毫秒级返回；后台任务**不受前台连接影响**，继续生成 |
| 轮询状态机 | `paused` 分支丢续跑，只有 `pending` 才续 | **暂停/恢复**语义，隐藏只暂停、显示立即补查，永不丢责任 |
| UI「生成中」 | `finally` 盲置 `typing=true`，可能永远卡住 | `typing` 由 `turn` 终态驱动，唯一状态源 |
| 超时判定 | 前端拍脑袋 2 分钟硬清（可能误杀/丢答案） | **服务端 `updated_at` 心跳**判定 stale，回 `expired`，不丢答案 |
| 结果获取 | 仅轮询，且回来后可能不一致 | 轮询为主 +（可选）SSE 推送，均查同一张 `ai_chat_turn` |
| 幂等/可靠性 | WAL 已有，但依赖同步链路写终态 | WAL + `turnId` 幂等 + 后台必写终态，任意时刻可恢复 |
| 用户体验 | 切回常看到"生成中"卡死或"已自动清理" | 切回即显示已完成结果；未完成继续转圈并自动续 |
| 跨端一致性 | 轮询（OK） | 轮询兜底（OK），SSE 仅 H5 增强，条件编译隔离 |

**结论**：保留轮询（跨端最稳），把「同步阻塞 POST」拆成「受理 + 后台执行 + 状态查询」，并把前端轮询状态机从"中断/放弃"改成"暂停/恢复"。改动集中在 `routes/ai.py`（受理与后台任务）、`chat_store.py`（stale 判定）、`ai-match.vue`（轮询控制器 + 生命周期），`ai-chat-wal.mjs` 几乎不动。

---

## 5. 落地步骤（建议顺序，可增量上线）

1. **后端**：`POST /ai/chat` 改 `BackgroundTasks` 受理即返回 202；`_run_chat_turn` 后台写终态；放宽 agent `is_disconnected` cancel。（先让结果不再依赖前台连接）
2. **后端**：`GET /ai/chat/turns/{id}` 增加 stale/expired 判定；删前端 2 分钟硬清。
3. **前端**：引入 `startPollingTurn/resumePolling/pausePolling` 轮询控制器；`onShow/onHide/onUnload` 接线；去掉 `finally` 盲置 `typing`。
4. **（可选）前端 H5**：SSE 订阅 `turns/{id}/events`，失败自动降级轮询。
5. **测试**：覆盖「发送后立刻切页→回来应看到结果」「后台生成中杀进程→重进补查」「后端慢→服务端 expired 提示」三类回归。

## 6. 关键代码文件对照

- 后端路由：`tech-transfer-service/routes/ai.py`（`ai_chat`、`ai_chat_turn_detail`）
- 任务存储：`tech-transfer-service/modules/ai/chat_store.py`（`start_turn/complete_turn/fail_turn/get_turn`）
- Agent：`nanshan-ai-agent/app/main.py`（`ai_chat`、`is_disconnected` cancel 逻辑）
- 前端页面：`南山/subpackages/tech-transfer/pages/ai-match/ai-match.vue`（`runAgentChat/waitForTurnStatus/scheduleTurnRecovery/onShow/onHide/onUnload`）
- 前端 WAL：`南山/subpackages/tech-transfer/api/ai-chat-wal.mjs`
- 前端请求：`南山/subpackages/tech-transfer/api/ai.js`、`client.js`（`apiRequest`）
- 轮询常量：`南山/subpackages/tech-transfer/api/ai-chat-queue.mjs`（`INFLIGHT_POLL_MS=2000, INFLIGHT_WAIT_MS=120000`）
- 现成异步范式参考：`routes/ai.py` 的 `/ai/evaluation-tasks`（`queued→running→succeeded|failed`）
