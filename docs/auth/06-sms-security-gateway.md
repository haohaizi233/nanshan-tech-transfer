# SMS Security Gateway：实现、规则与验收

基线：`b5bfb69`，2026-11-17。沿用现有分支；不部署、不迁移业务库、不发送真实短信。工作期间出现的成果/需求与小程序页面并行修改不属于本任务，不回退这些修改。

## 实际实现与复用

| 文件（仓库相对路径） | 主要职责 / 函数 |
|---|---|
| `tech-transfer-service/modules/security/sms_risk.py` | `SmsRiskEngine.check_request/reserve/transition`，Redis Lua 原子多维请求计数、成本预留和幂等确认/释放 |
| `tech-transfer-service/modules/security/sms_request.py` | `validate_sms_request`、`SmsBodyLimitMiddleware`、可替换 `DeviceRiskAdapter`；JSON/HTTPS/Origin/来源/HMAC/Nonce/设备标识 |
| `tech-transfer-service/modules/security/sms_gateway.py` | `start_sms_recovery/start_sms_binding/_send`，业务核验、挑战状态、审计；持久队列 claim；`reconcile_sms_delivery` |
| `tech-transfer-service/modules/security/provider.py` | 保留 Provider 抽象；`send_task` 返回受理收据；SendCloud 稳定 sendRequestId、签名、有限重试、异常分类、内部状态查询 |
| `tech-transfer-service/modules/security/service.py` | 复用 OTP HMAC、Recovery Grant、绑定及密码重置；修复过期验证、错误次数回滚、用途/目标绑定和消费 |
| `tech-transfer-service/core/rate_limit.py` | 在原 `_client_ip` 增量修正可信代理链及 IPv6 规范化，没有另建 IP 解析器 |
| `tech-transfer-service/core/middleware.py` | session_version 每次实时查库，跨 worker 立即失效；查库错误失败关闭 |
| `tech-transfer-service/routes/auth.py`、`routes/me.py`、`core/request_schemas.py` | 严格安全请求 Schema，复用 Bearer identity；公开恢复持久入队后统一返回 |
| `tech-transfer-service/migrations/pg/034_sms_security_gateway.sql` | 扩展 auth_challenge 发送元数据、account_contact 验证来源；增加内部请求队列，不增加第二套 OTP 表 |
| `tech-transfer-service/config.py`、`.env.example`、`requirements.txt` | 阈值配置及正值/时区校验；Redis、tzdata 依赖 |
| `nanshan-frontend/src/utils/device-instance.js`、`src/api/client.js` | 随机、可删除的设备实例提示 |
| `南山小程序/南山/subpackages/tech-transfer/api/client.js` | 可重置应用实例提示；不采集 MAC，不相信客户端 OpenID |
| `tech-transfer-service/tools/sms_gateway_ops.py` | 队列补偿、过期清理、投递回执核对和双开关真实验收入口 |

复用 `auth_challenge/account_contact/recovery_grant/auth_session/audit_log`；没有改写 JWT 签名、微信登录或机构权限语义。原 `password_recovery` 数据库 purpose 保持兼容，Provider 边界使用 `reset_password`。当前只启用 `reset_password/bind_phone` 短信；其他用途拒绝。

## 实际默认阈值

| 维度 | 阈值 / 窗口 |
|---|---|
| 手机号 + IP/手机号组合冷却 | 60 秒 |
| 手机号发送任务请求 | 3 / 滑动10分钟，5 / 滑动1小时 |
| 手机号发送成本预留 | 10 / 业务自然日 |
| IP 请求与发送 | 10 / 滑动1分钟，60 / 滑动1小时，200 / 自然日 |
| IP 不同手机号 | 10 / 滑动1小时，超限 CHALLENGE |
| 设备请求与发送 | 10 / 滑动1小时，20 / 自然日 |
| 设备不同手机号 | 5 / 滑动10分钟，超限 CHALLENGE |
| 账号请求与发送 | 5 / 滑动1小时，10 / 自然日；实际发送再使用真实 user_id 限制，别名不能绕过 |
| OTP | 六位随机数字、300秒、最多5次错误，成功单次消费 |
| 待确认的发送结果 | 最长 OTP TTL 300秒禁止另建发送任务；原任务内部重试复用 sendRequestId |
| SendCloud 网络重试 | 最多3次；退避；确定业务拒绝不重试 |
| 请求体 | 4096 实际字节，ASGI 层先于 JSON 解析限制 |

默认业务时区 Asia/Shanghai；Redis TIME 确定跨实例时钟，自然日剩余秒数到午夜。滑动窗口 ZSET 成员是随机 UUID，避免相同时间戳并发覆盖。

## Redis Key、TTL 与计数语义

统一前缀 `sms:{gateway}:`，同一 Redis Cluster hash slot；后缀为 HMAC-SHA256，带类型域隔离，密钥使用独立 `SMS_RISK_HMAC_SECRET`，未配置时使用服务端 JWT_SECRET。Key 不含完整号码、IP 或设备值。

