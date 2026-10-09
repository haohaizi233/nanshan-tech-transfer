# 南山科转通 服务稳定性 Code Review

> 审查日期：2026-10-09 ｜ 范围：tech-transfer-service、nanshan-ai-agent、配置、进程管理、网络/部署
> 重点：服务崩溃、数据丢失、安全漏洞、性能瓶颈。只读审查，未修改任何代码。

## 总体评估
- 稳定性评分：**5.5/10**（代码层工程素养较好：连接池/超时/重试/任务回收/日志轮转大多到位；但**部署与配置层严重失守**——公网服务以 local+DEBUG+mock 配置运行、默认 JWT 密钥、无限流绕过，直接把代码层的努力抵消）
- 高风险问题：**4 个**
- 中风险问题：**8 个**
- 低风险问题：**9 个**

亮点（无需修改）：
- `db.py` 连接池实现成熟：TCP keepalive、SELECT 1 预检、坏连接替换、`_CONN_RECYCLE_SECONDS=300` 过期回收、池耗尽等待+条件变量唤醒、`putconn` 异常兜底关闭，映射 503。
- `core/exception_handlers.py` 统一错误契约，敏感细节（SQL/连接串/traceback）只进日志不外发；404 扫描噪音过滤。
- `modules/ai/worker.py` 有 `reap_stuck()` 卡任务回收、`FOR UPDATE SKIP LOCKED` 认领、fail_reason 脱敏。
- `nanshan-ai-agent` LLM 调用有重试+退避+fallback Provider、运行时预算（runtime_budget）、日志落盘队列（512 上限，满则丢弃）+ 20MB×3 轮转 + 14 天清理。
- `.env` 文件权限 700 且未提交 git（仅 `.env.example` 入库）。

---

## 高风险问题（必须修复）

| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| H1 | **公网服务以 `APP_ENV=local` + `DEBUG=true` + `AUTH_PROVIDER=mock` 运行**，生产保护断言（`assert_environment`）被完全绕过 | `tech-transfer-service/.env`；`config.py:288-317`；`modules/identity/provider.py:29-56`；`app.py:52,336` | ① `MockIdentityProvider` 接受任意以 `local-dev-ticket-` 开头的票据即放行身份（外部攻击者可随意伪造任意 user）——**认证完全绕过**；② `/docs`、`/openapi.json` 公网暴露接口面；③ `uvicorn reload=True` 热重载跑在公网流量路径，任何文件变动即重启服务（服务随时中断）。公网域名 `inanshan.sjhcip.com` 走 frp+Caddy 打到本服务 | 公网服务必须 `APP_ENV=production`（或 staging）+ `DEBUG=false` + `AUTH_PROVIDER` 切到手机号+密码登录（已实现 `password_login_session`）；`assert_environment` 会自动拦截弱配置，一并解决 H2 |
| H2 | **JWT_SECRET 为仓库公开的开发默认密钥**（`tech-transfer-dev-secret-key`），且 DB_PASSWORD 大概率为弱默认（`postgres123`） | `tech-transfer-service/.env`（`JWT_SECRET=tech…`）；`config.py:100,82`（默认值即弱密钥，`_WEAK_SECRETS` 拦截仅限 production） | 任何人可从公开代码库拿到密钥，**伪造任意 userId/roles 的 access/refresh token**，包括 admin → 全站账号接管、任意数据读写；DB 弱口令叠加 0.0.0.0 监听有被直连风险 | 生成 ≥16 位随机 `JWT_SECRET`（`openssl rand -hex 32`）；换强 `DB_PASSWORD`；切换 APP_ENV=production 由 `assert_environment` 强制校验 |
| H3 | **登录/注册限流可被 X-Forwarded-For 伪造完全绕过** | `core/rate_limit.py:30-35`（取 XFF **首段**，即客户端自带值）；`deploy/nanshan.caddy`（`reverse_proxy` 未配置 trusted_proxies/覆盖 XFF） | `_client_ip` 信任攻击者可控的 XFF 头，暴力破解防护（账号 5 次/5min）形同虚设；配合 H2 可批量撞库/爆破 | 仅信任反代追加的 XFF **最后一跳**（Caddy 已把真实客户端 IP 追加到尾部），或由 Caddy 显式覆盖 `X-Forwarded-For {remote_host}`；同时对 `/refresh` 补限流 |
| H4 | **ai-agent 超时/取消路径的并发槽位泄漏 → AI 端点整体 503 雪崩** | `nanshan-ai-agent/app/main.py:87-124`（`future.cancel()` 对 ThreadPoolExecutor 中已在运行的线程**无效**，且在线程真正结束前 `_chat_slots` 不释放；若在任务开始前被取消则 `finally` 永不执行，槽位**永久泄漏**）；`llm_client.py:131-158`（单次 chat 最坏 45s×2 重试，失败再走 fallback 又一轮，远超 90s 总预算） | 4 个并发槽位（`AI_CHAT_MAX_CONCURRENCY=4`）被僵占后，后续所有 `/api/ai/chat` 立即 503，直到慢线程自然结束（最坏数分钟）；4 次早期取消可**永久关闭** AI 功能 | ① 取消/超时时立即释放槽位（用独立计数而非依赖线程 finally）；② fallback 调用的 timeout 用 `remaining_seconds()` 余量而非完整 timeout，保证单请求 ≤90s 预算；③ 服务端加请求排队而非直接拒绝 |

