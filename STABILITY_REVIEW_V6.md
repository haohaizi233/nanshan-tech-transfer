# 南山科转通 全面 Code Review V6

> 审查日期：2026-10-18 ｜ 审查方式：全量静态代码审查 + 测试套件实际运行 + 运行时进程/配置验证 + V1–V5 修复状态抽验
> 范围：tech-transfer-service、nanshan-ai-agent、南山小程序前端（uni-app）、nanshan-frontend（管理后台）、watchdog/配置/部署、整体架构
> 原则：只读审查，未修改任何业务代码。新问题编号 **G 系列**（V1=H/M/L, V2=N, V3=D, V4=E, V5=F, V6=G）。
> 本轮特点：V5（10-09）之后新增了 WAL 暂存、page-state-cache、AI 聊天容灾、api-origin 端口修复、frp 8077/8076 映射——本轮重点覆盖这些新代码 + V5 未深审的前端与基础设施层。

---

## 一、总体评估

### 总体评分：7.8 / 10

### 各模块评分

| 模块 | 评分 | 一句话评价 |
|------|------|-----------|
| 后端 tech-transfer-service | **8.5** | 分层清晰、SQL 参数化 + 排序白名单、JWT 类型锁定、统一错误契约 + 脱敏、限流 XFF 防护到位；扣分：CRUD 端点无限流、全量 pytest 无法运行、依赖漂移 |
| AI Agent nanshan-ai-agent | **9.0** | thread-local fallback 预算、槽位恰好一次释放、ContextVar 总预算、401 不降级、信号量带超时，9/9 测试通过；扣分：内部 90s 预算与外层 30s 倒挂 |
| 前端 南山小程序/南山 | **8.0** | WAL（脱敏/512KB 上限/版本校验）、page-state-cache（TTL/作用域隔离/敏感键过滤）、AI 三层容灾设计严谨、刷新 token 去重；扣分：6 个测试失败、localStorage 适配器缺口、生产同源守卫被注释 |
| 基础设施（watchdog/配置/日志） | **6.0** | watchdog 功能面完整（noproxy、pgrep -x、3 次容错、外部监控），但**3 个实例并存、脚本版本漂移、开机自启当前未生效、日志无轮转**——本轮最薄弱环节 |
| 整体架构 | **8.0** | 前后端分离合理、主服务/ai-agent/管理后台边界清晰、幂等 turn + WAL + 页面缓存的状态管理设计成熟；扣分：跨层超时倒挂、测试基建拖后腿 |

### 评分趋势

| 轮次 | 评分 | 关键变化 |
|------|------|---------|
| V1 | 5.5/10 | 21 项问题，配置层失守 |
| V2 | 6.5/10 | 配置修复未部署，4 项假修复 |
| V3 | 7.0/10 | 核心稳定性修复落地 |
| V4 | 8.0/10 | 进程守护从无到完整，9 项真正修复 |
| V5 | 8.5/10 | E1–E12 全部真正修复（后端+ai-agent 口径） |
| **V6** | **7.8/10** | 口径扩大（前端+基础设施首次深审）：后端/ai-agent 维持高位且 F1/F2 已修复；新代码（WAL/页面缓存/AI 容灾）质量好但测试脱节；基础设施层暴露出进程管理与日志治理缺口，拉低总分 |

> 注：V5 的 8.5 是「后端 + ai-agent 稳定性」口径；V6 为全项目口径（含前端、基础设施、测试基建），两者不可直接比。

---

## 二、V5 遗留项抽验（F 系列）

| # | 问题 | V6 状态 | 证据 |
|---|------|---------|------|
| F1 | auth_cache 溢出 off-by-one | ✅ 已修复 | `core/auth_cache.py:30` 已改为 `while len(_cache) >= _MAX_ENTRIES`；test_core_units.py **14/14 通过** |
| F2 | ai-agent 测试断言与 E6 不同步 | ✅ 已修复 | nanshan-ai-agent tests **9/9 通过** |
| F3 | test_error_contract 集成测试环境依赖 | ⚠️ 遗留 | 仍需运行中的 local 服务（被本轮 G7 问题放大） |
| D12/R1 | 旧 access_token query 通道 | ⚠️ 遗留 | 仍待前端迁移后移除 |
| R2 | CAPITAL_DB_PASSWORD 线上口令确认 | ⚠️ 遗留 | 无法从代码侧确认，需人工核对 |