- `request:{dimension}:{window}:{digest}`：滑动请求窗口，TTL=window+1秒；即使被拒绝也记录请求频率，ZSET 大小受限。
- `request:{dimension}:day:{date}:{digest}`：自然日请求计数，TTL=距业务午夜秒数。
- `send:{dimension}:{window}:{digest}`：发送任务频率，TTL=window+1秒；明确拒绝仍保留，防止无限失败重试。
- `cooldown:phone:{digest}`、`cooldown:pair:{digest}`：60秒。
- `distinct:ip:phone:{digest}` / `distinct:device:phone:{digest}`：不同目标集合，TTL=3601/601秒。
- `quota:{dimension}:{date}:{digest}`：实际发送成本预留，TTL=距业务午夜秒数。
- `pending_outcome:{digest}`：发送结果未知/处理中锁，300秒；接受/明确拒绝确认时按任务所有权清除。
- `reservation:{digest}`：172800秒；原子 `reserved → accepted/unknown/rejected`，`unknown → accepted/delivered`，`accepted → delivered`。重复同状态无副作用。只有 reserved→rejected 退回当天成本预留；不能从 unknown/accepted 退回配额。
- `sms:req:nonce:{digest}`：SET NX EX，默认601秒，覆盖±300秒签名时间窗，避免未来时间戳在Nonce过期后再次重放。

Redis 不可用时发送失败关闭；没有无限制内存降级。生产启动检查要求 SMS_ENABLED 时明确开启 REDIS_ENABLED。关闭 SMS_RISK_ENGINE_ENABLED 或 SMS_REQUIRE_VERIFIED_CONTACT 也关闭短信放行，不会移除安全控制。

发送申请、服务商接受、明确拒绝、未知结果、最终送达分别保存于 Redis 频率/预留和 `auth_challenge.send_state`、审计事件。accepted 不代表送达或最终账单。已受理但最终投递失败不自动退配额；实际费用以 SendCloud 账单为准。

## 请求与设备安全

公开恢复不要求登录；绑定操作继续使用既有 Bearer identity。没有 Cookie 登录凭证自动附带的绑定入口；Origin 检查防跨站浏览器调用，CORS 保持现有白名单。X-Client-Source 只是元数据，不会赋予可信身份。

可信后端请求必须使用 X-Client-Source=service 和 X-Sms-Client-Id / X-Sms-Timestamp / X-Sms-Nonce / X-Sms-Signature。Canonical 字符串为以下6段，以单个换行拼接，无尾换行：

```
METHOD_UPPERCASE
decoded_absolute_path
sha256(raw_body).hexdigest()
timestamp_decimal
nonce
client_id
```

禁止 query 和百分号编码 path；HMAC-SHA256、恒定时间比较，client_id 必须属于后台 SMS_SERVICE_CLIENTS 映射。密钥只放服务端，绝不使用 SMS_KEY。Nonce 按客户端和nonce做密钥摘要后原子消费。

H5/小程序只提供可撤销随机实例ID；缺失/重置/伪造仍受手机号、账号、IP和成本硬上限控制。DeviceRiskAdapter 可在服务器替换，未来接入微信/原生平台证明必须服务器验证，不能相信前端上传 OpenID。

风控输出 ALLOW/CHALLENGE/THROTTLE/DENY 和 rule_id、risk_score、risk_level。风险分数为规则等级映射，不是统计模型。CHALLENGE 当前失败关闭，不自动降低硬上限；人机验证服务商及验证适配器尚未配置，需在上线前确定接入方式。公共 NAT 只受有限窗口约束，不永久封禁或冻结账号。

## 业务与挑战安全

只有 active、未删除、有效密码凭证、经验证且未撤销的安全手机号可以恢复；不查询 user_profile.phone 赋权，不因手机号相同合并账号。平台/机构管理员不走单短信恢复，需人工或额外可信因素。真实绑定冲突会拒绝。

033迁移曾自动把 user_credential.phone 回填为 verified。034增加 verification_method，既有行默认 legacy_unknown，不具备短信恢复资格。必须重新验证，或基于已有确权证据经审计标记 sms/wechat/manual，禁止为了通过测试批量标记。

公开响应：固定 channel/sent/message/maskedDestination 字段和随机 challengeId，未知账号也返回同样结构。账号查询与Provider发送在响应后执行，无公开发送状态查询接口。请求限流的429反映调用压力，不表示账号存在。合法/不存在目标均先持久化同样的内部请求记录。

挑战状态：pending_send → pending（服务商受理或结果未知）→ verified → consumed；以及 failed/expired/locked/cancelled。重发创建新挑战并取消旧待完成挑战。HMAC绑定 challenge/purpose/destination/code；绑定时再核对目标摘要，恢复时再核查当前可信联系方式/业务状态；错误次数在提交后再报告错误，避免异常回滚；行锁保证一次核验签发一个 Grant。

重置事务原子消费 Grant、写密码哈希、消费挑战、递增 session_version、撤销 auth_session。Access Token 每请求实时检查版本，Refresh Token 的既有会话撤销机制复用。

