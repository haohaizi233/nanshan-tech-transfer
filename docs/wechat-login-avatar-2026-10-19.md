# 微信登录与头像修复

## 修复范围

- 头像操作弹层使用 H5 应用窗口左右边界，不再横向占满桌面浏览器。
- 微信相册入口优先 `wx.chooseMedia`，限定一张图片、仅相册；旧基础库和 H5 使用图片选择兼容路径。取消不覆盖旧头像，失败显示原因，不再无声失败。
- 微信端先通过 `wx.getPrivacySetting` 检查隐私授权；需要时展示隐私指引与官方 `agreePrivacyAuthorization` 按钮，用户明确同意后才开放相册、头像、手机号能力。不以普通弹窗或本地布尔值冒充授权。
- 头像临时路径先上传现有文件服务，资料只保存 `avatarFileId`。服务端检查本人上传、有效图片，并通过共享锁保护引用，已引用头像不能被文件删除接口删除。
- 头像文件访问沿用现有受控媒体读取接口，未改为公开私人上传文件；显示 URL 按现有媒体鉴权方式生成。

## 登录与绑定

1. 已绑定账号：`uni.login` 获取本次登录 code，后端 `code2Session` 核验微信身份，再签发原有业务会话。
2. 首次登录：要求用户通过微信手机号组件主动授权；前端分别提交 `loginCode`、`phoneCode`。后端向微信核验手机号、OpenID 关联、当前 AppID 水印和中国大陆号码，不接受客户端自报手机号或 OpenID。
3. 授权手机号已有密码账号：不自动合并。用户先用原手机号密码登录，再在“我的”授权同一登录手机号绑定微信；禁止跨用户绑定和替换已绑定身份。
4. 新手机号：创建普通账号，保留唯一手机号凭据，但随机初始化的密码不允许密码登录；用户可在“我的”首次设置 8—128 位密码后用于 H5 登录。设置和登录使用一致的首尾空白归一化；已有密码账号仍必须校验原密码。
5. 登录成功后沿用已有 access/refresh 会话；微信端可静默恢复已绑定身份，并发恢复共用一次请求。用户明确退出后关闭自动恢复；晚到登录/刷新响应不能覆盖退出状态。
6. H5 不展示微信小程序原生授权组件，保留手机号密码登录。微信登录为独立可选能力，不替换现有 `AUTH_PROVIDER=phone_password`。

## 上线前必须配置

1. **先执行 PostgreSQL 迁移** `tech-transfer-service/migrations/pg/027_profile_avatar_wechat_login.sql`，再更新主服务。新增头像外键和 `password_configured` 字段，已有密码账号默认保持启用。
2. 后端配置 `WECHAT_LOGIN_ENABLED=true`、`WECHAT_APPID`、`WECHAT_APP_SECRET`。AppID 必须与小程序一致；AppSecret 只放后端环境变量或密钥服务，不下发前端、不提交 Git。默认关闭，缺配置时拒绝微信登录，并保留密码方式。
3. 在微信公众平台确认手机号能力资格、权限/额度、服务端调用 IP 白名单；配置小程序 HTTPS request/uploadFile/downloadFile 合法域名。测试工具关闭域名校验不代表真机或生产可用。
4. 在微信后台完善并发布用户隐私保护指引，按实际用途声明头像/图片选择与手机号相关能力；本地同意按钮不能替代后台配置。
5. 更新并重新编译微信开发者工具中的小程序，再进行真机体验版验证。头像文件目录应使用持久化存储。

仅推送代码不等于完成数据库迁移、微信后台开通、服务部署或真机验收。当前没有调用真实付费手机号接口，也没有在用户手机上完成验收。

## 官方参考（2026-10-19 核验）

- [小程序登录](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html)
- [手机号快速验证组件](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/getPhoneNumber.html)：两个 code 不可混用，手机号 code 有效期 5 分钟、单次使用。
- [服务端获取手机号](https://developers.weixin.qq.com/miniprogram/dev/server/API/user-info/phone-number/api_getphonenumber.html)
- [chooseImage](https://developers.weixin.qq.com/miniprogram/dev/api/media/image/wx.chooseImage.html)：基础库 2.21.0 起停止维护，官方建议改用 chooseMedia。
- [chooseMedia](https://developers.weixin.qq.com/miniprogram/dev/api/media/video/wx.chooseMedia.html)
- [隐私授权说明](https://developers.weixin.qq.com/miniprogram/dev/api/open-api/privacy/wx.onNeedPrivacyAuthorization.html)：原生接口前轻触官方同意按钮的方式无需另设 pending 事件监听。

## 验证与限制

新增回归覆盖：头像上传与失败、文件所有权、账号切换晚到结果、微信身份与手机号双 code、已有账号防误合并、禁用身份、原账号绑定、旧手机号凭据回填、初始密码、退出及并发恢复、相册参数/新旧回调和隐私授权门禁。

最终验证：前端专项 38 项通过；前端全量 243 项中 240 项通过，3 项既有的 8076/8025 隧道端口断言失败；后端所选头像/微信/认证兼容/聊天历史 42 项通过；H5 和微信小程序构建均通过，Python 编译及 Git 空白检查通过。浏览器确认 H5 登录页正常显示且不出现微信小程序授权组件；未登录状态及本地后端/数据库不可用，未做头像上传端到端验证。

较大的三组旧后端测试在本次代码与 HEAD 基线内存加载对照中均出现相同的 71 项已有失败；未修改无关断言和服务。另有一个既有文件 token 测试依赖本地 PostgreSQL，当前数据库不可连接，不能作为通过依据。真实微信接口和真实 PostgreSQL 并发事务需部署环境验收。
