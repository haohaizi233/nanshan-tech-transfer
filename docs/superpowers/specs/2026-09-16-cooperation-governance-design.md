# 对接治理、库存与通知中心设计

## 目标

让成果与需求对接具备明确的联系方式授权、可并行且不超卖的名额库存、可运营的协助闭环、可分析的最终结果，以及逐条可跳转的通知中心。

## 全局约束

- 联系方式共享必须由发起方在请求体中明确传递 `contactShareConsent: true`；字段缺失、`false` 和其他类型均拒绝创建。
- 新发布成果和需求默认 `cooperationPolicy: "parallel"`、`inventoryMode: "unlimited"`。
- 限量内容以数据库内的 `available_slots` 作为事实源；禁止由前端计数决定可接受性。
- 不修改既有历史对接的含义：已有内容迁移为不限量并行，已有意向保持原状态。
- 轮询只读取未读聚合，不读取详情；前后台间隔统一为 5 秒，仅在可见页面生命周期运行。

## 内容发布与库存

成果表和需求表新增：

- `cooperation_policy`：`parallel` 或 `exclusive`，默认 `parallel`。
- `inventory_mode`：`unlimited` 或 `limited`，默认 `unlimited`。
- `inventory_total`：限量内容的总名额，必须大于 0；不限量时为 NULL。
- `available_slots`：限量内容当前可接受名额，必须介于 0 和 `inventory_total`；不限量时为 NULL。
- `manual_offline_at`：发布方手动停止接收新对接的时间；与库存耗尽分开记录。

发布端规则：

1. `parallel + unlimited`：不限制被接受的并行对接数量。
2. `parallel + limited`：发布方设置正整数名额；接受请求时预占一个名额。
3. `exclusive`：强制 `limited` 且总名额为 1；接受第一条请求后不再接受新请求。
4. `available_slots = 0`：内容对新请求显示“名额已满”，列表不再提供“我要对接”；当前合作方和发布者仍可访问详情。
5. 发布方手动下架不会取消已接受对接，只阻止新建请求。

库存状态机：

```text
pending --target accept--> reserved
reserved --completed + outcome=success--> consumed
reserved --cancelled/rejected/closed + outcome!=success--> returned
```

`reserved` 由 `cooperation_intent.inventory_reserved_at` 表示，不新增主状态；扣减和写入接受事件在同一事务、同一条带条件 UPDATE 中完成：`available_slots > 0` 才能成功。释放名额同样在终态写入事务中完成，保证并发不会超卖。成功完成不归还名额；失败、拒绝或取消归还。名额归还后若未手动下架，内容自动恢复接收新对接。

## 对接授权、运营与结果

`cooperation_intent` 新增运营字段：

- `last_contact_at`：最近一次运营联系时间。
- `next_followup_at`：下一次跟进时间。
- `attempt_count`：运营联系次数，默认 0。
- `sla_due_at`：当前阶段需处理截止时间。
- `inventory_reserved_at`：占用发布名额的时间。
- `close_reason_code` / `close_reason_note`：取消或关闭原因。

新表 `cooperation_outcome`（`intent_id UNIQUE`）记录最终业务结果：

- `outcome_type`：`signed`、`cooperating`、`no_deal`、`withdrawn`。
- `contract_signed`：是否签约。
- `final_cooperation_mode`：最终合作模式。
- `deal_amount_wan`：非负成交金额（万元，可空）。
- `failure_reason_code` / `failure_reason_note`：非成交结果的结构化原因和补充说明。
- `recorded_by_user_id`、`recorded_at`。

允许完成对接的角色（双方或运营管理员）必须提交结果；`signed` 和 `cooperating` 视为成功并消耗库存，其他结果会释放预占名额。取消/关闭必须选择原因枚举：`budget_mismatch`、`technical_mismatch`、`schedule_mismatch`、`no_response`、`withdrawn`、`other`；仅 `other` 额外要求说明。

协助对接运营接口允许管理员更新 `assist_status`、负责人、备注、跟进时间和联系次数。每次写入联系人动作自动更新 `last_contact_at`、递增 `attempt_count`；逾期查询以 `next_followup_at < NOW()` 或 `sla_due_at < NOW()` 筛选并排序。

## 通知中心

`notification_inbox` 是单条通知事实源。新增 API：

- `GET /me/notifications?cursor=&limit=`：按 `occurred_at DESC, id DESC` 返回当前用户通知、未读状态和精确 `targetPath`。
- `POST /me/notifications/{id}/read`：仅允许本人将单条标已读，幂等。
- `POST /me/notifications/read-all`：仅标记本人全部未读通知，支持可选 `category`。
- 保留 `GET /me/notifications/summary` 仅返回角标聚合。

小程序“我的”页提供通知入口与列表：点击单条先标已读再按 `targetPath` 跳转；全部已读只影响通知，不刷新业务详情页。后台铃铛打开同等能力的通知抽屉。两端轮询统一改为 5 秒，并使用 in-flight 保护。

## 数据迁移与兼容

新增顺序迁移：先为成果/需求添加默认并行不限量字段，再为对接添加运营与库存预占字段，再创建结果表及索引。对历史记录不回填占用时间、不调整库存；历史内容保持可见且不受新名额约束。现有自动拒绝逻辑只在 `exclusive` 内容的首次接受事务中执行；`parallel` 内容不得自动拒绝其他 pending。

## 测试

- 缺失、`false`、非布尔联系方式授权均不能创建对接；仅 `true` 成功。
- 并发接受限量内容时，只有剩余名额数的请求可成功；取消/失败结果恢复名额，成功结果不恢复。
- `exclusive` 仅接受一条；`parallel` 接受一条不影响其他 pending。
- 运营更新会正确推进联系次数、下次跟进和 SLA 逾期排序。
- outcome 的枚举、权限、必填规则及库存结果均受验证。
- 通知列表仅返回本人记录；单条/全量已读幂等，跳转路径完整。
- 小程序与后台轮询间隔为 5 秒，且只请求 summary。
