# SendCloud 短信失败审计与根因分析

## 审计基准与证据边界

2026-11-17 重新执行 `git fetch github`；本地 HEAD 与 github/main 均为 `7c586c4`，相对远端0/0，工作树起始干净。用户给出的598728f并非本次审查基准。只读访问服务商，没有发短信、改生产数据、关风控或提升手机号确权。

本地新Python进程读取配置：APP_ENV=local，SMS_ENABLED=true，SMS_PROVIDER=sendcloud，REDIS_ENABLED=false，SMS_RISK_ENGINE_ENABLED=true，SMS_REQUIRE_VERIFIED_CONTACT=true，模板942819，重试3次；SMS凭据已配置（不记录实际值）。`.env`与`.env.local`存在，development/production文件不存在，进程环境DB_HOST/DB_PORT有覆盖。

配置优先级：进程环境 > `.env.{APP_ENV}` > `.env` > Settings默认值。Settings在模块导入时实例化，修改.env不会修改已运行的worker内存设置。本机未发现正在监听8787的FastAPI或正在运行的短信worker，不能验证部署环境是否重载；生产进程设置标记BLOCKED_EXTERNAL。

本地所配置Redis PING超时，PostgreSQL连接失败（仅保留异常类型），因此此配置快照不能完成实际短信网关链路。不能据此断言生产Redis/数据库也不可用。真实数据库033/034迁移、账号确权、队列记录和worker状态未取得证据，标记BLOCKED_EXTERNAL。

使用已有授权凭据进行了只读SendCloud查询：模板942819审核通过，实际模板变量仅 `%code%`。今日该模板7条返回记录中6条最终590，原始诊断码4121；1条最终200。最新返回记录时间11:01:27，11:01:47最终590/4121。记录时间沿用服务商显示，未自行换算。仅输出短信ID摘要，不保存接收人、验证码、凭据或原始响应。

追加只读目标比对：其中4条记录匹配用户此前授权的测试目标，全部为最终590；该目标最新记录为10:24:09/10:24:29，590/4121。另一条200不属于该目标。因此不能拿其他目标的200声称原测试号码送达。最新11:01记录也不属于原目标，不将其他目标的失败冒认为本次用户申请。

因此：可以确认**服务商下游存在真实失败记录**，但尚不能将最新一条应用请求和这些服务商记录逐一关联。也不能把其中一条200解释为用户所述申请已收到短信。不能断言通道已修复。

## 当前真实调用链与故障点（补丁前）

| 阶段 / 函数 | 正常状态 | 失败 / 可观察性 / 影响 |
|---|---|---|
| Vue/uni-app API Client → recovery/start | HTTP200仅表示已受理 | 前端仍有“已发送”文案，误导用户把入队等同送达 |
| validate_sms_request | Schema、HTTPS、Origin、服务间签名/Nonce通过 | HTTP4xx/503；未到供应商，不应显示账号资格 |
| request_gate | ALLOW | 风控/Redis失败；现有统一429混淆临时安全服务不可用与限流；有rule审计，无任务时需request_id追踪 |
| enqueue_recovery_task | queued，提交数据库 | 数据库错误则未入队；payload内部受限，不应打印 |
| run_queued_recovery_task | 原子queued→processing | 并发claim安全；调用结束后无条件finished是确定代码缺陷 |
| run_recovery_task | 调用业务/发送 | except仅警告request_id，丢失阶段与原因；失败被吞，是确定代码缺陷 |
| start_sms_recovery / ELIGIBLE_SQL | 命中1个符合要求的用户 | 无资格返回与正常相同dict，worker无法区分；无短信、不能放宽资格修复 |
| SmsRiskEngine.reserve | 原子reserved | 冷却/日限额/设备/IP/Redis/重复任务；任务只记笼统failed，规则需保留 |
| _send → auth_challenge | pending_send，稳定sendRequestId | 数据库失败退明确未发配额；必须记录阶段；幂等索引和预留保护重复发送 |
| SendCloudSmsProvider.send_task | API200/accepted | ProviderError丢失供应商状态；重新核对7c586c4发送变量已只有%code%，并非本轮新修复；新增契约测试固定实际模板变量，不将变量问题虚构为4121根因 |
| _set_send_state | accepted/rejected/unknown | 现有捕获后重抛通用ProviderError会丢失unknown属性和原始分类，可能误诊 |
| reconcile_sms_delivery | delivered/delivery_failed | 最终状态码仅在审计数组中，未保留原始数值诊断码，缺少任务级关联 |

公开返回仍应与资格无关；内部结果应分开。重试只允许原任务原sendRequestId；未知结果不释放成本、不自动创建OTP；生产不自动补发processing任务。

## 官方依据与历史590/4121

