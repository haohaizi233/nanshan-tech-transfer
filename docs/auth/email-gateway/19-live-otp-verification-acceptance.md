# SendCloud 邮箱及短信验证码真实业务闭环验收

验收基准 `90bfd2da40d465b78148c4365bbed99c336b0ab1`。执行时间 2026-11-26 09:38–09:44（UTC+08:00，新加坡）。

**结论 `DELIVERY_ONLY_VERIFIED`。** 用户已确认此前实际收到邮件和短信。10:45 的 Mac 部署复查确认公网找回通道已启用，数据库直连和 039 门禁均通过。真实 Challenge 核验与业务状态变更均待验收。

## V0 首轮运行环境（09:38–09:44）

| 检查 | 结果 | 证据 |
|---|---|---|
| 公网入口 | PASS | `inanshan.sjhcip.com/`、`/health`、`/h5/`、`/admin/login` 和 `/api/health` 返回 HTTP 200。API 返回 `code=0, database=ok, db=true`，对应后端 `SELECT 1`。探活请求 ID `360b…9a0e`。 |
| 公网找回通道 | BLOCKED | `GET /api/tech-transfer/v1/auth/recovery/capabilities` 返回 HTTP 200、`code=0`，但 `sms=false, emailOtp=false, emailLink=false`。请求 ID `312a…3aa0`。 |
| 本机开发配置的远程 PostgreSQL | BLOCKED | 实际加载的 DB 目标与历史记录一致（`183.36.37.85:19258`）。TCP 可连接，`pg_isready` 无响应，`psql` 在要求 SSL 和禁用 SSL 两种模式下均报告远端关闭连接。使用本机应用实际配置的 psycopg2 探活也在连接阶段失败。需部署侧或数据库侧日志确定关闭连接的一方及原因。 |
| 039 Schema Gate | BLOCKED | 远程 PostgreSQL 握手失败，公网探活只验证基本查询。隔离集成测试通过 039 迁移及门禁检查。 |
| Redis 与 Lua | 本机 PASS，公网 BLOCKED | 本机应用实际配置的只读诊断返回 `connected=true, ping=true, lua=true`。公网 Redis 及 Lua 风控待部署侧核验。 |
| SendCloud Provider | 本机配置 PASS，公网 BLOCKED | 本机 `APP_ENV=local`，`EMAIL_PROVIDER=smtp`、`SMS_PROVIDER=sendcloud`、`EMAIL_ENABLED=true`、`SMS_ENABLED=true`、`REDIS_ENABLED=true`，两条通道的风控均启用，Provider 凭据有配置。公网 Provider、部署 SHA 及实际数据库目标待核验。 |
| 前后端环境一致性 | BLOCKED | 仓库的小程序配置模板引用上述域名，已验证该域名提供前端入口和 API。实际 H5/微信构建产物的请求与数据库实例对应关系待通过页面 Network 和部署日志核对。 |
| 多 Worker OTP HMAC | BLOCKED | 本机独立 OTP HMAC 密钥未配置。公网各 Worker 生效的密钥配置与一致性待从受控部署侧核验。 |

## V1–V5 真实业务证据

| 验收项 | 邮箱 | 短信 |
|---|---|---|
| 真实收到验证码 | PASS（用户确认此前收件） | PASS（用户确认此前收件） |
| Challenge 持久化 | BLOCKED | BLOCKED |
| 正确验证码核验 | BLOCKED | BLOCKED |
| 错误验证码拒绝 | NOT RUN | NOT RUN |
| 过期验证码拒绝 | NOT RUN | NOT RUN |
| 重复使用拒绝 | NOT RUN | NOT RUN |
| Recovery Grant 签发 | BLOCKED | BLOCKED |
| Recovery Grant 消费 | BLOCKED | BLOCKED |
| 联系方式实际确权 | BLOCKED | BLOCKED |
| OTP Step-up 签发及敏感操作消费 | BLOCKED | BLOCKED |
| 新密码登录 | BLOCKED | BLOCKED |
| 旧密码失效 | BLOCKED | BLOCKED |
| 旧会话撤销（Access / Refresh） | BLOCKED | BLOCKED |

真实外发及测试账号写操作待取得本轮授权并确认目标。业务接口的请求 ID、响应状态及数据库最终状态均无本轮记录。待取证的状态包括 `auth_challenge` 的用户、用途、渠道、目标指纹匹配、摘要存在性、TTL、尝试次数、Redis 预占与发送执行权，以及核验后的 Challenge、Grant、联系方式、凭证及会话状态。

## V6 隔离反向测试与并发证据

下表记录基准已有用例中已定位的证据。隔离用例采用测试 Provider 和合成身份。

| 项目 | 本轮隔离证据 |
|---|---|
| V01、V02 | 邮件和短信 PostgreSQL 网关用例覆盖正确码、恢复授权、业务消费。 |
| V03、V09、V11、V12 | 短信网关用例覆盖错码、尝试次数跨事务保留、锁定后拒绝及过期。邮件过期 OTP 的单独用例尚未定位。 |
| V04–V08 | NOT RUN（未逐项核验不存在的 Challenge、跨请求、跨渠道及跨用途的精确用例）。 |
| V10、V16–V18 | 网关、Step-up 上下文和跨事务用例覆盖终态、一次性消费及并发仅一次成功。 |
| V13–V15 | 第一次绑定和 Step-up 用例覆盖账号、会话、目标及缺少必要授权的约束。 |
| V19、V20 | 会话验证的数据库故障与风控 fail-closed 用例已运行。找回 Verify API 核验期间分别中断 PostgreSQL 和 Redis 的精确场景为 NOT RUN。 |
| V21 | 凭证撤销用例在密码恢复事务内注入审计写入失败，验证事务回滚时无缓存失效副作用，并用同一授权重试完成。 |
| V22、V23 | 凭证撤销和网关用例验证隔离环境中的会话撤销和密码写入。实际页面新旧密码与旧令牌回放待真实验收。 |
| V24 | NOT RUN（未独立取证）。 |

