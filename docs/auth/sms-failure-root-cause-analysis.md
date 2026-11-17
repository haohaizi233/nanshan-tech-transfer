# SendCloud 短信失败审计与根因分析

## 审计基准与证据边界

2026-11-17 重新执行 `git fetch github`；本地 HEAD 与 github/main 均为 `7c586c4`，相对远端0/0，工作树起始干净。用户给出的598728f并非本次审查基准。只读访问服务商，没有发短信、改生产数据、关风控或提升手机号确权。

本地新Python进程读取配置：APP_ENV=local，SMS_ENABLED=true，SMS_PROVIDER=sendcloud，REDIS_ENABLED=false，SMS_RISK_ENGINE_ENABLED=true，SMS_REQUIRE_VERIFIED_CONTACT=true，模板942819，重试3次；SMS凭据已配置（不记录实际值）。`.env`与`.env.local`存在，development/production文件不存在，进程环境DB_HOST/DB_PORT有覆盖。

配置优先级：进程环境 > `.env.{APP_ENV}` > `.env` > Settings默认值。Settings在模块导入时实例化，修改.env不会修改已运行的worker内存设置。本机未发现正在监听8787的FastAPI或正在运行的短信worker，不能验证部署环境是否重载；生产进程设置标记BLOCKED_EXTERNAL。

本地所配置Redis PING超时，PostgreSQL连接失败（仅保留异常类型），因此此配置快照不能完成实际短信网关链路。不能据此断言生产Redis/数据库也不可用。真实数据库033/034迁移、账号确权、队列记录和worker状态未取得证据，标记BLOCKED_EXTERNAL。

使用已有授权凭据进行了只读SendCloud查询：模板942819审核通过，实际模板变量仅 `%code%`。今日该模板7条返回记录中6条最终590，原始诊断码4121；1条最终200。最新返回记录时间11:01:27，11:01:47最终590/4121。记录时间沿用服务商显示，未自行换算。仅输出短信ID摘要，不保存接收人、验证码、凭据或原始响应。

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
| SendCloudSmsProvider.send_task | API200/accepted | ProviderError丢失供应商状态；vars含不存在的%time%，与实际模板不一致，需最小修复；不能证明冗余变量就是4121原因 |
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

## 外部待确认（BLOCKED_EXTERNAL）

运行中FastAPI设置与重载时间；部署Redis/DB连通、迁移状态、worker；目标账号可信绑定；SMS_USER发送权限、白名单、余额；签名主体/运营商报备；与应用Task ID对应的服务商发送明细及4121权威解释、最终回执。模板审核只读已验证，其他未验证项不能用代码推测替代。
