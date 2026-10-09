## 任务总结（重要：报告文件未能写出）

⚠️ **未完成项**：因达到工具调用轮次上限，`/Users/mac/Desktop/南山小程序/STABILITY_REVIEW_V2.md` **尚未生成**。完整报告内容已整理在下方，父代理只需将其保存为该文件即可（代码未做任何修改，纯只读审查）。

### 审查方式
- 对比修复提交 `573b6fa`/`1982c98` 的 diff 与实际代码（不只看提交信息声称）
- 运行时验证：用 `.venv-macos` 启动服务（测试端口 8799），实测 `/health`、`/docs`、登录限流、XFF 伪造、`/refresh` 重放；启动 ai-agent、检查线上进程
- 跑测试套件

---

# 南山科转通 服务稳定性 Code Review V2（报告正文）

## 修复验证结果

| # | 问题 | 修复状态 | 验证结果 | 备注 |
|---|------|---------|---------|------|
| H1 | staging+DEBUG=false+phone_password | ✅ 到位（但未部署生效） | `.env`=staging/false/phone_password，assert_environment PASS，/docs 404 | ⚠️ 线上 8787 进程仍报 `appEnv=local,authProvider=mock`（20:08 启动，早于 .env 20:52 修改）；且 start_dev.py `env.setdefault("AUTH_PROVIDER","mock")` 进程环境变量优先级高于 .env，用它启动会**静默还原漏洞** |
| H2 | JWT_SECRET/DB_PASSWORD 强随机 | ✅ 到位 | 运行时验证 JWT 64 字符、DB 48 字符；断言门槛提高到 ≥32/≥12 | CAPITAL_DB_PASSWORD 仍为 6 位弱口令（遗留） |
| H3 | 限流取真实 IP | ⚠️ 部分 | 代码改取 XFF 末跳 ✅；但实测 25 次登录轮换伪造 XFF → **0 次 429**，IP 维度限流可被完全绕过（仅账号维度有效） | 仅在"流量必经 Caddy 追加真实 IP"拓扑下成立，无 trusted-proxy 防护，直连端口即可绕过 |
| H4 | AI Agent 并发槽位释放 | ❌ **未修复** | `main.py` 槽位逻辑与审查时**完全相同**（仅加了 logging/validate），`future.cancel()` + 线程 finally 释放的泄漏模式原样保留 | 提交信息声称修复但无对应代码 |
| M1 | sync 路由超时限制 | ⚠️ 部分 | 代码默认 AI 30s/专利 30s/H5 15s/全局 60s ✅；但 `.env` 覆盖为 AI_AGENT_TIMEOUT=100、专利 45s/PDF 60s，**声称值被部署配置推翻**；且 `asyncio.wait_for` 中间件不终止 sync 线程，最坏 2×100s 线程占用仍在 | 信号量 `_AI_CONCURRENCY` acquire 无超时，慢请求下线程排队堆积 |
| M2 | AI_MAX_CONCURRENT 配置 | ✅ 到位 | Settings 显式声明 + 校验器，运行时生效=4 | |
| M3 | AI_AGENT_URL 统一 | ✅ 到位 | .env/config/run_local.bat/http-client 均 127.0.0.1:8001 一致 | |
| M4 | LLM SSL 验证 | ❌ **未修复** | `llm_client.py:218` 仍 `verify=False`，git 历史无任何改动 | 提交声称修复属虚假；fallback 走 https://api.xiaomimimo.com，MITM 风险实际存在 |
| M5 | /refresh 与上传限流 | ❌ **未修复（死代码）** | `check_ip_rate/check_user_rate/check_user_daily_quota` 已定义但**零调用点**；实测 /refresh 连发 12 次 0×429 可无限重放；上传无日配额；/ai/chat、/ai/match 无用户级频控 | |
| M6 | 进程守护 | ⚠️ 部分/不可靠 | start_services.sh 存在但有硬伤：① `nohup ${cmd}` 不解释 `source ... &&`，venv 分支必然启动失败；② MAX_RESTART_ATTEMPTS/HEALTH_CHECK_INTERVAL 定义了但**无守护循环**，崩溃无人拉起；③ 声称"日志轮转"实为无限 `>>` 追加；④ ai-agent 以 `--host 0.0.0.0` 启动（无鉴权 LLM 端口暴露）；⑤ 预期 venv 路径均不存在 | 非 systemd/supervisor，脚本未经实测 |
| M7 | 限流/幂等内存清理 | ✅ 基本到位 | 惰性修剪+每256次清扫+2万桶硬上限；幂等 TTL 清理+5000 上限 FIFO | 小瑕疵：sweep 只删空桶，闲置旧桶要到硬上限才回收 |
| M8 | 鉴权 DB 查询缓存 | ❌ **未修复（死代码）** | `auth_cache.py` 已建、middleware 引入并写注释，但 `cached()/invalidate_user()` **零调用点**；`_user_is_active` 及 admin/org_admin/backend 身份仍每请求直查 DB | 典型"只建不接"假修复 |
| L1 | 密码脱敏 | ✅ 基本到位 | http-client.env.json 已换占位符 | 旧密码仍留在 git 历史（未清），线上账号是否轮换无法验证 |
| L2 | 幂等 | ✅ 到位 | evaluation-tasks 接入 `idempotent_create`+响应缓存+`Idempotent-Replay` 头 | 仅覆盖一个端点 |
| L3 | 文件 token | ✅ 基本到位 | HMAC-SHA256+5min TTL+compare_digest+file_id 绑定 | 旧 `access_token` query 通道仍保留（标废弃），风险未根除 |
| L4 | 上传限制 | ✅ 到位 | `file.read(max_bytes+1)` 双层校验 | 用户日配额缺失（归入 M5） |
| L5 | 日志 | ⚠️ 部分 | LOG_LEVEL/LOG_DIR 轮转已实现，但 `.env` `LOG_DIR=''` → **线上实际仍纯控制台无落盘**；ai-agent 仍大量 `print()` | |
| L6 | 错误响应脱敏 | ✅ 到位 | `_desensitize_upstream_body` 正则脱敏（URL/凭据/堆栈/连接串/IP）已接入 BizError 处理器 | |
| L7 | API 版本管理 | ✅ 基本到位 | 旧 `/api/file/{id}` 加 Deprecation + Link successor 头 | |
| L8 | 连接池配置 | ✅ 基本到位 | DB_POOL_MAX×workers 校验（超 100 仅 warning） | 仅告警不强制 |
| L9 | CORS | ✅ 到位 | 显式白名单 `https://inanshan.sjhcip.com`，staging 无 regex；运行时验证生效 | |