[发送API](https://www.sendcloud.net/doc/sms/api/)：200是API请求成功，sendRequestId一小时内去重；签名原文排序后SHA256，之后才URL编码。[投递回应](https://www.sendcloud.net/doc/sms/sms_status/)：最终200是送达，590属于发送失败其他原因，600是待回执；查询结果可缓存10分钟。590的API响应上下文和最终投递上下文必须区分。

官方公开文档没有查到4121具体解释，保留为供应商原始诊断码，不推测未备案/黑名单/号码问题。最早来源是本次聊天的真实发送及用户提供的历史回执；仓库仅06文档和实施计划记录过590/4121，没有完整历史原始日志。今日只读查询再次证实多条590/4121，但有一条200，不能一概认定所有请求失败同因。

## 经审计确定的最小修改范围

1. 追加迁移扩展现有队列/挑战诊断字段，不重写033/034或另建OTP系统。
2. 内部DeliveryTaskResult和类型化阶段错误，保留provider状态、unknown、risk rule，安全结构化事件及审计。
3. 队列根据真实结果进入completed/ineligible/blocked/config_error/failed/unknown/failed_internal；崩溃留下可核对状态，不重发。
4. Provider严格使用实际模板%code%，完善官方错误分类和受理/投递分离。
5. 内部CLI支持配置、队列、任务/Request ID、业务资格、Redis只读状态和Provider契约检查，默认不发短信。
6. 前端统一“请求已提交，符合条件才会发送”，倒计时只代表请求冷却。
7. Mock HTTP单元回归和隔离Redis/PostgreSQL并发验收；报告真实PASS/FAIL/SKIP及外部未验证项。

增量审计还发现：微信平台已验证手机号的新account_contact插入没有verification_method，034默认legacy_unknown会让新验证记录也不具备恢复资格。最小修复仅为这一条经过平台服务器验证的新增记录写入wechat来源；不回填历史记录，不修改账号合并规则。既有微信账号首次不设密码的password_configured=false限制继续保留，用户需先走登录后的密码设置及安全绑定流程。

迁移机制注意：仓库根run_migration.py仍使用pymysql且读取migrations/，不能直接用于migrations/pg/035。需在目标PostgreSQL按已有DB变更流程，使用psql的ON_ERROR_STOP执行035；不能把CI中“迁移失败可忽略”的日志当作035已经应用的证据。本轮只在隔离schema执行，未改生产迁移流程或实际业务库。

## 外部待确认（BLOCKED_EXTERNAL）

运行中FastAPI设置与重载时间；部署Redis/DB连通、迁移状态、worker；目标账号可信绑定；SMS_USER发送权限、白名单、余额；签名主体/运营商报备；与应用Task ID对应的服务商发送明细及4121权威解释、最终回执。模板审核只读已验证，其他未验证项不能用代码推测替代。

## 最终修改清单

执行过程中本地/远端另有CI修复推进至17dbffa；结束时重新fetch，两端0/0。未重置工作树，未回退并行成果。

| 文件 | 原问题 → 本轮行为 |
|---|---|
| modules/security/sms_delivery.py | 新增内部DeliveryTaskResult、阶段异常、安全结构化事件；明确结果、规则、服务商状态、调用标记和耗时；日志不包含原始异常文本/验证码/号码/密钥 |
| modules/security/sms_gateway.py | 异常吞掉/无条件finished → 真实结果驱动队列状态；配置/资格/风控/挑战写入/Provider/回执持久化/队列持久化分阶段；数据库不可用也有安全关联日志；资格细分；崩溃unknown不重发；保存最终回执码和原始诊断码 |
| modules/security/provider.py | 供应商错误只有通用文案 → reason_code/provider_status/retryable/request_attempted/outcome_unknown；按官方映射区分签名、模板、权限、余额、IP、参数、网络和响应错误；HTTP层与业务层分开；311部分受理与400重复请求不释放未知额度；仅%code%契约被测试固定 |
| modules/security/sms_request.py | 独立生成与前端响应不同的UUID → 复用core.response请求上下文Request ID，使响应、队列、审计关联 |
| modules/security/sms_diagnostics.py | 新增内部只读配置/队列/Request ID或Challenge ID/业务资格/Redis TTL及计数/离线Provider契约检查；短信ID仅输出摘要；旧/停滞任务不伪装已知未发送 |
| tools/sms_gateway_ops.py | 扩展内部CLI；默认不发送，依赖错误仅安全JSON；live-test除双开关还必须显式给出授权测试号码并匹配合格绑定；无公开HTTP诊断接口 |
| migrations/pg/035_sms_delivery_diagnostics.sql | 仅扩展现有任务与挑战诊断列和索引；已有finished转为legacy_unknown，不能倒推送达；migration在真实隔离PG验证可重复执行；不改业务账号数据 |
| modules/identity/wechat.py | 仅为平台服务端完成验证后新插入的安全手机号写入wechat来源；避免合法新记录误落legacy_unknown；不回填历史数据、不改变账号合并/权限 |
| ForgotPasswordView.vue、mine.vue恢复段 | “已发送”→统一“验证请求已提交，符合条件时才会发送”；冷却倒计时不表示投递；提示既有邮件/其他验证方式 |
| tests/test_sendcloud_security.py、test_sms_delivery_results.py、test_sms_diagnostics.py、test_sms_gateway_postgres.py、test_sms_request_security.py、test_wechat_login.py及recovery-acceptance-wording.test.mjs | 增加错误、关联、诊断、并发、崩溃及前端文案回归；旧失败测试未删除，既有风控未关闭 |

文件路径均相对tech-transfer-service，Vue页面和文案测试位于nanshan-frontend，小程序位于南山小程序/南山。

## 当前状态模型与脱敏链路

任务：queued→processing→completed / ineligible / blocked / config_error / failed / unknown / failed_internal。超过期限仍未处理为expired；processing失联按claimed_at判定，转unknown，不能自动重入队。

发送：reserved→accepted / rejected / unknown→delivered / delivery_failed。

OTP：复用pending_send/pending/verified/consumed和expired/locked/failed/cancelled，没有重建验证码系统。

下面为**隔离自动化测试链路示例，不是真实发送声明**：

```text
HTTP requestId=R，统一Request Accepted
  → task_id=T，queued
  → 单worker原子claim，processing
  → challenge_id=T；sendRequestId=T
  → SendCloud API Accepted；内部保存smsIds，CLI只显示ID摘要
  → worker completed（仅说明处理并受理完成）
  → 查询最终590/sendLog4121
  → auth_challenge.send_state=delivery_failed
  → task.outcome=DELIVERY_FAILED，failure_stage=delivery
  → diagnose(R或T)：provider_request_accepted=true，final_delivery=failed
```

下游投递失败不把已经成功完成的任务处理重跑，任务处理完成与短信送达分别保存。未知接收结果、重复sendRequestId、数据库回执写失败不会自动创建第二个OTP。服务商SMS ID含接收号码，因此不能直接输出，内部表访问需受限。

公开未符合资格的账号仍然同样受理，不暴露内部reason；内部可区分account_not_found/contact_not_verified/credential_not_configured/account_disabled/account_deleted/privileged_account_restricted/contact_conflict。旧响应Request ID与当时另生成的任务上下文ID无法凭空修复，旧记录优先通过Challenge ID查，迁移不捏造缺失历史。

## 运维执行顺序（不发送短信）

在backend目录、目标环境使用正确虚拟环境：

```powershell
python tools/sms_gateway_ops.py config-check
python tools/sms_gateway_ops.py queue-check
python tools/sms_gateway_ops.py diagnose --request-id <响应中的RequestID>
python tools/sms_gateway_ops.py diagnose --challenge-id <UUID>
python tools/sms_gateway_ops.py diagnose --account <授权运维核查的账号>
python tools/sms_gateway_ops.py risk-check --phone <授权核查号码> --ip <客户端IP> --device-id <实例ID> --challenge-id <UUID>
python tools/sms_gateway_ops.py provider-check
```

config-check明确标注fresh_cli_process_not_running_worker；它不能证明运行中的worker已重载。实际本轮执行结果：Redis PING超时、PostgreSQL连接失败、REDIS_ENABLED=false。queue-check安全返回diagnostic_failed/OperationalError，不把不可连接误报为队列为空。provider-check离线契约通过，real_send_attempted=false。

risk-check只读GET/TTL/ZCOUNT/TIME，检查冷却、日配额、滑动窗口、预留与pending_outcome；不调用check_request/reserve，不清空Key，不消费额度。IP/设备/账号/手机号参数不回显。每日account额度按发送时真实user_id，而请求频率按请求账号，两者应按实际需要分别检查。

迁移/重启/worker执行必须由目标环境授权运维实施：先验证033/034及035结构，使用已配置的安全PG连接运行`psql -v ON_ERROR_STOP=1 -f migrations/pg/035_sms_delivery_diagnostics.sql`；随后重启所有FastAPI/补偿worker并复核设置，配置周期性worker-once及内部回执核对。不得只改.env后假设运行时生效。Caddy源文件保留Host、X-Request-Id、Authorization等头；实际TLS、XFF/frp多跳及TRUSTED_PROXIES匹配仍须在部署环境验证，不修改网络信任来绕过风控。

真实验收须另有明确授权，SMS_LIVE_TEST_ENABLED=true且显式--send、--account、--phone；号码必须与合格安全绑定匹配，仍执行原风控，仅创建一个逻辑任务。**本轮没有执行live-test。**

## 最终回归结果

相关后端扩大回归实际输出：**558 PASS / 0 FAIL / 0 SKIP，18.76秒，1条warning**。warning来自原JWT错误密钥测试故意使用短密钥，不是短信配置错误。包含用户要求的7个文件，另含任务结果、诊断、微信及核心认证/路由回归。

```powershell
$env:SMS_TEST_POSTGRES='1'
$env:SMS_TEST_REDIS_URL='redis://127.0.0.1:16379/0'
..\.venv\Scripts\python.exe -m pytest tests/test_sendcloud_security.py tests/test_sms_gateway.py tests/test_sms_gateway_service.py tests/test_sms_gateway_postgres.py tests/test_sms_risk.py tests/test_sms_request_security.py tests/test_unified_auth_recovery.py tests/test_sms_delivery_results.py tests/test_sms_diagnostics.py tests/test_wechat_login.py tests/test_cov_core.py tests/test_cov_ach_identity.py tests/test_middleware_exception.py tests/test_routes_comprehensive.py -q
```

PostgreSQL使用回环地址的专用随机sms_test_* schema，真实执行033/034/035并在结束清理；Redis使用回环16379和随机测试Key前缀，未指向生产。验证过多workerclaim一次、并发OTP核销、各任务终态、受理后崩溃不重发、590/4121存储、Request ID定位、旧finished迁移、异常文本不泄露。首次迁移测试曾暴露状态字符串超过旧VARCHAR(16)，已用兼容legacy_unknown修复并重跑通过；测试没有删除。

前端文案/认证视图6项通过，小程序相关安全/密码反馈8项通过；管理端npm run build与小程序npm run build:mp-weixin通过。小程序构建提示未配置统计所需Appid，未做微信真机验收。Ruff对本轮Python改动检查通过。不是全仓库、生产流量或真实运营商送达的通过声明。

## 最终十项结论

1. 为什么之前发不出去：原授权测试目标4条有明确最终590/4121，属于供应商下游失败记录；4121具体原因只能由供应商权威解释。对用户本次新增申请，**尚未取得部署环境运行时证据，不能确认本次真实根因**，不能把其他目标的发送记录冒认为本次。
2. 代码问题：后台吞异常、无条件finished、错误元数据丢失、Request ID不一致、前端误报已发送、微信新确权来源遗漏；均已补丁和回归。
3. 配置问题：本地新进程Redis关闭且不可连、PG不可连是实测阻断；部署环境是否同样配置错误、是否重载仍BLOCKED_EXTERNAL，不凭本地推断生产。
4. 平台/运营商问题：590为最终投递失败；当前模板审核通过；签名主体/备案、SMS_USER权限、白名单、余额与4121含义仍需公司和SendCloud确认。
5. 异常吞掉：已改为结构化结果、阶段码、安全异常类型、耗时和关联事件；不能写DB时保留安全日志，不打印原始异常中的敏感内容。
6. 队列错误完成：已修复，失败按真实结果分态，旧finished标unknown。completed不等同delivered。
7. 单一ID定位：新请求可通过响应Request ID或Challenge ID查询受控CLI；DB完全不可用时用同ID的结构化服务日志，不能假装已有DB记录。旧ID缺失不捏造。
8. 重复发送：claim CAS、预留、稳定sendRequestId均保留，崩溃/unknown不自动重发，受控网络重试复用同一ID；仍需生产Redis/供应商幂等及worker配置实际验收，不能声称绝对零风险。
9. 真实送达：**不能确认原授权测试目标已送达；本轮未发真实短信**。另一目标的一条200不作为原目标验收。
10. 缺少证据：目标环境config-check/迁移/worker与队列结果；本次申请的Request ID/Challenge ID；对应SendCloud发送明细、余额/授权/备案和4121权威解释、目标最终200回执或终端收到证据。

## 公司/服务商控制台核对清单

| 项目 | 本轮状态 | 下一步 |
|---|---|---|
| 模板942819审核与变量 | 已只读确认审核通过，仅%code% | 不凭空增加%time%或code变量 |
| SMS_USER/SMS_KEY配置 | 已配置且只读查询鉴权成功 | 发送权限与当前IP授权仍BLOCKED_EXTERNAL |
| 短信签名主体/运营商报备 | BLOCKED_EXTERNAL | 控制台核验对应主体与通道报备，不只看模板审核 |
| 白名单/余额/额度 | BLOCKED_EXTERNAL | 核对发送授权、出口IP白名单及短信余额 |
| 原目标4条590/4121 | 已取得只读最终失败证据 | 用控制台内部发送ID、模板、时间提交SendCloud工单；要求解释原始4121及对应通道，不盲目重复发送 |
| 用户本次新增申请与服务商记录关联 | BLOCKED_EXTERNAL | 用新Request ID/Challenge ID在目标环境诊断并关联发送ID |
| 原目标真实送达 | 未通过 | 只有目标终端收到或对应最终200才算送达，不以HTTP受理/Mock通过替代 |
