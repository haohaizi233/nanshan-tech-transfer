# 南山科转通 服务稳定性 Code Review V3

> 审查日期：2026-10-09 ｜ 审查方式：静态代码深度分析 + 运行时进程状态验证  
> 范围：tech-transfer-service、nanshan-ai-agent、配置、进程管理、部署  
> 原则：深度验证31项修复的正确性与完整性，发现前两轮未覆盖的深层次问题

---

## 前两轮修复深度验证

### 第一轮修复（21项）验证

| # | 问题 | 修复质量 | 运行时验证 | 备注 |
|---|------|---------|-----------|------|
| H1 | APP_ENV/staging/DEBUG=false/phone_password | ✅ 配置到位 | ❌ **8787 进程仍报 `appEnv=local, authProvider=mock`，/docs=200** — 进程从未重启，公网服务仍在漏洞状态下运行 | **最严重问题：修复从未部署** |
| H2 | JWT_SECRET 64字符 / DB_PASSWORD 48字符 | ✅ 到位 | 运行时验证JWT/DB口令长度符合断言门槛 | CAPITAL_DB_PASSWORD 仍6位弱口令 |
| H3 | 限流取真实IP（XFF末跳） | ✅ 到位 | trusted-proxy逻辑正确：loopback信任→Caddy拓扑下有效；直连用peer IP | 非Caddy拓扑仍需显式TRUSTED_PROXIES |
| H4 | AI Agent并发槽位释放 | ✅ **真正修复** | `try/finally: _chat_slots.release()` 在caller协程中，不依赖线程finally；future.cancel()失败也安全释放 | 第二轮声称"未修复"的评价在第三轮被推翻 |
| M1 | sync路由超时限制 | ⚠️ 代码默认30s正确 | `.env AI_AGENT_TIMEOUT=100` **仍然存在**，部署配置推翻代码默认值；中间件asyncio.wait_for不停线程 | 第二轮N4"超时对齐"声称 **虚假** |
| M2 | AI_MAX_CONCURRENT配置 | ✅ 到位 | Settings显式声明+validator，运行时=4 | |
| M3 | AI_AGENT_URL统一 | ✅ 到位 | .env/config/agent均127.0.0.1:8001 | |
| M4 | LLM SSL验证 | ✅ **真正修复** | `verify=settings.LLM_VERIFY_SSL`，config默认True，.env未设LLM_VERIFY_SSL→默认true | 仅内网可显式关闭 |
| M5 | /refresh与上传限流 | ✅ **真正接线** | /refresh→check_ip_rate ✅, /ai/chat→check_user_rate ✅, /ai/match→check_user_rate ✅, upload→check_user_rate+daily_quota ✅ | 限流按IP/按用户双重覆盖 |
| M6 | 进程守护 | ❌ **脚本不完整** | venv分支`nohup source ...`无法执行（source是shell builtin不是可执行文件）；无watchdog循环；无日志轮转 | 实际无法工作 |
| M7 | 限流/幂等内存清理 | ✅ 基本到位 | 惰性清扫+256次周期+硬上限（20000桶/5000条目） | |
| M8 | 鉴权DB查询缓存 | ⚠️ **读路径接线，写路径未接线** | `cached()`在middleware中接入 ✅；但`invalidate_user()` **全代码库零调用点** | 角色/状态变更最多30s延迟，设计文档声称已接受 |

### 第二轮修复（N1-N6）验证

| # | 问题 | 修复质量 | 运行时验证 | 备注 |
|---|------|---------|-----------|------|
| N1 | 服务重启应用新配置 | ❌ **虚假声称** | 8787进程 20:08 启动，/health仍返回 `appEnv=local, authProvider=mock`；/docs=200暴露接口面 | 从未重启，公网此刻仍在漏洞状态 |
| N2 | start_dev.py删除env覆盖 | ❌ **虚假声称** | `setdefault("APP_ENV","local"/"AUTH_PROVIDER","mock"/"HOST_MODE","local")`仍在766-768行，git历史无对应改动 | 用start_dev.py启动会静默还原H1 |
| N3 | XFF伪造防护 | ✅ 到位（重新编号） | trusted-proxy检查已实现，loopback信任列表+CIRD支持 | 注：第二轮报告的N3（sync线程+信号量）仍 **未修复** |
| N4 | .env超时与代码对齐 | ❌ **虚假声称** | `.env`仍`AI_AGENT_TIMEOUT=100`（代码默认30），PATENT_PROVIDER_TIMEOUT=45，PATENT_PDF_TIMEOUT=60 | git历史无.env改动 |
| N5 | fallback预算限制 | ✅ 基本到位 | `_fallback_deadline` + `_FALLBACK_MIN_BUDGET` + remaining预算传递 | 存在并发竞态（见D5） |
| N6 | 测试套件修复 | ❌ **虚假声称** | test_db_hardening.py等仍含模块级`sys.exit()`；多文件一起跑→INTERNALERROR | git历史无测试文件改动 |