---

## 三、本轮新发现问题（G 系列，按严重程度）

### 🟡 中风险（建议尽快修复）

#### G1 🟡 watchdog 同时运行 3 个实例，无单实例守卫
**位置**：`/Users/mac/watchdog.sh:238-246`（`start` 分支无既有实例检查）；运行时 `ps` 观测到 PID 14911/23060/28594 三个 `bash /Users/mac/watchdog.sh start` 并存（18:44/18:47/18:50 各起一个）。
**影响**：三个监控循环同时跑：同刻并发 `start_service`（叠加 G10 端口竞态可双开后端）、日志互相交错、`watchdog.pid` 被互相覆盖导致 `stop` 只能杀掉最后一个、另两个成孤儿永久运行。
**建议**：`start` 分支开头读 `$LOG_DIR/watchdog.pid`，`kill -0` 存活即拒绝启动并提示已运行；`stop` 改为 `pkill -f "watchdog.sh start"` 兜底清理孤儿。

#### G2 🟡 watchdog 脚本版本漂移 + 开机自启当前未生效
**位置**：运行中的是 `/Users/mac/watchdog.sh`（10,091 字节，**不在 git 版本控制内**）；仓库内 `/Users/mac/Desktop/南山小程序/watchdog.sh`（3,890 字节）是旧版；`com.nanshan.watchdog.plist` 指向 Desktop 路径（macOS TCC 对 Desktop 下脚本有限制），且 `launchctl list` 中**没有** com.nanshan.watchdog（仅 com.nanshan.caffeinate）。
**影响**：守护脚本零版本管理、两份漂移副本随时分叉；机器重启后 watchdog 不会自启，全部服务失去守护——与 V5「M6 进程守护 ✅」的结论形成部署落差。
**建议**：把当前生效的 watchdog.sh 收编进仓库（或反向同步），plist 改为指向 `~/watchdog.sh` 并 `launchctl load` 验证 `RunAtLoad`；加载后重启验证一轮。

#### G3 🟡 跨层超时倒挂：ai-agent 内部预算 90s > 后端等待 30s
**位置**：`nanshan-ai-agent/app/config.py:40`（`AI_CHAT_TIMEOUT_SECONDS` 默认 **90**，无 .env 覆盖）→ `tech-transfer-service/routes/ai.py:227`（`urlopen(..., timeout=settings.AI_AGENT_TIMEOUT)`，.env **30**）→ `tech-transfer-service/app.py:278`（MAX_REQUEST_SECONDS=60）→ `南山/.../api/ai.js:23`（前端 70s）。
**影响**：正确排序应为「LLM provider < ai-agent 预算 < 后端等待 < 前端等待」，当前是 90 > 30 倒挂：耗时 30–90s 的合法 AI 请求在 30s 处被后端截断报错（用户仅等了 30s 就收到失败，尽管前端愿意等 70s），而 ai-agent 的工作线程仍在继续烧 LLM 配额直到 90s——纯浪费。V5 的「四层超时对齐 ✅」漏掉了这一层。
**建议**：`AI_CHAT_TIMEOUT_SECONDS=50`（ai-agent 内部预算）、`AI_AGENT_TIMEOUT=55`（后端等待）、MAX_REQUEST_SECONDS=60、前端 70s 保持——单调递增且各层留 5s 余量。

#### G4 🟡 watchdog 捕获日志无轮转，已积累 154MB
**位置**：`/Users/mac/watchdog.sh:49`（`$cmd >> "$LOG_DIR/${name}.log"` 无上限追加）；`/Users/mac/nanshan-logs/` 实测 **154MB** 持续增长。应用内 RotatingFileHandler（20MB×5，`core/exception_handlers.py:107-113`）只覆盖应用自身 logger，管不到 watchdog 重定向的 stdout/stderr/frpc/external 日志。
**影响**：磁盘持续膨胀；`external-api.log` 每 5 分钟追加、frpc 日志量大；无清理机制。
**建议**：启动时对 `*.log` 做大小检查（>20MB 则 `mv xxx.log.1` 截断），或为该目录配置 newsyslog/每日 cron `find -mtime +14 -delete`。

