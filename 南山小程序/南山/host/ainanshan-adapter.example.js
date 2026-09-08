/**
 * AiNanshanAdapter 示例骨架 —— 上级宿主（AiNanshan）适配器
 *
 * ⚠ 本文件为注释级契约骨架，不可运行，不参与编译引用。
 *    上级协议 C-01（凭证格式）/ C-03（网关身份传递）/ C-08（合并方式）
 *    均「已索取未确认」，全部按默认方案占位，确认后逐项落地。
 *
 * 合并步骤（决策 D1 的合并含义）：
 *   1. 将契约文件 host/host-bridge.js 原样拷入上级工程主包同路径
 *      （host/ 目录，保持相对引用层级：subpackages/tech-transfer/pages/* → ../../../../host/）
 *   2. 在上级工程 App.vue 的 onLaunch 中注册本 adapter：
 *        import HostBridge from './host/host-bridge.js'
 *        import AiNanshanAdapter from './host/ainanshan-adapter.js'
 *        HostBridge.registerAdapter(AiNanshanAdapter)
 *   3. 将 subpackages/tech-transfer/ 整目录并入上级工程（分包注册路径见 _navigate）
 *   4. LocalAdapter/mock-identity 仅本地开发使用，不随合并上送
 *
 * 接口契约：与 host/local-adapter.js 完全同构（HostBridge REQUIRED_METHODS 9 项）
 */

// ── 环境与网关配置（C-08 确认后替换） ─────────────────────────
// const GATEWAY_API_BASE = '<上级网关地址，C-08 合并方式确认后定>'
// const API_PREFIX = '/api/tech-transfer/v1'
// const SUBPACKAGE_ROOT = '/subpackages/tech-transfer/' // 上级实际注册路径，C-08 确认后调整

const AiNanshanAdapter = {
  /**
   * 环境快照 —— 分包经 HostBridge.getEnvironment() 读取
   * 返回字段与 LocalAdapter 对齐：appEnv/hostMode/authProvider/apiBase/apiPrefix
   * [C-08 待确认] apiBase 前缀语义取决于合并方式（独立网关域 / 同域路径前缀）
   */
  _getEnvironment() {
    return {
      appEnv: 'production',
      hostMode: 'ainanshan',
      authProvider: 'ainanshan',
      // apiBase: GATEWAY_API_BASE,
      // apiPrefix: API_PREFIX,
    }
  },

  /**
   * 宿主身份凭证 —— 分包 client.js 在 /auth/bootstrap 时携带
   * [C-01 待确认] 上级 Token / 一次性票据格式
   * 默认方案占位：{hostCredential: <上级登录态>}，形状与 LocalAdapter 一致
   */
  _getIdentityCredential() {
    // return { hostCredential: <上级当前登录态凭据> }
    throw new Error('[AiNanshanAdapter] C-01 未确认：上级凭证格式待定')
  },

  /**
   * 统一请求通道 —— 分包 api/client.js 的唯一出口
   * [C-03 待确认] 网关身份传递三选一：
   *   a) 透传原始 token（默认方案：Bearer 直传打网关）
   *   b) X-User-Id 可信头（网关完成验签后注入）
   *   c) 网关签发内部 token（上级登录态换取科转通内部会话）
   * 决策 D2：鉴权注入归本层（分包 client.js 不注入 Authorization）
   */
  async _request(options) {
    // const { method = 'GET', path, query, body, headers = {} } = options
    // 1. 组装 URL：GATEWAY_API_BASE + API_PREFIX + path + query 编码
    // 2. 注入身份（C-03 确认后实现）：headers['Authorization'] = 'Bearer ' + <上级凭据>
    // 3. 透传 X-Request-Id（无则生成），保持 requestId 全链路
    // 4. 经上级网络通道发请求（uni.request 或上级封装）
    // 5. 返回 SuccessEnvelope 原文（{code, message, data, requestId}），解包归 client.js
    throw new Error('[AiNanshanAdapter] C-03 未确认：网关身份传递方式待定')
  },

  /**
   * 文件上传
   * [08 #10 待确认] 上级统一上传通道
   * 返回值收敛为 {fileId, url}，与 LocalAdapter 契约一致
   */
  async _upload(file, options = {}) {
    // 经上级上传接口预签名/直传，返回 { fileId, url }
    throw new Error('[AiNanshanAdapter] 08 #10 未确认：上级上传通道待定')
  },

  /**
   * 分包内导航 —— path 为分包内相对路径（如 'pages/dock-detail/dock-detail'）
   * [C-08 待确认] 补全前缀 = 上级工程中本分包的实际注册根路径
   */
  _navigate(path, params) {
    // const url = SUBPACKAGE_ROOT + path + (params ? '?' + qs(params) : '')
    // uni.navigateTo({ url })
    throw new Error('[AiNanshanAdapter] C-08 未确认：分包注册根路径待定')
  },

  /**
   * 消息提示
   * [08 #11 待确认] 上级消息通道（uni.showToast 或上级统一 toast）
   */
  _showMessage(message, duration = 2000) {
    // uni.showToast({ title: message, icon: 'none', duration })
    throw new Error('[AiNanshanAdapter] 08 #11 未确认：上级消息通道待定')
  },

  /**
   * 错误上报
   * [08 #13 待确认] 上级埋点/监控通道
   */
  _reportError(error, context = {}) {
    // 上级监控 SDK 上报，context 至少含 requestId
    throw new Error('[AiNanshanAdapter] 08 #13 未确认：上级监控通道待定')
  },

  /**
   * 存储通道 —— 会话 key 沿用 tt_*（tt_access_token 等）
   * [C-01 待确认] 或改为映射上级会话（上级登录态即科转通登录态时，
   * 可整体省略 tt_* 会话，_request 每次取上级凭据）
   */
  _getStorage(key) {
    // return uni.getStorageSync(key)
    throw new Error('[AiNanshanAdapter] C-01 未确认：会话存储映射待定')
  },

  _setStorage(key, value) {
    // uni.setStorageSync(key, value)
    throw new Error('[AiNanshanAdapter] C-01 未确认：会话存储映射待定')
  },
}

export default AiNanshanAdapter