## 队列与投递核对

security_delivery_request 是受限数据库工作队列，存储恢复输入与来源上下文，不存OTP明文。HTTP响应前持久化，BackgroundTasks仅用于立即触发；独立worker可补处理 queued 请求。UPDATE state条件原子claim，多worker不会重复执行。同一任务一旦 processing 不自动重新发送；崩溃后保留已有挑战/发送额度，过期结束，防未知结果重复计费。过期5分钟未处理任务不会再发验证码，队列PII保留7天后清理。

生产需要每秒或数秒执行一次 `python tools/sms_gateway_ops.py worker-once`（由现有进程管理器调度），并监控队列积压/失败；状态核对使用 `python tools/sms_gateway_ops.py reconcile --challenge-id <uuid>`。仅内部运维可访问此工具。SendCloud状态查询可缓存10分钟；无provider ID的未知任务需要人工核查，不自动退费重发。

## 回归命令与测试证据

最终本轮相关回归：**514 passed，1 warning**（12.58秒）；warning来自原JWT错误密钥负向测试故意使用短密钥。新增/变更网关核心文件 Ruff 检查通过。管理端 `npm run build` 与小程序 `npm run build:mp-weixin` 均通过；小程序构建提示未配置Appid，未做微信真机验收。不是全仓库所有测试的通过声明。

从 backend 目录使用工作区虚拟环境运行：

```powershell
$env:SMS_TEST_POSTGRES='1'
$env:SMS_TEST_REDIS_URL='redis://127.0.0.1:16379/0'
..\.venv\Scripts\python.exe -m pytest tests/test_unified_auth_recovery.py tests/test_sms_gateway.py tests/test_sms_gateway_service.py tests/test_sms_gateway_postgres.py tests/test_sms_risk.py tests/test_sms_proxy_ip.py tests/test_sms_request_security.py tests/test_sendcloud_security.py tests/test_cov_core.py tests/test_cov_ach_identity.py tests/test_middleware_exception.py tests/test_routes_comprehensive.py -q
```

PostgreSQL显式开关默认仅连接本地Settings默认连接，或提供专用 SMS_TEST_POSTGRES_DSN。每个测试创建随机 sms_test_* schema，使用实际033/034迁移的隔离schema版本，结束删除该schema；没有修改业务行。Redis使用独立随机 sms:test:* 命名空间，测试后只清理该前缀。当前验收Redis为隔离Windows Redis 5.0.14.1，不作为生产推荐版本，部署仍须在实际受支持Redis版本复验。

已实际验证：30并发同手机号预留只有1次ALLOW；Redis+PostgreSQL全链路24并发只有1条Provider发送；16并发核验只签发1份Grant；16并发队列claim只执行1次；20并发Nonce只消费1次；配额幂等释放、未知结果不释放、自然日跨午夜TTL、手机号窗口/日限额、NAT不同目标CHALLENGE、设备限流、伪造XFF、IPv6、账号状态/管理员/存量来源拒发；OTP过期/错误次数持久化/绑定单次消费及密码重置会话失效。

独立安全复核已进行。提出的“Lua检查后写入竞态”由Redis脚本原子性和真实并发用例排除；公开入口的账号/IP限流在任何账号查找前统一执行，对不存在账号同样计数，429不作为绑定状态结果。人机验证和真实运营商通道仍按下方剩余项单独验收，不能视为已完成线上安全认证。

## 上线清单与明确剩余项

1. 安装依赖，先备份并审查033/034，按现有迁移流程执行；本次未在业务库执行。
2. 配置受支持的Redis（持久化、高可用、ACL、网络隔离、监控），设置业务时区及独立HMAC密钥，不能使用测试Redis。
3. 审核 Caddy/frp 实际可信链路：TRUSTED_PROXIES仅列明确节点，反代正确追加XFF/设置HTTPS；不要使用任意来源通配信任。配置CORS真实前端Origin。
4. 审核历史安全联系方式来源，管理员恢复交给额外因素/人工；本次不把未确权手机号提升为恢复资格。
5. 配置人机验证/平台证明适配器；目前CHALLENGE会拒绝发送，不能宣传已接入某个人机验证服务。调优NAT阈值并基于真实流量/成本压测，不永久封禁共享出口。
6. 部署内部队列补偿worker、回执核对、过期清理，设置受理/拒绝/未知/送达和队列积压告警；限制PII表和审计访问。未配置任何对外短信回调入口。
7. 校验SendCloud运营商报备和通道。之前真实短信590/sendLog4121仍未解决，本次风控实现不能解决运营商拒绝。
8. 真实短信验收独立进行：SMS_LIVE_TEST_ENABLED=true，同时显式执行 `python tools/sms_gateway_ops.py live-test --account <合格业务账号> --send`；仍执行完整风控，不能向未确权/不存在用户发送。只以终端收到或最终200回执确认送达，Mock/接口受理不等同送达。
9. 本次不推送、不部署、不提交真实密钥。生产流量容量、运营商通道真实送达、人机验证服务接入仍需单独验收。