#### G5 🟡 前端 6 个测试失败——测试断言与近期 3 次行为变更脱节
**位置**：`南山/tests/` 实测 **190/196 通过，6 失败**：
- `ai-chat-wal.test.mjs:41`「pending turn 不可被覆盖」——与 fdadc9d 有意变更（beginTurn 允许覆盖 pending turn）冲突，测试未同步更新；
- `api-base.test.mjs:7` / `h5 隧道端口`——期望 8076，实际 8025（fdadc9d 端口修复后断言未更新）；
- `host-bridge.test.mjs:118,128` ×2、`patent-search`（LocalAdapter 路由）——断言写死 `local`/`127.0.0.1:8787`，而当前配置为 staging/公网 43.138.138.200:8025，**测试耦合了部署配置**。
**影响**：前端回归防线失守——失败全被当「已知红」，真回归混入时无法分辨；且「pending turn 不可覆盖」的旧不变量被改掉后，旧 turn 的回复会静默只进历史（用户当前界面看不到），此语义变更无测试保护。
**建议**：逐个更新断言到新契约（覆盖语义补一条「覆盖后旧 turn 结果仍可经 getChatTurn 查到」的测试）；部署相关断言改为读取测试夹具而非真实 config。

#### G10 🟡 watchdog 启动宽限期是死代码，端口竞态可双开服务
**位置**：`check_health` 读 `$LOG_DIR/${name}_start_time` 做 60s 宽限（watchdog.sh:93-101），但 `start_service`（24-51 行）**从不写这个文件**——宽限期从未生效。同时 `start_service` 仅以 `lsof -i :$port` 判活：uvicorn 冷启动 10–30s 内端口未绑定，下一检查周期（10s）判「已挂」→ 再起一个实例。
**影响**：后端/ai-agent 可能被拉起双实例（端口冲突或抢端口），与 G1 三实例叠加放大。
**建议**：`start_service` 启动后 `date +%s > "$LOG_DIR/${name}_start_time"`（与 check_health 对齐）；并以 `$LOG_DIR/${name}.pid` 的 `kill -0` 作为第二判活维度。

### 🟢 低风险

#### G6 🟢 python-pptx 未安装在运行环境（依赖漂移）
**位置**：`requirements.txt:16` 声明 `python-pptx>=1.0.2`，但实际运行/测试所用 `/Users/mac/.pyenv/versions/py313` 环境缺失（`modules/achievement/importer.py:242` 懒加载 `from pptx import Presentation`）。实测 test_content_payload.py **2 处 ModuleNotFoundError**（35/37）。
**影响**：PPTX 导入功能在运行时会抛未处理的 ModuleNotFoundError；测试误报失败。
**建议**：`pip install python-pptx` 补齐运行环境；测试加 `pytest.importorskip("pptx")` 守卫。

#### G7 🟢 pytest 全量无法运行：集成脚本 import 期 SystemExit/网络请求
**位置**：`tech-transfer-service/test_institution_api.py:151`（模块级 `raise SystemExit(1)`，未包 `if __name__`）；另有多份 `test_*.py` 是打运行中服务的集成脚本（import 即发请求、`KeyError: 'data'`）。实测 `pytest --continue-on-collection-errors` 直接 **INTERNALERROR**，只能跑手工挑出的子集。
**影响**：无法一条命令回归；CI 化受阻；D9「sys.exit 包入 __main__」只修了部分文件（遗留不完整修复）。
**建议**：集成脚本移入 `tests/integration/` 或改名 `verify_*.py`，模块级执行统一包 `if __name__ == '__main__':`；pyproject 配 `testpaths` 只指向真单元测试。

#### G8 🟢 api-origin.js 生产同源守卫被注释 + 端口启发式脆弱
**位置**：`南山/config/api-origin.js:43`（`// if (PRODUCTION_ENVS.includes(appEnv)) return ''` 被注释，`appEnv` 成死参数）、`:50-52`（非 localhost 且非 8077 端口一律拼 `:8787`——本机 API 端口）。
**影响**：生产环境 API origin 改由页面端口启发式决定；若 H5 以非 8077/非同源端口对外服务，请求会被导向 `hostname:8787`（错误端口）。该注释是 fdadc9d 为修公网端口解析问题的权宜改动，缺注释说明与测试。
**建议**：恢复按 appEnv 的显式分支（或在注释处写清决策原因 + 覆盖测试）；把端口配对关系收敛为配置表而非 if 链。

