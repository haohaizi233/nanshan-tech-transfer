# P2-07 验收报告

日期：2026-11-17（Asia/Singapore）

## 1. 基线与工作区

已 fetch GitHub main，并执行 ff-only 同步（Already up to date）。最新远端 main / 开始时 HEAD：`70aab12433739153ce10e0206942c168038cb08c`。未创建提交、未推送。

开始时存在需求预算、成员管理及测试等未提交修改，全部保留。执行期间观察到其他页面和测试继续变化，未回退、暂存或提交这些并行修改。全量回归结果对应当前共享工作区，不能视为纯净 main 的回归。

## 2. 根因及具体泄露路径

注册以 display_name or phone 写入用户资料。原 _counterpart_display 直接读取 display_name，经 list_my_intents/get_intent_detail 输出 counterpartDisplayName，前端 my-list 拼入副标题。该字段不经过 _counterpart_contact 状态/角色控制，因此 pending 发起方即使只能获得脱敏电话，仍能从展示名读到完整号码。新增测试以手机号及 +86 分隔手机号复现这一问题（修改前 18 失败、51 通过）。

布局方面已核实原标题与不可收缩标签共用一行，标题缺少 min-width:0，标签缺少换行；这是窄屏挤压风险，尚未用实际渲染复现覆盖，不能断言 gap 是唯一根因。

## 3. 修复后身份优先级及权限依据

- direct 发起方查看目标方：目标 target_org_id 对应 active institution，且目标方具有该机构 active organization_membership，才使用该机构名。
- direct 接收方查看发起方：使用安全 profile 昵称；不将目标机构冒充发起方机构。
- assisted 无目标账号：保留 target_org_id 关联的 active institution 名称；无安全名称时为“目标机构”。
- 机构不可用时，使用过滤后的 user_profile.display_name；无安全昵称则为“对方用户”。
- 统一纯函数去首尾空格，NFKC 规范化检测，拒绝含 @、连续或常见分隔符分隔的长号码、纯数字及明显账号前缀编号；有效姓名保持原意。此规则保守过滤，不声称能识别任意刻意混淆联系方式。

依据为现有 institution（active 表示对外可见）、organization_membership（active 成员关联）及 cooperation_intent.target_org_id。未连接生产数据库核验真实数据；未读取 companyText、申请表 real_name 或额外用户资料；未改用户原始数据、数据库结构或公开接口。

## 4. 原有联系方式规则

审查了 _counterpart_display、_counterpart_contact、_contact_response、get_intent_detail、list_my_intents。仅改身份解析；联系方式、创建时共享授权、角色限制和状态机均保留。

pending 发起方查看目标方：脱敏；pending 接收方查看申请方：按既有创建授权解锁；accepted/confirmed/completed 解锁；cancelled/rejected 双方重新脱敏。12 项状态角色矩阵验证通过。非参与方详情拒绝行为沿用既有测试；列表仍按登录 user_id 限制，新增测试确认传入其他 userId 参数不能改变查询归属。

## 5. 后端文件与核心 Diff

- tech-transfer-service/modules/cooperation/service.py：新增 normalize_counterpart_display_name；_counterpart_display 统一机构/昵称/兜底解析。机构查询在原查询内关联有效成员，无额外每行查询。
- tech-transfer-service/tests/test_cooperation_service.py：新增 43 项身份过滤、角色、assisted、状态权限、列表详情一致性、查询归属和机构优先级测试。
- tech-transfer-service/tests/test_cov_orgs_demand.py：已有 direct 测试使用明确昵称 fixture；assisted 无机构测试预期改为明确安全兜底。该文件另有并行成员测试修改，予以保留。

核心变化：原 `return profile.display_name` 改为 `safe(org_name) or safe(display_name) or 对方用户`；assisted 使用 `safe(institution.name) or 目标机构`。

## 6. 前端文件与核心 Diff

- 南山小程序/南山/subpackages/tech-transfer/pages/my-list/my-list.vue：_counterpartName、_counterpartPrefix、_intentLabel 分别承载身份、方向和意向，在独立 text 行显示。保留 _intentId、_openType、_openId、_role、状态转换和切换请求逻辑。
- 南山小程序/南山/subpackages/tech-transfer/pages/dock-detail/dock-detail.vue：联系方式区域新增独立“对接对象”行，直接使用服务端统一 counterpartDisplayName；联系人继续按 counterpartContact 权限显示。
- 南山小程序/南山/tests/cooperation-identity.test.mjs：新增 9 项真实映射函数测试及模板布局约束检查（不等同视觉验收）。

## 7. 标签布局

卡片标题占满首行，min-width:0，允许长串断行；标签容器位于下一行，限制 max-width:100%，允许 flex-wrap，标签文字不拆分。长身份字段允许断行。未添加 absolute/z-index，保留原状态颜色与语义。通用卡片标题布局随本页调整，未修改其他列表页面。

## 8. 自动化结果

- 后端全量：2245 passed、31 skipped、1 warning（11.03s）。跳过项未冒充通过。
- 合作服务专项：82 passed（含新增 43 项）。
- 前端本任务专项：9 passed。
- 前端全量：392 项，387 passed、5 failed。

前端失败项：cr-business-fixes 的收藏星标静态断言（HEAD 已使用 floating-star-btn，旧断言要求 star-btn）；认证卡片布局断言；mine 视觉资源断言；local host H5 路由断言；patent preview 路由断言（8025 与 8076 不一致）。这些断言涉及的逻辑不在本次修复范围，未删除测试或改无关业务以强行通过。并行工作区仍在变化，以上为执行时快照。

## 9. H5 / 微信小程序验收

`npm run build:h5`：DONE Build complete。
`npm run build:mp-weixin`：DONE Build complete。

构建成功不等同实际布局验收。320、360、375、414px、系统字体放大、多状态标签、按钮点击与切换的真实渲染/交互、微信开发者工具与真机均未执行。没有将静态检查作为视觉验收，也未声称已复现并消除实际重叠。

## 10. 数据库查询性能

原每行：目标摘要一次查询 + 对方名称一次查询；修复后仍为每行两次，分页计数和列表查询不变，总计约 2+2N（最多 N=50）。direct 名称查询新增一个限定 target_org_id 的成员/机构子查询，使用现有机构主键及成员 user/status 索引；不增加往返次数，不扩大为所有机构查询。详情查询次数也未增加。现有 N+1 未整体重构；尚无真实数据库 EXPLAIN/耗时基准，不声称延迟无变化。

## 11. 剩余风险

全量前端仍有 5 个失败，端侧视觉及交互验收缺失；未在生产数据库验证数据质量和查询计划。名称过滤保守，可能将某些编号式昵称降级；任意混淆联系方式无法仅用通用正则完全识别。缺少机构成员关系的历史目标将降级昵称，不从私人申请资料补名。

## 12. 最终结论：FAIL

代码修复、后端回归与双端构建已完成；由于全量前端未全绿且所要求的窄屏/微信实际视觉验收尚未完成，不能判定完整验收 PASS。未部署、未推送。
