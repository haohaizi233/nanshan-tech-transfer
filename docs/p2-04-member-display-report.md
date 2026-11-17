# P2-04 机构成员展示验收报告

1. HEAD：`70aab12433739153ce10e0206942c168038cb08c`。桌面仓库 GitHub main 已 fetch 且差异为 0/0；origin 为 Gitee（落后 GitHub），未执行回退。未提交/并发改动保留，无提交或推送。
2. 根因：正式成员表不存姓名，成员查询仅选择 user_no；前端也只展示编号。
3. 姓名策略：合并同用户、同机构两类 approved 申请，排除空白姓名，按 reviewed_at DESC NULLS LAST、id DESC、source DESC 选一条。审核时间相同按 ID 决定，完全相同时成员申请优先；有审核时间优先于无时间历史记录。无可用申请时保守读取展示名（中文姓名或拉丁字母姓名格式，排除手机号、编号及常见占位名）；最后 realName=null。nameSource 明确区分 membership_application、admin_application、profile_display_name；均不宣称实名核验。
4. API：仅增强机构管理员成员列表的 SELECT 投影，新增 realName/nameSource；不变更路由、权限检查、成员关系 ID、version、审批、撤销或公开机构接口。申请审核查询保持原语义。
5. 页面：姓名主标题；编号单独保留；角色标签、部门、职务分别显示；无姓名显示“未填写姓名”。空字段不产生分隔符。文本可折行，按钮不压缩。申请列表也展示姓名和编号。请求序号及机构/标签快照阻止迟到响应跨机构覆盖。
6. SQL：使用相关标量子查询及 UNION ALL/LIMIT 1，不增加成员行，不改变 COUNT、排序、LIMIT/OFFSET；固定一次分页查询，无应用层 N+1。姓名子查询只返回一个 JSON 值，资料主键保证一行。真实 PostgreSQL 临时表验证查询、隔离、分页与 EXPLAIN ANALYZE。011 迁移中只有 pending 申请局部索引，approved 历史量大时相关子查询可能扫描较多记录；生产数据规模和计划未取得，不能宣称生产性能已验证。后续可根据实际计划评估 (user_id, org_id, reviewed_at DESC, id DESC) WHERE status='approved' 索引；本次不新增迁移。
7. 核心 Diff：membership/service.py 增加姓名子查询和保守展示名过滤；org-manage.vue 增加姓名编号与职务、折行和迟到响应防护；test_member_names.py 新增真实 SQL 测试；test_cov_orgs_demand.py 补齐一个旧模拟查询结果；organization-management-layout.test.mjs 增加真实 Vue 渲染与异步逻辑测试。
8. 后端测试：全量重跑 2293 通过、31 跳过、1 条已有 JWT 短密钥警告；专项真实 PostgreSQL 14/14 通过。结果见工作区 p2-04-backend-tests.log。新增测试使用 PostgreSQL TEMP TABLE，连接结束 rollback；不写真实业务数据。既有 test_organization_membership.py 中 HTTP 流程需要运行中的后端与业务数据库，未单独运行该脚本。
9. 前端：专项 8/8 通过；全量 372 项，367 通过、5 失败。失败名称：dock-detail keeps the favorite star available after confirmation；uses the certification backdrop and compact actions in one unverified card row；local host mode still follows the H5 tunnel origin rule；uses the supplied visual resources on the mine page；patent preview follows the LocalAdapter H5 API routing rule。H5 与微信小程序构建均 DONE Build complete。微信构建提示 Appid 未配置，无法使用 uni statistics。未做微信真机或浏览器像素级布局验收。
10. 历史兼容：无申请管理员仍返回成员；无可靠姓名为 null，编号和角色保留；历史身份关系无更新。
11. 风险：配置中的业务数据库连接失败，无法核实真实姓名分布或生产查询计划；展示名规则可能保守地拒绝部分合法姓名，也不能识别所有昵称，因此明确来源。全量前端测试存在上述失败；未做真机布局验收。另有其他任务并发修改，未覆盖或提交。
12. 最终结论：FAIL（严格完整验收尚未通过）；本次专项测试与两端构建通过，全量前端失败和生产/真机验证待处理。
