# P2-06 交付报告

1. HEAD：70aab12433739153ce10e0206942c168038cb08c。已 fetch origin main；本地 HEAD 与 origin/main 一致。origin 实际为 Gitee 镜像。未提交、未推送；保留其他任务修改。
2. 根因：5 秒固定请求；续期完成后才加锁；全局持久缓存无身份归属；异步结果无会话校验；AI Tab 错用账号通知总数。
3. 策略：5 秒 setInterval 改为请求完成后单次 setTimeout 调度，默认 30 秒，缓存新鲜度 10 秒。首次立即刷新；后台清除定时器；恢复时复用新鲜缓存。网络错误保留有效结果并按 60、120、240、300 秒退避，成功复位。请求耗时会使实际间隔长于 30 秒。
4. 归属：仅 mine 且 count > 0 显示，1–99 数字，超过 99 为 99+；保留原样式。AI 无全局数字角标。
5. 缓存：按 userId 的内存 Map 隔离，不读取旧全局持久化键。登录、注销完成后同步失效旧状态，epoch 和请求前后身份校验阻止迟到摘要及续期响应覆盖新会话。普通续期不会重启轮询。重启 App 从 0 开始获取。
6. 修改文件：App.vue、pages.json、utils/notification-poller.js、api/client.js、components/app-tabbar.vue、pages/mine/mine.vue、新增 pages/notifications/notifications.vue、tests/notification-poller.test.mjs、tests/wechat-login.test.mjs（路径均相对 南山小程序/南山）。另外增加本报告和核心 diff。
7. 核心 Diff：同目录 p2-06-core.diff。新增通知页支持分页、标题/分类/时间、已读/未读、单条及全部已读；不执行载荷 targetPath 跳转。成功已读使用服务端 updated 立即扣减本地角标，再统一摘要校准；旧飞行中摘要被失效。后端和权限模型均未修改。
8. 测试：新增可控时钟、VM 加载实际轮询代码、模拟 HostBridge 请求，覆盖单例、新鲜恢复、后台停机、游客、续期锁、缓存隔离、迟到摘要、迟到续期、注销、401、网络退避、16→15、角标归属及格式。微信登录测试补充新增依赖绑定，保留原断言。
9. 实际验证：node --test notification-poller.test.mjs wechat-login.test.mjs 共 18/18 通过。完整 tests/*.test.mjs：381 项，376 通过，5 失败。失败名称：
   - dock-detail keeps the favorite star available after confirmation
   - uses the certification backdrop and compact actions in one unverified card row
   - local host mode still follows the H5 tunnel origin rule
   - uses the supplied visual resources on the mine page
   - patent preview follows the LocalAdapter H5 API routing rule
   在临时目录从 HEAD archive 执行基线，也复现上述五项；精简 archive 缺少仓库外层资源，另有环境性失败，不能把该基线的总数与工作区直接比较。
10. 构建：npm run build:h5、npm run build:mp-weixin 均 exit 0 / DONE Build complete。日志在仓库根目录 p2-06-h5.log、p2-06-weixin.log；测试日志 p2-06-tests.log。构建不等于真机验收。
11. 剩余风险：尚未进行不同屏宽、微信真机及浏览器实际可见性切换视觉验收；通知页操作和 UI 本身尚无挂载集成测试。H5 visibilitychange 作为 App 生命周期补充，同一单例调度器，微信构建移除浏览器 API。认证客户端和轮询器各自已有续期锁，本次仅修复轮询器内部重复续期，未统一两个模块的认证锁。其他业务操作不盲目刷新，当前明确同步登录/登出及通知已读事件。工作区同时存在其他任务新增修改，未覆盖。
12. 最终：FAIL（严格完整验收）。本任务核心自动化与两端构建 PASS，但完整回归存在上述既有失败，且真机/视觉验收未完成，不能宣称全部验收通过。

固定周期理论请求频率（不含首次、业务事件、续期、退避和请求耗时）：优化前每 5 秒一次，一小时 720 次；优化后每 30 秒一次，一小时 120 次；理论减少 83.3%。
