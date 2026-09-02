/**
 * HostBridge 契约 —— 分包与宿主之间的唯一桥梁
 * 契约只定义接口形状，不含任何实现
 * 随分包合并上级，稳定不变
 */

const REQUIRED_METHODS = [
  '_getEnvironment',
  '_getIdentityCredential',
  '_request',
  '_upload',
  '_navigate',
  '_showMessage',
  '_reportError',
  '_getStorage',
  '_setStorage',
]

const HostBridge = {
  _adapter: null,

  registerAdapter(adapter) {
    if (this._adapter) {
      throw new Error('[HostBridge] adapter already registered')
    }
    this._validate(adapter)
    this._adapter = adapter
  },

  getAdapter() {
    return this._adapter
  },

  isReady() {
    return this._adapter !== null
  },

  getEnvironment() {
    return this._require()._getEnvironment()
  },

  getIdentityCredential() {
    return this._require()._getIdentityCredential()
  },

  request(options) {
    return this._require()._request(options)
  },

  upload(file, options) {
    return this._require()._upload(file, options)
  },

  navigate(path, params) {
    return this._require()._navigate(path, params)
  },

  showMessage(message, duration) {
    return this._require()._showMessage(message, duration)
  },

  reportError(error, context) {
    return this._require()._reportError(error, context)
  },

  getStorage(key) {
    return this._require()._getStorage(key)
  },

  setStorage(key, value) {
    return this._require()._setStorage(key, value)
  },

  _require() {
    if (!this._adapter) {
      throw new Error('[HostBridge] no adapter registered — 宿主未完成装配，页面禁止渲染')
    }
    return this._adapter
  },

  _validate(adapter) {
    const missing = REQUIRED_METHODS.filter((m) => typeof adapter[m] !== 'function')
    if (missing.length > 0) {
      throw new Error(`[HostBridge] adapter missing methods: ${missing.join(', ')}`)
    }
  },
}

export default HostBridge