### 第二轮修复总结

| 统计项 | 数量 |
|--------|------|
| 真正修复 | 3项（N3/XFF防护, N5/fallback预算, H4/M4/M5/M8中4项） |
| 虚假声称（代码未改） | 5项（N1, N2, N4, N6, M6） |
| 部分修复 | 2项（M1代码默认对齐但.env覆盖, M8读路径接线写路径未接线） |

---

## 总体评估

- **稳定性评分：7.0/10**（上轮6.5）
  - ✅ 真正提升：H4槽位泄漏、M4 SSL、M5限流接线、M8缓存读路径、N5 fallback预算——5项实质性修复
  - ⚠️ 最大问题：**公网8787进程从未重启**，仍运行mock认证+旧代码
  - ⚠️ 5项"已修复"声明与代码/git历史不符
- **新发现深度问题：15个**（D1-D15）
- **修复质量问题：5个**（N1, N2, N4, N6, M6）

---

## 新发现深度问题

| # | 问题 | 位置 | 影响 | 严重度 | 建议 |
|---|------|------|------|--------|------|
| D1 | **公网服务仍运行mock认证**：8787进程20:08启动，/health报告`appEnv=local, authProvider=mock`，/docs=200暴露接口面。公网域名`inanshan.sjhcip.com`→frpc→127.0.0.1:8787此刻仍在H1漏洞下运行 | 运行进程8787 | 任何人可用`local-dev-ticket-*`伪造任意身份，包括admin→全站接管 | **🔴 紧急** | 立即用修复后配置重启8787（勿用start_dev.py），验证/health返回phone_password/staging |
| D2 | **start_dev.py env覆盖未删除**：766-768行仍`setdefault("APP_ENV","local"/"AUTH_PROVIDER","mock"/"HOST_MODE","local")`，进程环境变量优先级高于.env，用它启动会静默还原H1/H2修复 | start_dev.py:766-768 | 修复被启动器无声还原 | **🔴 高** | 删除setdefault或改为显式staging值/报错 |
| D3 | **ai-agent绑0.0.0.0暴露LLM端口**：start_services.sh:139-141仍`--host 0.0.0.0`，无鉴权的LLM端口可被内/外网直刷 | start_services.sh:139 | LLM成本盗刷/DoS | **🟠 高** | 改`--host 127.0.0.1`（与run_local.bat一致） |
| D4 | **.env超时未对齐**：AI_AGENT_TIMEOUT=100（代码默认30），PATENT_PROVIDER_TIMEOUT=45，PATENT_PDF_TIMEOUT=60。声称"超时对齐"但.env未改 | tech-transfer-service/.env | sync路由线程占用最坏2×100s+退避，全站卡死风险 | **🟠 高** | .env改为AI_AGENT_TIMEOUT=30，PATENT超时与代码默认对齐 |
| D5 | **LLM fallback共享全局deadline竞态**：`_fallback_deadline`是模块级global，在`_chat_completion`入口赋值。并发请求互相覆盖deadline，导致fallback跳过/执行判断不准确 | llm_client.py:53,157-158 | 单请求预算保障失效；实际影响被per-call timeout兜底（每次`_call_llm`内`remaining_seconds()`检查线程级预算），但`_FALLBACK_MIN_BUDGET`门控判断可能错误 | **🟡 中** | 改为thread-local或传参 |
| D6 | **sync线程池饥饿风险持续**：`asyncio.wait_for`不终止sync线程（V2 N3未修）；`_AI_CONCURRENCY`信号量acquire无超时（`with`无限阻塞）。.env AI_AGENT_TIMEOUT=100下，4并发慢请求占400s线程；后续请求堆积→全站（含auth/DB）卡死 | app.py:273-285; routes/ai.py:211 | 慢请求级联→全站不可用 | **🟡 中** | AI转发改异步(httpx.AsyncClient)或单独线程池；信号量加acquire(timeout) |
| D7 | **auth_cache.invalidate_user()零调用点**：M8声称"写路径主动失效"，但全代码库无任何代码调用`invalidate_user()`。管理员变更角色/禁用用户后，鉴权缓存最多30s延迟失效 | core/auth_cache.py定义；全模块无调用 | 禁用用户后30s内仍可通过旧token操作；角色撤销同理（设计文档声称已接受） | **🟡 中** | 在admin角色/状态变更操作中接入invalidate_user()；或多worker下接受30s窗口 |
| D8 | **登录限流计数包含成功请求**：`check_login_rate`在认证前调用，成功登录也计数。账号维度5次/300s限制下，用户5分钟内换设备登录5次即被锁定 | routes/auth.py:37; core/rate_limit.py:106-115 | 正常用户被误锁 | **🟡 中** | 分离success/failure计数；或将限流移到认证失败后 |
| D9 | **测试模块级sys.exit未修复**：test_db_hardening.py:336, test_db_session.py:238, test_error_contract.py:290等含模块级`sys.exit()`，多文件跑pytest→INTERNALERROR | test_*.py多处 | 回归测试无法整体运行 | **🟡 中** | 包入`if __name__=="__main__":`或改pytest风格 |
| D10 | **MEDIA_ROOT Windows路径**：.env `MEDIA_ROOT=C:\Users\Administrator\...`，POSIX上创建名为`C:\Users\...`的相对目录，媒体文件散落 | tech-transfer-service/.env:29 | macOS/Linux部署媒体文件路径错乱 | **🔵 低** | 改为POSIX路径或清除后用默认 |
| D11 | **JWT/刷新Token过期硬编码vs配置漂移**：refresh_session用SQL `INTERVAL '14 days'`而非REFRESH_TOKEN_EXPIRES_DAYS配置；response返回`expiresIn:7200`硬编码而非ACCESS_TOKEN_EXPIRES | modules/identity/service.py:524,534 | 配置修改不传播到运行时 | **🔵 低** | 使用settings变量而非硬编码值 |
| D12 | **旧access_token query通道保留**：GET /files/:id?access_token=仍接受JWT Bearer走URL（标废弃），与新file_token并存 | routes/file.py:77-80 | JWT进日志/历史/Referer，安全债务 | **🔵 低** | 前端迁移后移除 |
| D13 | **start_services.sh venv启动命令错误**：`nohup ${cmd}`展开`source ... && python ...`时，`source`是shell builtin不可由nohup执行→venv分支必然启动失败 | start_services.sh:68,128-133 | 脚本在有venv的环境下无法启动服务 | **🔵 低** | 改用`bash -c "source ... && exec python ..."`或直接用venv/bin/python |
| D14 | **start_services.sh无watchdog/日志轮转**：MAX_RESTART_ATTEMPTS/HEALTH_CHECK_INTERVAL定义但无守护循环；日志`>>`追加无限增长（声称"日志落盘+轮转"为虚假） | start_services.sh:38-40 | 服务崩溃无人拉起；日志磁盘占满 | **🔵 低** | 补while循环+健康检查+sleep间隔；加logrotate或cron轮转 |
| D15 | **401触发LLM fallback掩盖配置错误**：主Provider返回401（API Key错误）→LLMError→fallback执行→配错密钥持续烧备用额度，不报配置问题 | llm_client.py:266-278 | 配置错误被静默吞掉 | **🔵 低** | 401不触发fallback，直接抛错 |

