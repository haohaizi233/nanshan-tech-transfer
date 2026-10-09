# 南山科转通 服务稳定性 Code Review V4

> 审查日期：2026-10-09 ｜ 审查方式：全量静态代码深度分析 + git diff 交叉验证 + 修复链路追踪  
> 范围：tech-transfer-service、nanshan-ai-agent、配置、进程管理、部署、测试  
> 原则：验证前三轮 56 项修复的实际生效情况，发现深层次新问题  
> 只读审查，未修改任何代码。

---

## 前三轮修复验证总结

### 第三轮（2790ca2）新增修复验证

| # | 问题 | 修复状态 | 验证依据 |
|---|------|---------|---------|
| D2 | start_dev.py env覆盖 | ✅ **真正修复** | 766-768行注释"D2: 不再覆盖 APP_ENV/HOST_MODE/AUTH_PROVIDER"，setdefault已删除 |
| D5 | fallback全局deadline竞态 | ✅ **真正修复** | `threading.local()` 替代模块级global，`_fallback_deadline_local.value` |
| D6 | 信号量acquire无超时 | ✅ **真正修复** | `_AI_CONCURRENCY.acquire(timeout=30.0)` |
| D8 | 登录限流计数含成功请求 | ✅ **真正修复** | IP维度认证前检查，账号维度仅在except失败后计数 |
| D14 | 401触发fallback | ✅ **真正修复** | `if primary_err.status_code == 401: raise` 直接抛出 |
| D7 | auth_cache.invalidate_user()零调用 | ✅ **真正修复** | membership/service.py: 550/734/775/813 四处调用 |
| D9 | test sys.exit模块级 | ✅ **真正修复** | 三个test文件均包入`if __name__ == "__main__":` |
| D3 | start_services.sh 0.0.0.0 | ✅ **真正修复** | line 140: `--host 127.0.0.1` |
| D13 | start_services.sh venv命令 | ✅ **真正修复** | `bash -c 'source ... && exec python ...'` |
| D14 | start_services.sh watchdog | ✅ **真正修复** | while true + 健康检查 + 自动重启循环已实现 |

### 第一/二轮遗留修复验证

| # | 问题 | V3状态 | V4状态 | 备注 |
|---|------|--------|--------|------|
| H1 | APP_ENV/staging/phone_password | 配置到位但未部署 | ✅ 代码层面到位 | assert_environment()正确拦截弱配置 |
| H2 | JWT_SECRET/DB_PASSWORD强随机 | ✅ | ✅ | 断言门槛≥32/≥12位 |
| H3 | 限流XFF真实IP | ✅ | ✅ | trusted-proxy + loopback信任 |
| H4 | AI Agent槽位释放 | ✅ | ✅ | caller协程finally统一释放 |
| M2 | AI_MAX_CONCURRENT配置 | ✅ | ✅ | Settings显式声明+validator |
| M3 | AI_AGENT_URL统一 | ✅ | ✅ | 127.0.0.1:8001 |
| M4 | LLM SSL验证 | ✅ | ✅ | verify=settings.LLM_VERIFY_SSL, 默认True |
| M5 | /refresh与上传限流 | ✅ | ✅ | check_ip_rate/check_user_rate/check_user_daily_quota全面接线 |
| M7 | 限流/幂等内存清理 | ✅ | ✅ | 20000桶/5000条目硬上限 |
| M8 | 鉴权缓存 | 读路径接线 | ✅ **读写均到位** | cached()读路径 + invalidate_user()写路径（4处调用） |
| N3 | XFF伪造防护 | ✅ | ✅ | trusted-proxy逻辑正确 |
| N5 | fallback预算限制 | ✅ | ✅ | thread-local deadline + remaining预算传递 |
| L1 | 密码脱敏 | ✅ | ✅ | http-client.env.json换占位符 |
| L2 | 幂等 | ✅ | ✅ | evaluation-tasks接入idempotent_create |
| L3 | 文件token | ✅ | ✅ | HMAC-SHA256 + 5min TTL + compare_digest |
| L4 | 上传限制 | ✅ | ✅ | file.read(max_bytes+1)双层校验 |
| L6 | 错误响应脱敏 | ✅ | ✅ | _desensitize_upstream_body正则脱敏 |
| L8 | 连接池配置 | ✅ | ✅ | DB_POOL_MAX×workers校验 |

### 修复统计

| 类别 | 数量 |
|------|------|
| V3→V4 新验证为真正修复 | **10项**（D2/D3/D5/D6/D7/D8/D9/D13/D14×2） |
| 累计真正修复（V1→V4） | **48项** |
| 仍有遗留 | **8项**（见下方） |
| 本轮新发现 | **12项**（E1-E12） |

---