## 中风险问题（建议修复）

| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| M1 | sync 路由长时间阻塞 FastAPI 默认线程池（anyio to_thread，约 40 线程）：`/ai/chat` 转发 `urllib` 阻塞 100s×2 次重试+退避 sleep；`/h5` 代理 60s；专利 45-60s | `routes/ai.py:204-234`（`AI_AGENT_TIMEOUT=100`）；`app.py:228`；`config.py:130-131,140` | 突发慢请求可耗尽线程池，殃及全部 sync 端点（含认证/DB 查询），表现为全站卡死 | AI/文件代理改 `httpx.AsyncClient` 异步化，或单独线程池隔离 + 全局排队上限 |
| M2 | `AI_MAX_CONCURRENT` 配置项失效（死旋钮）：`getattr(settings, "AI_MAX_CONCURRENT", 4)`，但 `Settings` 未声明该字段，`extra="ignore"` 使 .env 配置被静默丢弃 | `routes/ai.py:35`；`config.py:54-150` | 运维调参无效，并发控制固定为 4，扩容/收紧都做不到 | 在 `Settings` 显式声明 `AI_MAX_CONCURRENT: int = 4` 并加校验 |
| M3 | `AI_AGENT_URL` 端口/地址漂移且未显式配置：默认硬编码 `http://43.138.138.200:8000/...`，`.env` 无此项；而 ai-agent `run_local.bat` 用 **8001**、README 写 8000 | `config.py:139`；`nanshan-ai-agent/run_local.bat:8`；`tech-transfer-service/.env`（缺键） | 端口不一致时 `/ai/chat`、`/ai/match` 全部 503；配置缺失时生产流量打到固定公网 IP | `.env` 显式写 `AI_AGENT_URL`/`AI_AGENT_TIMEOUT`，统一端口约定，健康检查接入监控 |
| M4 | LLM 调用禁用 TLS 证书校验（`verify=False`） | `nanshan-ai-agent/app/llm_client.py:218` | fallback/主 Provider 若走 https 可被中间人替换模型回包（改写检索参数/结果） | `verify=True`；内网 http 可接受，但 https 上游必须校验证书 |
| M5 | 高危端点缺少防刷/配额：`/refresh` 无限流（可无限重放/枚举）；`/ai/chat`、`/ai/match` 无用户级频控（LLM 成本 DoS，仅 4 并发限制）；文件上传登录后无限量（20MB×N） | `routes/auth.py:82-89`；`routes/ai.py:257,345`；`routes/file.py:51` | 成本耗尽（LLM 调用/磁盘）、refresh token 爆破 | 复用 `core/rate_limit` 给 /refresh、/ai/*（按用户）、上传（按用户日配额）加限 |
| M6 | **无进程守护/自动重启/日志落盘**：公网流量由开发启动器 `start_dev.py` + frpc 单隧道承载，无 systemd/launchd/supervisor；uvicorn 日志只进控制台，无轮转；开发机休眠/网络抖动/进程崩溃 = 公网 502，无人拉起 | `南山小程序/start_dev.py`（仅 spawn+复用逻辑）；仓库内无任何 systemd/launchd/supervisor 配置 | 服务不可用窗口不可控、故障无人知晓、历史日志丢失 | 服务迁到常驻环境（VPS/systemd + `Restart=always`）或加 supervisor+健康探针自动拉起；日志落盘+logrotate；frp 加多路隧道或改 VPS 直跑 |
| M7 | 进程内限流/幂等状态无上限增长 + 多 worker 计数翻倍：`rate_limit._buckets` 仅按 key 惰性修剪（key 本身不删）；`idempotency._store` 同理（TTL 10min、无容量上限）；`UVICORN_WORKERS=2` 下各自独立计数 | `core/rate_limit.py:15-27`；`core/idempotency.py:18-53`；`config.py:106` | 大量 IP/key 时内存缓慢泄漏（长期内存上涨）；实际限流阈值 ×worker 数被放大 | 定期全局清理或换 Redis；为 `_store`/`_buckets` 设容量上限 |
| M8 | 每请求 2-3 次额外 DB 查询 + 每次借用连接先 `SELECT 1` ping，放大连接池压力：`identity()` 每请求查 `app_user.status`；`admin_identity`/`org_admin_identity`/`backend_identity` 再查 1-2 次；「我的」页并发十余查询时 `DB_POOL_MAX=20` 易顶满（acquire 3s 超时 → 503） | `core/middleware.py:28-42,107-208`；`db.py:170-203` | 高并发下池耗尽报 503（`connection pool exhausted`），性能瓶颈 | active 校验合并进业务查询或加 30s 短 TTL 缓存；ping 改为「仅异常后校验」策略；按压测调 `DB_POOL_MAX` |

## 低风险问题（可选修复）

| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| L1 | `http-client.env.json`（已提交 git）含 4 个真实开发账号密码（adminPassword/userPassword/orgAdminPassword/phonePassword） | `http-client.env.json`（git ls-files 可见） | 测试凭据进 git 历史；若与线上账号同密码则横向风险 | 改占位符 + 轮换密码；必要时清理 git 历史 |
| L2 | X-Idempotency-Key 仅打印未实现（`replay protection NOT IMPLEMENTED`），幂等契约缺失 | `routes/ai.py:60-62`；`core/idempotency.py`（仅 cooperation/achievement/demand 用） | 重复提交产生重复评估任务（依赖 is_new 去重兜底） | 接入 `idempotent_create` 或删除误导性日志 |
| L3 | access_token 经 URL query 传递（`GET /files/:id?access_token=`） | `core/middleware.py:69-89`；`routes/file.py` | token 进 Caddy/uvicorn 访问日志、浏览器历史、Referer | 换短时效一次性文件 token |
| L4 | ai-worker 为手动进程，无守护；queued 任务堆积无告警（`reap_stuck` 只回收 running） | `tools/run_ai_worker.py`；`modules/ai/worker.py:54-74` | worker 崩溃后评估任务永久排队，用户轮询无果 | 纳入进程守护 + queued 深度监控告警 |
| L5 | ai-agent 配置无校验：纯 `os.getenv`，`LLM_API_URL/DB_*` 缺失时运行期才报错，fail 模式不清晰 | `nanshan-ai-agent/app/config.py` | 部署漏配 → 启动假成功，首请求才失败 | pydantic-settings + 启动自检（参考主服务 `assert_environment`） |
| L6 | `_LLM_SLOTS.acquire(0.25s)` 过短：路由+重排两段 LLM 调用在 4 并发下易误报 `overloaded` | `llm_client.py:38,112-114` | 稍有并发即走规则兜底/失败，体验抖动 | 等待时间放宽到 2-5s 或按请求预算自适应 |
| L7 | 主服务日志无轮转/落盘（仅控制台）；ai-agent 大量 `print()` 代替 logging | `app.py`/`core/exception_handlers.py:64-80`；`nanshan-ai-agent/app/main.py` 等 | 排障依赖终端缓冲；结构化检索困难 | logging 落盘 + RotatingFileHandler；print → logger |
| L8 | 上游错误正文随错误响应外发（`details.upstreamBody`/`llmBody`，截断 300 字符） | `routes/ai.py:151-155`；`core/exception_handlers.py:135-148` | 可能携带内部 URL/上游堆栈片段给客户端 | 与 worker 的 `_desensitize_reason` 同样处理后再外发 |
| L9 | local 模式 CORS regex 放行任意 IP:5173/8077；`HOST=0.0.0.0` 全接口监听 | `config.py:220-226`；`.env` | 叠加 H1 扩大浏览器侧攻击面 | 公网环境仅显式 `CORS_ORIGINS` 白名单（production 已如此） |

---

## 配置审计

| 配置项 | 当前值 | 建议值 | 风险 |
|--------|--------|--------|------|
| APP_ENV | `local` | `production` | **高**：绕过全部生产保护断言（docs 暴露、mock 登录、弱密钥放行） |
| DEBUG | `true` | `false` | **高**：uvicorn 热重载跑公网，服务随时重启 |
| AUTH_PROVIDER | `mock` | `password`（手机号+密码） | **高**：mock 票据任意伪造身份 |
| JWT_SECRET | 仓库公开默认值 `tech-transfer-dev-secret-key` | `openssl rand -hex 32` 生成 | **高**：token 可任意伪造 |
| DB_PASSWORD | 弱默认（疑 `postgres123`） | 强随机密码 | 高 |
| DB_USER | `mac`（超级用户） | 业务专用最小权限角色 | 中 |
| AI_AGENT_URL | 未配置（默认硬编码 `43.138.138.200:8000`） | .env 显式配置，端口与部署一致（8000/8001 漂移） | 中 |
| AI_MAX_CONCURRENT | 配置无效（Settings 未声明） | 在 Settings 声明并生效 | 中 |
| CORS_ORIGINS | 空（local regex 兜底，放行任意 IP:5173/8077） | 公网域名显式白名单 | 中 |
| AI_DB_USER / AI_DB_PASSWORD（ai-agent） | 未配置，回退主账号 | 只读角色（agent 自己的注释即如此要求） | 中 |
| LLM_*（ai-agent） | 主 Qwen + 备用 mimo 均已配置 | 保持；建议 `verify=True` | 中（verify=False） |
| UVICORN_WORKERS | 2（local 下被 reload 强制 1） | 生产 2-4，注意 DB_POOL_MAX×workers ≤ PG max_connections | 低 |
| DB_POOL_MAX / DB_POOL_ACQUIRE_TIMEOUT | 20 / 3.0s | 压测后调整 | 低 |
| AI_PROVIDER_KEY / PATENT_PROVIDER_KEY / WECOM_SECRET | .env 有值、未入库、权限 700 | 保持，生产换 secrets 管理 | 低 |

---

## 稳定性改进建议（按优先级）

1. **立即**：公网服务切换生产配置（`APP_ENV=production` + `DEBUG=false` + 真实登录 + 随机 `JWT_SECRET`/`DB_PASSWORD`）——一条改动同时关闭 H1、H2 及多项中低风险。
2. **立即**：修复限流的 XFF 信任（H3），改取反代追加的最后一跳真实 IP。
3. **本周**：修 ai-agent 并发槽位泄漏与超时预算（H4）：取消立即释放槽位、fallback 用剩余预算、单请求硬上限 90s。
4. **本周**：进程守护化——服务迁常驻环境（systemd `Restart=always` + 健康探针 + 日志落盘轮转），替换「开发机 + start_dev + frp 单隧道」承载公网的模式（M6）。
5. **迭代内**：`/refresh`、`/ai/*`、上传接口补按用户限流/配额（M5）；`AI_MAX_CONCURRENT` 配置修复（M2）；`AI_AGENT_URL` 显式化（M3）。
6. **迭代内**：AI 转发链路异步化或线程池隔离（M1）；`verify=True`（M4）。
7. **持续**：压测确定 `DB_POOL_MAX`、减少每请求鉴权 DB 往返（M8）；限流/幂等状态换 Redis 或加容量上限（M7）。
8. **监控**：接入 /health、/health/db、queued 任务深度、池耗尽 503 计数、LLM 失败率的告警（现有 `X-Upstream-*` 头与 requestId 链路可直接利用）。