## 总体评估
- 稳定性评分：**6.5/10**（上轮 5.5）——配置层 H1/H2 真实改善、M2/M3/M7 与多数 L 项落实；但 **4 项声称修复是假的（H4/M4/M5/M8）**，M1 被 .env 推翻，M6 脚本有硬 bug，且**全部修复尚未在运行中的公网进程生效**
- 新发现问题：**10 个**
- 修复不完整/未落实：**9 个**（H3、H4、M1、M4、M5、M6、M8、L5、L3 尾巴）

## 新发现问题
| # | 问题 | 位置 | 影响 | 建议 |
|---|------|------|------|------|
| N1 | **修复未部署**：线上 8787/8001 进程 20:08 启动，早于 .env 修改与修复提交；公网（frpc→127.0.0.1:8787）当前仍 mock 认证+旧代码 | 运行进程 | 公网此刻仍在 H1/H2 漏洞状态下运行 | 立即用修复后配置重启（勿用 start_dev.py），核对 /health 返回 phone_password |
| N2 | start_dev.py `env.setdefault("APP_ENV","local"/"AUTH_PROVIDER","mock"/"HOST_MODE","local")` —— 进程环境变量优先级高于 .env，用它启动会静默覆盖 H1 修复 | start_dev.py:766-768 | 修复被启动器无声还原 | 删除 setdefault 或改为显式报错/staging 值 |
| N3 | 超时中间件 `asyncio.wait_for` 只取消等待，sync 线程继续跑完（AI 最坏 2×100s+退避）；信号量 acquire 无超时会堆积线程 | app.py:273-285; routes/ai.py:210 | 客户端 504 但线程池仍被占，慢请求下全站卡死风险未根除 | AI 转发异步化/隔离线程池；信号量带超时排队 |
| N4 | start_services.sh 把 ai-agent 绑 `0.0.0.0`，无鉴权 LLM 端口可被内/外网直刷 | start_services.sh:139-141 | LLM 成本盗刷 | 绑 127.0.0.1（与 run_local.bat 一致） |
| N5 | fallback LLM 调用沿用完整 timeout（非剩余预算）；主 Provider 401（配置错误）也切 fallback，掩盖配置问题 | llm_client.py:149-157 | 墙钟时间可达 2×；配错密钥持续烧备用额度 | fallback 用 `remaining_seconds()`；401 不触发 fallback |
| N6 | 测试套件无法整体运行：test_achievement_write_api/test_ai_api/test_db_hardening 模块级 `sys.exit()` → pytest INTERNALERROR；ai-agent 一用例顺序依赖失败（fallback 全局状态泄漏） | tests | 回归验证形同虚设 | 用例改 pytest 风格；fallback 状态加 teardown |
| N7 | CAPITAL_DB_PASSWORD 仍 6 位弱口令 | .env | 本地资本库被直连风险 | 换强口令 |
| N8 | 旧测试密码仍存 git 历史 | http-client.env.json 历史 | 凭据泄露面 | 轮换线上同名账号密码，必要时清历史 |
| N9 | .env `MEDIA_ROOT=C:\Users\Administrator\...`（Windows 路径）与当前 macOS/bash 部署形态矛盾 | .env | POSIX 上会创建名为 `C:\...` 的相对目录，媒体文件散落 | 明确部署平台，改 MEDIA_ROOT |
| N10 | /health 暴露 authProvider/appEnv；幂等缓存回放消息与首响应不一致（cosmetic） | app.py:310; routes/ai.py:70-74 | 低 | 可选收敛 |