#### G9 🟢 localStorage 降级适配器缺 getStorageInfoSync，H5 下前缀失效静默无效
**位置**：`南山/.../api/page-state-cache.mjs:19-32`（适配器只实现 get/set/removeStorageSync）→ `:209`（`clearPageStateScope` 要求 `getStorageInfoSync` 否则直接 return false）；`deletePageStateEntry` 的 `key*` 通配失效同理（`getStorageInfoSync?.()` 为 undefined → 空列表）。
**影响**：H5 下清缓存/登出清态对已写入条目无效（仅 TTL 7 天兜底）；由于 key 带 scope（userId）前缀且读取时校验 scope，**无跨用户泄露**，只影响清理及时性。
**建议**：localStorage 适配器补 `getStorageInfoSync: () => ({ keys: Object.keys(localStorage) })`。

#### G11 🔵 watchdog 尾部死代码 + 外部检查密钥占位
**位置**：`watchdog.sh:292-300`（`check_mysql` 定义在 case 之后，永不执行也不被调用）；`:21`（`x-api-key: ***` 为字面占位符，好于真密钥入库，但检查实际以 401 判健康——`:158` 将 401/403 计为正常）。
**建议**：删除死代码；外部检查如需真实鉴权，密钥放 `.env`/环境变量并注入。

#### G12 🔵 routes/ai.py 调 ai-agent 未绕过系统代理
**位置**：`routes/ai.py:227` 用裸 `urllib.request.urlopen`（走 `http_proxy` 环境变量），而 `modules/ai/provider.py:20` 特意 `build_opener(ProxyHandler({}))` 绕过代理——两处不一致。
**影响**：环境存在 http_proxy/Clash 时，127.0.0.1:8001 的内部调用可能被误代出网（延迟/失败）。
**建议**：routes/ai.py 复用无代理 opener（或统一走 `modules/ai/provider.py` 的传输层）。

#### G13 🔵 CRUD 写端点无限流
**位置**：限流仅覆盖 `routes/auth.py`、`routes/ai.py`、`routes/file.py`、`routes/institution_registration.py`（12 处调用）；achievement/demand/cooperation/admin_ops 等写端点仅靠鉴权。
**影响**：已登录用户可高频刷内容/骚扰接口；影响可控（有鉴权+审计）。
**建议**：对发布/提交类端点补 `check_user_rate` 粗粒度限流（如 60s/20 次）。

---

## 四、分模块审查详情

### 4.1 后端 tech-transfer-service（8.5/10）

| 检查项 | 结论 | 证据 |
|--------|------|------|
| 应用结构/路由 | ✅ 优 | `routes/`（18 个路由模块）→ `modules/`（20 个域）→ `core/`（横切）分层清晰；API 版本化 + Deprecation 头 |
| SQL 注入防护 | ✅ 优 | 全部参数化（`%s` + params）；`ORDER BY` 走 `SORT_WHITELIST`（demand/service.py:462）与白名单常量（membership/service.py:29-37）；动态 WHERE 均为拼结构不拼值 |
| JWT | ✅ 优 | `algorithms=[settings.JWT_ALGORITHM]` 钉死算法（jwt_utils.py:39）防算法混淆；access/refresh `type` 双重校验（middleware.py:111,138 / identity/service.py:467）；refresh 带 jti；过期走 settings |
| API 密钥 | ✅ | 出站密钥（PATENT_PROVIDER_KEY/AI_PROVIDER_KEY）从 .env 读取，日志有 api_key 脱敏（errors.py:198）；文件访问用 HMAC-SHA256 + 5min TTL token |
| 错误处理 | ✅ 优 | 统一错误契约（core/exception_handlers.py 273 行）、上游 body 正则脱敏、health 收敛不暴露内部配置、X-Request-Id 全链路 |
| 限流/安全 | ✅（覆盖面见 G13） | 滑动窗口 + 桶硬上限 20000 + 清扫；XFF 仅信任可信代理且取**最后一跳**（rate_limit.py:92-107）；登录按 IP 前置 + 账号仅失败计数 |
| 连接池 | ✅ | dirty-conn 探活、TCP keepalive、300s recycle、lifespan 启停、minconn=0 降级 |
| 请求超时 | ⚠️ | `asyncio.wait_for(call_next)` 只约束客户端等待，sync 路由的工作线程仍会跑完（已知取舍，G3 关联） |

