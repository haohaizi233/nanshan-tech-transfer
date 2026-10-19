# Code Review — 2026-10-19（微信登录/头像 + AI运行时优化 + 前端修复）

> 评审范围：当日 7 个提交（77f64f1, 1140048, daadc88, 5bdf51e, ca4fded, 7550029, 8ff9661）+ 整体架构
> 评审方式：静态审读 + 实际执行测试（非声明性验证）

## 总分：8.5 / 10

| 模块 | 评分 | 说明 |
|---|---|---|
| 微信登录 + 头像（新增） | 9.0 | 安全设计显著高于平均水平，仅有低危边界问题 |
| AI Agent 运行时优化（新增） | 9.0 | 容错/预算/追踪闭环完整，日志留存需策略 |
| 前端修复 | 8.0 | 修复正确，测试覆盖好；index.html 手改 CSS 偏脆弱 |
| 整体架构 | 8.0 | 分层清晰、服务边界合理；进程内状态是扩展瓶颈 |
| 测试覆盖 | 8.5 | 新增测试质量高；存量套件跨环境不可复现 |

## 实测测试结果（真实执行）

| 套件 | 结果 |
|---|---|
| 前端新测试（wechat-login/avatar-picker/profile-avatar/ai-match/business-page-freshness/page-state-cache，node --test） | **63/63 通过** |
| nanshan-ai-agent 全部测试（pytest） | **24/24 通过**（含 8 subtests） |
| 后端新增 tests/test_wechat_login.py + test_profile_avatar.py | **19/19 通过**（1 项 TestClient 用例因环境缺 httpx2 跳过） |
| 后端全量 tests/ | 1009 通过 / 81 失败 / 108 错误 —— **绝大多数为环境与存量问题，非今日代码引入**（详见问题清单 L3/L4） |

---

## 一、微信登录 + 头像（9.0）

### 做得好的（安全要点全中）
- **不信任客户端身份**：openid 一律服务端 code2session 换取；客户端传入的 phone/openid 从不采信（前端测试有显式断言）。
- **手机号强校验**：getuserphonenumber 回包校验 watermark.appid == 本小程序 + countryCode==86 + `validate_phone` 规范化。
- **防账号合并/接管**：手机号已存在账号时，未登录原账号拒绝绑定（TT_AUTH_40903）；不能绑定他人手机号；已解绑微信（unlinked_at）拒绝登录；密码登录对 `password_configured=false` 的微信新账号关闭。
- **并发安全**：`pg_advisory_xact_lock` 串行化首次登录建号 + IntegrityError → 409 兜底；`change_password` 行级 FOR UPDATE。
- **凭据卫生**：AppSecret 仅在服务端 .env（未入 git，.env.example 为空占位）；`_wechat_json` 5s 超时 + 64KB 读上限 + 统一错误映射不泄内部。
- **限流**：wechat/login 10次/分/IP、bind 5次/分/IP；登录接口 IP 维度 20/分 + 账号维度 5次/5分 仅计失败。
- **头像上传**：`avatarFileId` strict int；`file_object` 归属校验（created_by）+ status='active' + `mime_type LIKE 'image/%'` + FOR SHARE 锁；乐观锁 version 冲突返回 currentVersion；被 user_profile 引用的文件禁止删除（级联保护）。
- **前端**：sessionEpoch 防「登出后迟到的 refresh/login 响应复活会话」竞态（有测试）；静默微信恢复去重（_wechatRestoring 单例）；privacy-gate 正确使用 agreePrivacyAuthorization + openPrivacyContract。