## 修复不完整的项
| # | 问题 | 原因 | 建议 |
|---|------|------|------|
| H3 | 无 trusted-proxy 判定，直连可伪造 XFF 绕过 IP 限流（实测 0/25 拦截） | 仅取末跳，未验证链路 | Caddy 显式覆盖 XFF 或服务端白名单代理 IP |
| H4 | 声称修复但 main.py 无任何对应改动 | 修复缺失 | 取消/超时立即独立计数释放槽位 |
| M1 | 代码默认 30s 被 `.env` 100s/45s/60s 覆盖；中间件不停线程 | 配置与修复意图冲突 | .env 同步调小；转发异步化 |
| M4 | verify=False 原样保留 | 修复缺失 | `verify=True` |
| M5 | 三个限流函数零调用点，/refresh 实测无限重放 | 只建函数未接线 | /refresh 接 `check_ip_rate`，上传接日配额，/ai/* 接用户频控 |
| M6 | 无守护循环、venv 启动命令 bug、无日志轮转 | 脚本不完整 | systemd `Restart=always` 或补 watchdog 循环+logrotate |
| M8 | auth_cache 零调用点，鉴权仍每请求查库 | 只建缓存未接线 | `_user_is_active`/角色查询接入 `cached()`，写路径 `invalidate_user()` |
| L5 | LOG_DIR 未配置 → 线上无日志落盘；print 未清 | 配置未跟上 | .env 设 LOG_DIR |
| L3 | 旧 access_token query 通道保留 | 兼容未拆 | 前端切换后删除 |

## 稳定性改进建议（按优先级）
1. **立即**：用修复后配置重启两个服务并验证 `/health` 返回 `phone_password`/`staging`（N1）；改掉 start_dev.py 的 env 覆盖（N2）——否则 H1 修复随时被还原。
2. **立即**：补 M4 `verify=True`、M5 三处限流接线、M8 auth_cache 接线——这三项是"声称已修实际没修"，风险敞口与上轮相同。
3. **本周**：H4 槽位释放重构；M1 把 `.env` 超时与代码意图对齐 + AI 转发异步化；M6 换 systemd/supervisor 或修好脚本（含 ai-agent 绑 127.0.0.1）。
4. **本周**：修测试套件（N6）恢复回归能力；设置 LOG_DIR 落盘。
5. **持续**：H3 trusted-proxy、N5 fallback 预算/401 策略、轮换历史密码、统一部署平台叙事（Windows/MAC 混用需澄清）。