## V7 前端

源码及回归覆盖 OTP 前导零、组件内 Challenge 和 Grant、幂等键、找回弹窗和安全中心入口，以及 409、429、503 的客户端错误映射。管理端和小程序回归均通过，管理端、H5 和微信小程序构建成功。实际页面的发送、重发、失效恢复、重复点击、绑定后重登录与浏览器 Network 对照数据库取证均为 BLOCKED。

## V8 投递与核验

投递回执和 SMTP/API 受理状态用于更新投递链路。身份确权取决于 Verify API 所做的 Challenge 约束、HMAC 摘要比较及业务事务提交。隔离 CAS 用例验证重复回执和延迟回执无法恢复终态 Challenge。本轮未添加 Webhook。

## V9 自动化回归

- 隔离栈为本机 PostgreSQL 18.6、Redis 3.0.504（Lua 测试通过），使用独立回环端口。Redis 版本与 CI 镜像的 Redis 7 有差异。邮件并发用例直接注入真实 Redis 风控引擎，测试内隔离全局 Redis 配置。
- 按现有 CI 安全专项命令运行并加跑 SendCloud 专项，97 passed，0 skipped。包含邮件和短信 PostgreSQL 网关、跨事务、Step-up 上下文、首次绑定、凭证撤销、投递 CAS 和 Schema Gate 039。
- `verify_acceptance_evidence.py --scope pg_redis_integration` 通过，核验 132 项清单要求和 137 个 JUnit 节点。
- Ruff 检查和格式检查通过，283 个文件已符合格式。安全核心 mypy 通过，23 个源文件无问题。
- 管理端 53 个、微信小程序/H5 418 个 Node 回归通过。管理端 Vite 构建与 UniApp H5、微信构建成功，UniApp 使用生成的本地开发配置。
- 首轮全量后端因 Windows 子进程默认编码导致 A19 CLI JSON 读取失败。启用 `PYTHONUTF8=1` 后复跑，2501 passed、108 skipped、覆盖率 84.23%（门槛 75%）。全量证据门禁通过，核验 132 项清单要求和 177 个 JUnit 节点。

## V10 结论条件

`OTP_VERIFICATION_VERIFIED` 需要两个真实渠道分别通过由业务接口签发的 Challenge 核验。`BUSINESS_FLOW_VERIFIED` 还需要见证真实授权消费及对应密码、会话、联系方式和敏感操作状态持久化。`CONDITIONALLY_READY` 未授予。下一次真实验证依赖已确认的部署入口、部署侧只读核验权限、通道启用证据和受控账号的本轮外发及写操作授权。验证码及密码由测试操作者在对应业务页面输入。
## Mac 部署复查（2026-11-26 10:45，UTC+08:00）

- H5 `/h5/` 及当前入口 JavaScript、CSS 均返回 HTTP 200。H5 请求 ID `f481…9b2`。实际发送、核验及事务未触发。
- `/health` 和 `/api/health` 均返回 HTTP 200 且 `code=0, database=ok, db=true`。健康检查请求 ID 分别为 `46be…f6a` 与 `70de…649`。
- API 前缀根返回 HTTP 404（应用错误码 `TT_COMMON_40401`）。具体路由 `GET /api/tech-transfer/v1/auth/recovery/capabilities` 返回 HTTP 200、`sms=true, emailOtp=true, emailLink=true`，前端能力接口公布的验证码 TTL 为 300 秒、冷却为 60 秒。公网请求 ID `48ca…9db`。Mac 上 FastAPI `127.0.0.1:8787` 对同一路由返回相同能力。
- Mac 部署检出 SHA 为 `90bfd2da40d465b78148c4365bbed99c336b0ab1`。应用配置指向 Mac 本机 `127.0.0.1:5432/tech_transfer`，该连接和 Windows 端 `192.168.7.11:5432` 的只读直连分别通过 `SELECT 1` 和 039 Schema Gate。未建立数据库 SSH 隧道。
- Mac 当前配置为 `EMAIL_PROVIDER=smtp`、`SMS_PROVIDER=sendcloud`，双通道、Redis 及两套风控均启用，SMTP 主机匹配 SendCloud，两套投递凭据均已配置。应用 Redis 诊断通过 PING 和 Lua。
- Mac 当前加载 `APP_ENV=local`，独立 `SECURITY_OTP_HMAC_SECRET` 未设置。此次检测到一个监听进程，未执行跨 Worker OTP 一致性验收。
- 真实外发、Challenge、核验、授权消费及业务最终状态仍待受控验收。公网开关和数据库连通性的首轮阻塞已解除。

## 真实短信找回请求诊断（2026-11-26 10:54，UTC+08:00）

- 用户从 H5 发起短信找回后，数据库记录任务 `9413346f…`，请求 ID `req_1795…`。执行阶段 `pre_provider`，状态 `ineligible`，内部原因 `privileged_account_restricted`。
- 账号安全手机号已确权，账号持有受限制角色。公开找回接口按防账号枚举策略统一受理，资格规则在发码前终止任务。`provider_called=false`，无关联 Challenge，无 OTP 核验或授权消费。
- 此轮已在公网重新确认 `sms=true` 与 `emailOtp=true`。H5 的「未启用」来自全站占位/能力状态，页面标签本身无法判定该账号是否绑定了安全邮箱。
