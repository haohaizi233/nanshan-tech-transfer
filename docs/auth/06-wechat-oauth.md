# 南山科转通微信开放平台 PC 网页 OAuth 接入指南 (06-wechat-oauth)

## 1. 架构定位

南山科转通支持两类微信身份认证体系：
1. **微信小程序端（原生）**：
   - 依赖微信小程序 AppID (`WECHAT_APPID`) 与 AppSecret (`WECHAT_APP_SECRET`)；
   - 采用 `jscode2session` 换取 Mini-Program OpenID，`getuserphonenumber` 授权手机号；
   - 映射为 `external_identity` (`issuer='wechat-mini'`)。
2. **PC 管理后台端（开放平台扫码）**：
   - 依赖微信开放平台网站应用 (`WECHAT_OPEN_APPID` 与 `WECHAT_OPEN_APP_SECRET`)；
   - 采用 OAuth2 Authorization Code 流程；
   - 映射为 `external_identity` (`issuer='wechat-web'`)；
   - 跨应用打通：依赖微信同一开放平台绑定的 `unionid` 实现跨端同主体匹配。

---

## 2. PC 扫码登录业务流程

```
[浏览器 / Vue 3 登录页]
   │
   ├─► 1. GET /auth/wechat/web/authorize?redirectUri=...
   │       服务端生成 256 位高熵一次性 state，缓存 10 分钟
   │       返回开放平台扫码 URL (open.weixin.qq.com/connect/qrconnect)
   │
   ├─► 2. 用户在 PC 端展示的微信二维码上完成手机扫码并确认授权
   │
   ├─► 3. 微信重定向回前端并带上 code 与 state 参数
   │
   ├─► 4. POST /auth/wechat/web/callback (code, state)
   │       - 验证 state 有效性并立即原子核销（防 CSRF 跨站请求伪造）
   │       - 服务端向微信官方接口换取 access_token、openid 与 unionid
   │       - 查库匹配 external_identity：
   │         a) 若已绑定账号：签发科转通业务会话 JWT，直接登录成功；
   │         b) 若未绑定账号：返回 bindingTicket，引导用户登录已有账号或注册后完成安全绑定。
```

---

## 3. 安全防护规范

1. **State 防 CSRF**：
   - `state` 采用密码学安全随机字符串；
   - 单次使用，核验即销毁；
   - 严格超时（10 分钟）。
2. **凭据隔离**：
   - 微信官方回调的 `code` 绝不直接向前端暴露业务 JWT；
   - 严禁将微信 `AppSecret` 打包进前端 bundle 或暴露于网络出站外。
3. **资质与配置降级**：
   - 当项目尚未申请到腾讯微信开放平台开发者资质时，配置 `WECHAT_OPEN_ENABLED=false`；
   - 系统安全关闭 PC 扫码选项，测试环境支持 `mock_code_*` 模拟测试。