### 4.2 AI Agent（9.0/10）

| 检查项 | 结论 | 证据 |
|--------|------|------|
| LLM 容错/fallback | ✅ 优 | thread-local fallback deadline（llm_client.py:54）防并发互踩；墙钟预算 `min(2×timeout, timeout+60)`；预算耗尽跳过 fallback；**401 直接抛出不降级**（:168-170，防掩盖配置错误） |
| 并发/资源 | ✅ 优 | BoundedSemaphore(4) 槽位由**发起协程的 finally** 释放（main.py:100-127，H4 修复验证在位）；`acquire(timeout)` 防线程饥饿；executor max_workers 兜底 |
| 超时 | ⚠️ G3 | 单层内部自洽（ContextVar 总预算 + `call_timeout=min(timeout, remaining)`），但 90s 内部预算与后端 30s 等待倒挂 |
| 测试 | ✅ | 9/9 通过（F2 已修复） |

### 4.3 前端 南山小程序/南山（8.0/10）

| 检查项 | 结论 | 证据 |
|--------|------|------|
| WAL 正确性 | ✅ 优 | 写前持久（beginTurn 先落盘再发请求）；512KB 上限；版本+scope+turnId 模式校验；**敏感键/本地文件路径脱敏**（ai-chat-wal.mjs:8-9,52-66）；损坏条目自清 |
| page-state-cache | ✅ 优（G9 除外） | 分级 TTL（list 2min/detail 5min/dict 30min/draft 24h）+ 7 天 stale 保留；scope=userId 隔离 + scope 切换重置；敏感/瞬态键过滤 + `hasSensitiveKey` 写前拒绝；防抖写 + flush + 失效取消 |
| AI 聊天容灾 | ✅ 优 | 三层：WAL pending → `getChatTurn` 轮询服务端幂等 turn → 2 分钟超时强清理；`_requestInFlight`/`_recovering`/`_alive`/scope 四重栅栏防串台；错误分支（chat_history_cleared/断网）分别处理；请求中断后恢复不重发（防重复提问） |
| API 错误处理 | ✅ 优 | 统一 code 契约 + 40102/40104 静默刷新且并发共享同一 refresh promise；dev-only mock bootstrap；request-retry 仅重试传输层错误 |
| 测试 | ⚠️ G5 | 190/196，6 个断言脱节 |

### 4.4 基础设施（6.0/10）

| 检查项 | 结论 | 证据 |
|--------|------|------|
| watchdog 健壮性 | ⚠️ | 功能面完整（启动/停止/状态/重启、3 次失败容错、60s 宽限意图、外部接口监控、`--noproxy "*"`、`pgrep -x frpc`、`set -eo pipefail`），但 G1 三实例、G2 漂移、G10 宽限死代码/端口竞态 |
| 配置管理 | ✅/⚠️ | .env 权限 600 ✅、未入 git ✅、`.env.example` 覆盖全 ✅、`assert_environment()` 拦弱配置 ✅；但运行 watchdog 与仓库 watchdog 配置漂移（G2） |
| 日志监控 | ⚠️ | 应用侧 RotatingFileHandler 20MB×5 ✅；watchdog 侧无轮转 154MB（G4）；无告警体系（仅日志），V5 遗留建议未落地 |

### 4.5 整体架构（8.0/10）

- **前后端分离**：✅ 契约清晰（code/message/requestId + X-Request-Id 追踪链）；小程序/H5/管理后台三端共用版本化 API。
- **微服务划分**：✅ 主服务（业务域 20 个模块）/ ai-agent（LLM 适配 + reranker + 预算）职责单一；127.0.0.1 内网互访，公网仅走 frp 隧道；ai-agent 不直接对公网。
- **数据流与状态管理**：✅ 服务端幂等 turn（turnId）+ 客户端 WAL + 页面状态缓存三层互补，切页/杀进程/断网均有恢复路径；队列 + 防抖写避免竞态。
- **短板**：超时链倒挂（G3）；基础设施（watchdog）横切面无人管理（G1/G2/G4）；测试基建无法全量回归（G5/G7）。