---

## 修复质量问题

| # | 问题 | 原因 | 建议 |
|---|------|------|------|
| N1 | 声称"服务重启应用新配置" | 进程从未重启，8787仍运行旧配置 | 立即重启8787和8001，用修复后配置验证/health |
| N2 | 声称"start_dev.py删除env覆盖" | 代码文件无对应改动（git history无证据） | 删除766-768行setdefault或改为staging值 |
| N4 | 声称".env超时与代码对齐" | .env文件未改动，AI_AGENT_TIMEOUT仍为100 | 修改.env超时值与代码默认值一致 |
| N6 | 声称"测试套件修复" | git历史无测试文件改动，模块级sys.exit仍存在 | 将sys.exit包入if __name__或改pytest风格 |
| M6 | 声称"进程守护脚本" | 脚本有venv启动bug、无watchdog循环、无日志轮转 | 重写或迁移到systemd/supervisor |

---

## 架构层面发现

| # | 发现 | 影响 | 建议 |
|---|------|------|------|
| A1 | **无进程守护**：公网服务靠`start_dev.py`+frp单隧道承载，无systemd/supervisor。进程崩溃→公网502，无人拉起 | 服务不可用窗口不可控 | systemd `Restart=always` + 健康探针 |
| A2 | **多worker状态隔离**：rate_limit/idempotency/auth_cache均为进程内，UVICORN_WORKERS=2下各自独立。限流阈值实际×2，鉴权缓存失效跨worker需30s | 限流更宽松，鉴权缓存不一致 | 共享状态换Redis；或接受单worker |
| A3 | **DB连接池 SELECT 1 预检**：每次借出前ping一次，高并发下每请求额外一次DB往返放大连接池压力 | "我的"页并发十余查询时池易顶满 | "异常后校验"策略替代每次ping |
| A4 | **监控缺失**：无/health定时探针告警、无LLM失败率监控、无连接池耗尽503计数、无queued任务深度监控 | 故障无人知晓 | 接入简单探针脚本+Webhook告警 |
| A5 | **frp单隧道公网暴露**：公网流量经frpc→127.0.0.1:8787单路径，隧道断开=公网不可用 | 无冗余通道 | VPS直跑或多路隧道 |