### 问题
- **[LOW] 遗留账号边界**：`wechat.py` 用 LEFT JOIN user_credential 取 phone，legacy 账号 uc.phone 为 NULL 时（user_profile.phone 有值），重新授权手机号会被误判「与账号绑定手机号不一致」拒绝。
- **[LOW-MED] 登录吞吐瓶颈**：`pg_advisory_xact_lock(hashtext("wechat:"+APPID))` 把**所有**微信登录串行化到单事务；高峰期是吞吐瓶颈。可按 openid 分桶加锁或仅在建号路径加锁。
- **[LOW] 错误码粗糙**：`_wechat_json` 把所有 errcode≠0 映射为 401「授权无效」，但 40001（AppSecret 错）等服务端配置错误应为 503，误导排障。
- **[LOW] 封装**：routes/auth.py 直接 import `core.rate_limit` 的私有函数 `_check`/`_client_ip`。
- **[INFO] `_token_cache` 进程内**：多 worker 各自取 stable_token（微信允许，但有额外延迟）；`exchange_phone_code` body 里的 `openid` 非微信 API 契约字段（无害冗余）。

## 二、AI Agent 运行时优化（9.0）

### 做得好的
- **llm_client.py**：仅对 502/503/504/429 退避重试（带抖动）；主/备 Provider 共享墙钟预算（thread-local deadline，修复了并发覆盖 bug）；TLS 校验默认开启；上游回包日志截断 800 字符；BoundedSemaphore(4) 限并发；connect 3s/read 按预算；CoT 剥离 + 多策略 JSON 提取兜底。
- **reranker.py**：提示词强制只排序不造数据；返回 id 必须命中送入候选集合 + 去重（防幻觉注入）；失败静默回退原始顺序（fail-open）；payload 字符预算；重试也受剩余预算约束。
- **runtime_trace.py**：ContextVar trace id；**客户端 X-Request-Id 经正则白名单清洗**（防日志注入）；stage 耗时 + outcome 埋点。
- **main.py 并发**：槽位由 executor done_callback 恰好一次释放（修复此前 cancel 泄漏）；超时仅取消未启动任务；`X-AI-Timeout-Seconds` 只能缩短不能放大（isfinite + 0<t<上限校验）。

### 问题
- **[MED] 日志留存**：`_write_call_log` 持久化完整 input messages + output（含用户问答/联系方式领域内容），需明确 LLM 日志的脱敏与留存期限策略。
- **[LOW] fallback 全局可变状态**：`set_fallback_provider` 全局变量注入，测试多配置切换需小心（现状可接受）。

## 三、前端修复（8.0）

- **local-adapter.js Content-Type 修复**：正确且最小化（POST/PUT 带 body 时补 `application/json`，修复 422）。✅
- **index.html 超宽屏 CSS**：已实测 `<style>` 花括号 7/7 平衡，`@media(min-width:500px)` + `!important` 强制 414px 居中。但手改内联 CSS 花括号偏脆弱，建议后续拆到独立样式文件。**[LOW]**
- **ai-match.vue**：卡片浏览量轮询有 alive/visible/scope 三重守卫 + requestId 防乱序覆盖 + 50 条分批 + 安全整数展示；缓存渐进渲染/滚动恢复均有测试。
- **页面刷新修复链**（home/mine/my-list/dock-detail + page-state-cache 失效）：business-page-freshness.test.mjs 系统性覆盖。✅

## 四、整体架构（8.0）

- **前后端分离**清晰：uni-app 小程序（分包内唯一请求出口 client.js + HostBridge 适配层，平台隔离干净）/ Vue3 管理后台 / FastAPI 后端。
- **服务划分合理**：tech-transfer-service 模块化单体（modules/<域>/service.py，约 12.7k 行，routes→service→db 分层一致）；nanshan-ai-agent 独立进程（约 3.9k 行），LLM 凭据与业务库隔离、超时预算独立——AI 慢路径不拖垮主服务，正确取舍。
- **横切关注点**集中在 core/（errors/middleware/rate_limit/request_schemas），错误码体系（TT_*）统一。
- **[MED] 进程内状态**：限流器、LLM token 缓存、会话计数均为单进程内存实现（代码注释已声明"多 worker 独立计数，宁严勿漏"）。单实例部署可接受，扩容前需换 Redis/共享存储。
- **[LOW] 双服务配置重复**：两套 config.py 各自管理 .env，超时/预算参数需人工对齐。