---

## 五、配置审计

| 配置项 | 当前值 | 建议值 | 风险 |
|--------|--------|--------|------|
| AI_CHAT_TIMEOUT_SECONDS（ai-agent） | 90（默认） | 50 | 🟡 G3 倒挂 |
| AI_AGENT_TIMEOUT（后端） | 30 | 55 | 🟡 G3 截断合法慢请求 |
| MAX_REQUEST_SECONDS | 60 | 60（保持） | ✅ |
| 前端 AI_CHAT_TIMEOUT_MS | 70s | 70s（保持） | ✅ |
| .env 权限 / 入库 | 600 / 未入库 | 保持 | ✅ |
| watchdog.sh 归属 | 仓库 3.8KB / 运行 10KB 双份 | 单一入库版本 | 🟡 G2 |
| com.nanshan.watchdog LaunchAgent | plist 在仓库未安装 | 安装并验证 RunAtLoad | 🟡 G2 |
| nanshan-logs 日志轮转 | 无（154MB） | >20MB 滚动或定期清理 | 🟡 G4 |
| TRUSTED_PROXIES | 默认仅回环 | 保持（多机时显式配） | ✅ |
| watchdog external x-api-key | `***` 占位 | 环境变量注入或移除 | 🔵 G11 |

---

## 六、改进建议（按优先级）

**P0（本周）**
1. **G1+G10**：watchdog 增加单实例守卫（start 前 `kill -0` 检查 watchdog.pid）、`start_service` 落盘 `${name}_start_time` 激活宽限期 + 以 pid 文件判活；先杀掉现存的 2 个多余实例。
2. **G2**：watchdog.sh 收编入库、plist 指向 `~/watchdog.sh`、`launchctl load` 并重启验证开机自启真实生效。
3. **G3**：超时链改为 50/55/60/70 单调递增（改 ai-agent .env + 后端 .env 各一行，重启两服务）。

**P1（本月）**
4. **G5**：修复 6 个前端测试断言到新契约（含 beginTurn 覆盖语义补测试），恢复前端回归防线。
5. **G4**：nanshan-logs 日志轮转/清理机制。
6. **G6+G7**：补装 python-pptx + `importorskip` 守卫；集成脚本迁出 pytest 收集范围，让 `pytest` 一条命令可全量回归。

**P2（持续）**
7. **G8**：api-origin.js 生产守卫恢复显式分支 + 补端口配对测试。
8. **G9**：localStorage 适配器补 `getStorageInfoSync`。
9. **G12**：routes/ai.py 统一无代理 opener。
10. **G13**：CRUD 写端点补粗粒度用户限流。
11. 监控告警体系（/health 探针 + LLM 失败率 + 连接池耗尽计数），V5 起持续建议。
12. 前端迁移完成后移除旧 access_token query 通道（D12/R1）；确认 CAPITAL_DB_PASSWORD 已换强口令（R2）。

---

## 七、结论

后端与 ai-agent 经五轮打磨已达到高水位（本轮抽验 F1/F2 修复真实落地，SQL/JWT/限流/错误契约均无新发现高危问题）；10 月新增的 WAL、page-state-cache、AI 容灾代码设计严谨、脱敏与边界处理到位，是本轮亮点。**当前短板集中在基础设施运维面**：watchdog 三实例并存、脚本版本漂移、开机自启未生效、日志无轮转——单个都不致命，但叠加起来意味着「守护体系在下一次重启或故障时大概率不在场」，建议按 P0 顺序一周内收敛。测试面（前端 6 红 + 全量 pytest 不可跑）需要在继续快速迭代前修复，否则回归成本会持续上升。

**本轮新发现：🟡 中风险 6 项（G1-G5、G10）、🟢 低风险 5 项（G6-G9、G13）、🔵 极低 3 项（G11、G12 与遗留确认项）。无 🔴 高风险。**