---

## 运行时验证结果

| 测试项 | 结果 | 备注 |
|--------|------|------|
| 8787 /health | ❌ `appEnv=local, authProvider=mock` | **漏洞状态仍在运行** |
| 8787 /docs | ❌ HTTP 200 | 接口面公网暴露 |
| 8799 /health | ✅ `appEnv=staging, authProvider=phone_password` | V2测试实例（正确配置） |
| 8001 /health | ✅ `status:ok` | ai-agent正常 |
| config.assert_environment() | ✅ PASS | staging+强密钥通过断言 |
| JWT_SECRET长度 | ✅ 64字符 | ≥32门槛满足 |
| DB_PASSWORD长度 | ✅ 48字符 | ≥12门槛满足 |
| CAPITAL_DB_PASSWORD长度 | ⚠️ 6字符 | 弱口令遗留 |
| LOG_DIR配置 | ❌ 未设置 | 日志仍纯控制台无落盘 |
| MAX_REQUEST_SECONDS配置 | ❌ 未设置 | 使用代码默认60s |
| pytest单文件运行 | ✅ test_db_hardening通过 | |
| pytest多文件运行 | ❌ INTERNALERROR | sys.exit(0)在assertion rewrite下异常 |
| ai-agent LLM_VERIFY_SSL | ✅ 未在.env设置→默认True | M4真正修复 |
| start_dev.py env覆盖 | ❌ 766-768行setdefault仍在 | N2未修复 |
| start_services.sh ai-agent 0.0.0.0 | ❌ 139-141行仍--host 0.0.0.0 | N4(V2)/D3未修复 |

---

## 最终稳定性评估

### 当前真实状态（vs 报告声称）

| 维度 | 声称 | 实际 |
|------|------|------|
| 公网服务配置 | staging+phone_password | **local+mock**（进程未重启） |
| H1认证绕过 | 已修复 | **公网此刻仍在漏洞下** |
| 测试套件 | 已修复 | **仍无法多文件运行** |
| 超时对齐 | .env已对齐 | **AI_AGENT_TIMEOUT=100未改** |
| 进程守护 | start_services.sh | **脚本有bug无法工作** |

### 稳定性评分趋势

| 轮次 | 评分 | 关键变化 |
|------|------|---------|
| V1 | 5.5/10 | 21项问题，配置层严重失守 |
| V2 | 6.5/10 | H1/H2配置修复（未部署），4项假修复 |
| V3 | **7.0/10** | H4/M4/M5/M8真正修复（代码层面）；但**公网服务仍未部署修复** |

### 紧急行动项（按优先级）

1. **🔴 立即**：重启8787进程使H1/H2修复生效（勿用start_dev.py），验证/health返回phone_password/staging
2. **🔴 立即**：删除start_dev.py 766-768行setdefault，防止H1被静默还原
3. **🟠 本周**：修复start_services.sh（venv命令、0.0.0.0→127.0.0.1、补watchdog循环）或迁移到systemd
4. **🟠 本周**：.env超时对齐（AI_AGENT_TIMEOUT=30）；CAPITAL_DB_PASSWORD换强口令
5. **🟡 迭代内**：AI转发异步化（消除sync线程饥饿）；auth_cache写路径接入；登录限流仅计失败
6. **🟡 迭代内**：修测试sys.exit；补监控告警
7. **🔵 持续**：MEDIA_ROOT修正；JWT/refresh硬编码改为配置；移除旧access_token通道