## 仍有遗留的问题

| # | 问题 | 状态 | 影响 | 建议 |
|---|------|------|------|------|
| R1 | **.env AI_AGENT_TIMEOUT 未在代码仓库中验证**：config.py默认30，.env.example未列出此键。实际.env文件被gitignore，无法确认线上值 | ⚠️ 无法验证 | 若线上.env仍为100则sync线程占用2×100s | 确认线上.env已改为30或删除该键（用代码默认） |
| R2 | **CAPITAL_DB_PASSWORD 仍为弱口令**（123456） | 未修复 | 本地资本库被直连风险 | 换强口令 |
| R3 | **ai-agent 大量print()未转logger**：main.py:148/169/244/260/327/343, router.py:453, reranker.py:186, llm_client.py:490 | 未修复 | 日志不走统一格式，无法按级别过滤 | 全部改为logger.warning/error |
| R4 | **旧access_token query通道保留**：GET /files/:id?access_token=仍可用 | 未修复 | JWT进日志/历史/Referer | 前端迁移后移除 |
| R5 | **MEDIA_ROOT Windows路径**：.env中C:\Users\...与POSIX部署矛盾 | 未修复 | POSIX上路径错乱 | 改为POSIX路径或用默认 |
| R6 | **.env.example暴露内网IP**：PATENT_PROVIDER_BASE=http://43.138.138.200:8081 | 未修复 | 内网架构信息泄露 | 改为占位符 |
| R7 | **JWT/refresh过期硬编码**：refresh_session用SQL `INTERVAL '14 days'`，response返回`expiresIn:7200`硬编码 | 未修复 | 配置修改不传播到运行时 | 使用settings变量 |
| R8 | **health端点暴露appEnv/authProvider** | 未修复 | 低风险信息泄露 | 可选收敛 |

---

## 本轮新发现问题

### E1 🟡 ai-agent 重排器两次LLM调用超时预算溢出

**位置**：`nanshan-ai-agent/app/reranker.py:246-304`  
**问题**：`_call_reranker` 包含两次 LLM 调用（首次 + JSON格式修复重试），每次 timeout=50s。最坏情况下两次调用耗时 100s，但 `AI_CHAT_TIMEOUT_SECONDS=90` 的总预算会被溢出。虽然 `runtime_budget.remaining_seconds()` 会在第二次调用前检查剩余预算，但 `_call_reranker` 内部的第二次 `chat_completion` 调用使用的是固定 timeout=50 而非 remaining budget。  
**影响**：重排请求可能在总预算耗尽后仍等待 50s，导致 ai-agent 线程被占用超预期。  
**建议**：第二次 `chat_completion` 的 timeout 改为 `min(50, remaining_seconds() or 50)`。

### E2 🟡 auth_cache 写路径未覆盖 admin 角色变更

**位置**：`modules/membership/service.py`（invalidate_user 调用点）vs `modules/admin/service.py`（无调用）  
**问题**：`invalidate_user()` 已在 membership 的 approve/revoke 操作中接入（4处），但 admin 模块的以下操作**未接入**：
- 管理员通过 admin_ops 路由禁用/启用用户（当前为只读，但未来扩展时会遗漏）
- admin service 中的机构状态变更（set_institution_status）不涉及用户缓存

当前影响有限（admin路由对users为只读），但若后续扩展用户管理功能（禁用/启用），需同步接入。  
**建议**：在 admin service 的用户管理写操作中预留 `invalidate_user()` 调用。

### E3 🟡 上传文件未校验 Content-Type 白名单