## 五、测试覆盖（8.5）

- **新增测试质量高**：mock 打在边界（get_cursor/exchange_*），断言的是**安全分支**（未登录不合并账号、解绑拒绝、头像归属、迟到响应不复活会话），而非只测快乐路径。前端 node:test 与后端 pytest 分层清晰。
- **[MED] 套件跨环境不可复现**：全量跑 81 失败 + 108 错误。归因：(1) mac venv 缺 `httpx2`（starlette TestClient 依赖，Windows 开发 venv 有）；(2) 存量 test_coverage_boost.py 62 项与现实现断言不符（如 `dashboard_todos` 返回非 list）；(3) `test_app_routes_count` 路由数 17 vs >20。CI 需锁定依赖 + 在规范环境跑绿基线，否则"全绿"只是本机错觉。
- test_ai_card_view_counts.py / test_ai_forward_budget.py 因同一 TestClient 依赖无法在本环境收集——代码本身未见问题。

---

## 问题清单（按严重度）

| # | 严重度 | 模块 | 问题 |
|---|---|---|---|
| 1 | MED | AI Agent | LLM 调用日志持久化完整 prompt/output，缺脱敏与留存策略 |
| 2 | MED | 架构 | 限流/token 缓存为进程内状态，多 worker/扩容失效 |
| 3 | MED | 测试 | 存量套件 81F+108E 跨环境不可复现（httpx2 依赖 + 陈旧断言），CI 无绿基线 |
| 4 | MED | 微信登录 | advisory lock 按 APPID 全局串行化所有登录，吞吐瓶颈 |
| 5 | LOW | 微信登录 | LEFT JOIN 导致 legacy 账号（uc.phone NULL）重授权被误拒 |
| 6 | LOW | 微信登录 | errcode≠0 一律 401，配置类错误（40001）应 503 |
| 7 | LOW | 后端 | routes/auth.py 引用 rate_limit 私有函数 `_check`/`_client_ip` |
| 8 | LOW | 前端 | index.html 内联手改 CSS 花括号脆弱（已验证平衡） |
| 9 | LOW | 架构 | 双服务 config 重复，超时/预算参数需人工对齐 |
| 10 | INFO | 微信登录 | exchange_phone_code body 多余 openid 字段；token 缓存进程内 |

## 改进建议（按优先级）

1. **P0 — 测试绿基线**：CI 固定依赖清单（补 httpx/httpx2 入 requirements 并锁版本），清理 test_coverage_boost 陈旧断言，建立"全量套件必须绿"门禁。今日新增代码本身全绿，但存量噪声会掩盖回归。
2. **P0 — LLM 日志治理**：`_write_call_log` 对手机号/联系方式字段脱敏或只存 hash，设定留存期（如 30 天）。
3. **P1 — 微信登录锁粒度**：advisory lock 改为按 openid 分桶，或仅在"建号/绑定"路径加锁，纯登录路径用 SELECT ... ON CONFLICT 免锁。
4. **P1 — 限流共享化**：上线多实例前将 core/rate_limit 换 Redis 滑动窗口（接口已按可替换设计）。
5. **P2 — 微信错误码细分**：区分服务端配置错误（503）与用户授权过期（401）。
6. **P2 — legacy 手机号边界**：linked 分支的手机号比对 fallback 到 user_profile.phone。
7. **P3 — 杂项**：导出 rate_limit 公共 API 替代私有 import；index.html 超宽屏样式拆独立文件；双服务超时参数统一到共享配置。

## 结论

今日新增代码（微信登录/头像、AI 运行时优化、前端修复）**质量显著高于一般冲刺产出**：安全设计（不信任客户端身份、防账号合并、上传归属校验、日志注入防护、会话竞态防护）和容错设计（预算化重试/fallback、恰好一次槽位释放、fail-open 重排）均经真实测试验证。主要短板不在新代码，而在**工程基线**：跨环境可复现的测试门禁、LLM 日志留存策略、进程内状态的扩展路径。建议按 P0→P3 落实。