**位置**：`routes/file.py:52-64`  
**问题**：`upload_file` 端点接受任意 `content_type`（来自 `file.content_type`），仅校验文件大小。攻击者可上传可执行文件（.exe/.sh/.html），若浏览器直接访问（Content-Disposition: inline）可能触发 XSS 或 MIME 嗅探攻击。  
**影响**：存储型 XSS 风险（尤其 HTML 文件）。  
**建议**：
1. 校验 content_type 白名单（image/*, application/pdf, application/vnd.openxmlformats-*）
2. 响应头已设 `X-Content-Type-Options: nosniff`（app.py:91），但存储的 HTML 仍可能被同源访问

### E4 🟡 ai-agent 数据库连接无 TCP keepalive

**位置**：`nanshan-ai-agent/app/database.py:25-36`  
**问题**：ai-agent 的连接池创建参数缺少 `keepalives`/`keepalives_idle`/`keepalives_interval`/`keepalives_count`，而主服务 `db.py:63-66` 已配置。长时间空闲连接可能被网络设备/PG重启断开后不被感知。  
**影响**：偶发查询失败（拿到死连接），自动重试可缓解但增加延迟。  
**建议**：添加与主服务一致的 TCP keepalive 参数。

### E5 🔵 前端 AI 超时与后端严重不匹配

**位置**：`南山小程序/南山/subpackages/tech-transfer/api/ai.js:20`  
**问题**：前端注释写 `AI 对话/匹配同步链路最长等待（须 ≥ 后端 AI_AGENT_TIMEOUT 180s + 余量）`，但后端 `config.py:150` 默认 `AI_AGENT_TIMEOUT=30`，`MAX_REQUEST_SECONDS=60`。前端等待 180s 但后端 60s 就返回 504。  
**影响**：用户体验——后端已超时返回 504，前端仍在空等 120s。  
**建议**：前端超时与后端 `MAX_REQUEST_SECONDS` 对齐（建议 65-70s，留余量）。

### E6 🔵 reranker 回退逻辑过于宽泛

**位置**：`nanshan-ai-agent/app/reranker.py:147-149`  
**问题**：`if len(candidates) <= top_n: return candidates[:top_n]` 跳过 LLM 重排。当候选数恰好等于 top_n（如 10 条）时，直接按数据库默认序返回，不经过语义排序。  
**影响**：候选数刚好 10 条时结果未按用户查询语义排序，可能返回不相关结果。  
**建议**：阈值改为 `len(candidates) <= 3`（候选极少时排序价值低）或始终走 LLM。

### E7 🔵 日志落盘配置 .env.example 缺失

**位置**：`config.py:129`（LOG_DIR 默认空）vs `.env.example`（无 LOG_DIR 键）  
**问题**：LOG_DIR 在 config.py 中有定义，.env.example 中未列出，运维部署时容易遗漏，导致日志纯控制台无落盘。  
**影响**：线上日志不持久化，排障困难。  
**建议**：.env.example 中添加 `LOG_DIR=` 及注释说明。

### E8 🔵 .env.example 缺少 AI_AGENT 相关配置

**位置**：`.env.example`  
**问题**：`.env.example` 缺少以下配置键的示例：
- `AI_AGENT_URL`（默认 127.0.0.1:8001）
- `AI_AGENT_TIMEOUT`（默认 30）
- `AI_MAX_CONCURRENT`（默认 4）
- `MAX_REQUEST_SECONDS`（默认 60）
- `LOG_DIR`
- `LOG_LEVEL`

**影响**：运维部署时不清楚有哪些可调参数。  
**建议**：补充完整配置示例。

### E9 🔵 连接池 SELECT 1 预检性能开销

**位置**：`db.py:177-184`（`get_conn` 每次借出前 `_ping`）  
**问题**：每次 `get_conn()` 借出连接前执行 `SELECT 1` 探活，高并发下每请求额外一次 DB 往返。V1 已指出此问题（A3），但未在后续轮次中作为独立修复项。  
**影响**：「我的」页并发十余查询时，每请求多一次 SELECT 1，连接池压力翻倍。  
**建议**：改为「异常后校验」策略——仅在上一次使用报错后探活，正常复用跳过 ping。

### E10 🔵 测试覆盖不完整

**位置**：`tech-transfer-service/test_*.py`  
**问题**：
1. 多数测试为集成测试风格（依赖运行中的服务），非 pytest 原生
2. `test_auth_provider_compat.py` 是唯一真正的 pytest 风格测试
3. ai-agent 的 `tests/test_runtime_hardening.py` 是 unittest 风格，质量较好
4. 无单元测试覆盖核心模块：rate_limit、auth_cache、idempotency、file_token、middleware

**影响**：回归验证能力弱，修改核心模块时缺乏安全网。  
**建议**：为核心模块补充 pytest 单元测试（不需要 DB/网络）。

### E11 🔵 安全响应头缺少 HSTS

**位置**：`app.py:86-96`  
**问题**：安全响应头已设 X-Frame-Options/X-Content-Type-Options/Referrer-Policy/Content-Security-Policy，但缺少 `Strict-Transport-Security`（HSTS）。  
**影响**：首次 HTTP 访问可能被中间人降级为 HTTP。  
**建议**：部署 HTTPS 后添加 `Strict-Transport-Security: max-age=31536000; includeSubDomains`。

### E12 🔵 ai-agent 日志轮转竞态窗口

**位置**：`nanshan-ai-agent/app/llm_log.py:300-321`  
**问题**：`_append_rotating` 使用文件级 `.lock` 做互斥，但 `write_llm_log` 中 jsonl 和 text 两个文件的写入在同一个 `_lock` 块内，如果进程崩溃在两个写入之间，jsonl 和 log 文件记录不一致。  
**影响**：极低——仅影响日志完整性，不影响业务。  
**建议**：可接受，无需修复。

---

## 架构层面评估

### ✅ 显著改善（vs V3）

1. **进程守护**：start_services.sh 从"有 bug 无法工作"升级为完整 watchdog（健康检查 + 自动重启 + 重启计数 + 最大重试）
2. **并发安全**：fallback deadline 改 thread-local 消除竞态；信号量 acquire 加 30s 超时防饥饿
3. **鉴权缓存**：读写双路径完整接线（cached + invalidate_user），30s TTL + 4096 条目上限
4. **登录安全**：IP/账号双维度限流，仅计失败不计成功，防误锁
5. **配置安全**：start_dev.py 不再覆盖安全配置，assert_environment 强制校验

### ⚠️ 仍需关注

1. **sync 线程池饥饿**：信号量 30s 超时 + AI_AGENT_TIMEOUT=30s 已大幅缓解，但 sync 路由仍用 `urllib` 阻塞，4 并发 × 30s = 120s 线程占用仍可能在突发时卡住
2. **监控缺失**：无 /health 定时探针告警、无 LLM 失败率监控、无连接池耗尽 503 计数
3. **多 worker 状态隔离**：rate_limit/idempotency/auth_cache 进程内，UVICORN_WORKERS=2 下各自独立
4. **日志落盘**：代码已支持但 .env 配置未确认

---

## 稳定性评分趋势

| 轮次 | 评分 | 关键变化 |
|------|------|---------|
| V1 | 5.5/10 | 21项问题，配置层严重失守 |
| V2 | 6.5/10 | H1/H2配置修复（未部署），4项假修复 |
| V3 | 7.0/10 | H4/M4/M5/M8真正修复；公网仍未部署 |
| **V4** | **8.0/10** | D2/D3/D5/D6/D7/D8/D9/D13/D14 全部真正修复；进程守护从无到完整；鉴权缓存读写到位；10项新发现均为中低风险 |

**评分依据**：
- ✅ 安全层：认证绕过已封堵（phone_password + assert_environment）、JWT强随机、限流全覆盖、XFF防护、SSL校验
- ✅ 稳定性层：槽位释放、信号量超时、fallback预算、watchdog守护
- ✅ 配置层：start_dev.py不再覆盖安全配置、超时代码默认合理
- ⚠️ 扣分项：sync线程架构未根本改造（-0.5）、监控缺失（-0.5）、测试覆盖不足（-0.5）、ai-agent print未清（-0.3）、.env配置完整性（-0.2）

---

## 改进建议（按优先级）

### 🔴 立即
1. 确认线上 .env 中 `AI_AGENT_TIMEOUT` 值（应为 30 或删除用默认）
2. 前端 AI 超时从 180s 降至 65-70s，与后端 `MAX_REQUEST_SECONDS=60` 对齐

### 🟠 本周
3. ai-agent reranker 第二次 LLM 调用 timeout 改用 remaining budget
4. ai-agent 全量 print() → logger（约 11 处）
5. ai-agent database.py 添加 TCP keepalive 参数
6. .env.example 补充 AI_AGENT/LOG/MAX_REQUEST 配置示例

### 🟡 迭代内
7. 上传文件 Content-Type 白名单校验
8. CAPITAL_DB_PASSWORD 换强口令
9. .env.example 中 PATENT_PROVIDER_BASE 改占位符
10. 为核心模块补充 pytest 单元测试

### 🔵 持续
11. AI 转发改异步（httpx.AsyncClient）彻底消除 sync 线程饥饿
12. 接入健康探针 + Webhook 告警
13. 连接池预检改「异常后校验」策略
14. HSTS 安全头
15. 旧 access_token query 通道移除
16. JWT/refresh 过期改为配置驱动

---

## 附录：修复链路完整性验证

| 修复项 | 代码改动文件 | git commit | 运行时可验证 |
|--------|------------|------------|-------------|
| D2 start_dev.py | 南山小程序/start_dev.py | 2790ca2 | ✅ |
| D5 fallback thread-local | llm_client.py | 2790ca2 | ✅ |
| D6 信号量超时 | routes/ai.py | 2790ca2 | ✅ |
| D7 invalidate_user接线 | modules/membership/service.py | 2790ca2 | ✅ |
| D8 登录限流分离 | routes/auth.py | 2790ca2 | ✅ |
| D9 test sys.exit | test_db_hardening/db_session/error_contract.py | 2790ca2 | ✅ |
| D14 401不触发fallback | llm_client.py | 2790ca2 | ✅ |
| D3 ai-agent绑定127.0.0.1 | start_services.sh | 2790ca2 | ✅ |
| D13 venv启动命令 | start_services.sh | 2790ca2 | ✅ |
| D14 watchdog循环 | start_services.sh | 2790ca2 | ✅ |