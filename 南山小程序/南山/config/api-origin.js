const PRODUCTION_ENVS = ['staging', 'production']
const TUNNEL_H5_PORT = '8077'
const TUNNEL_API_PORT = '8025'
const LOCAL_API_PORT = '8787'
const SAME_ORIGIN_PORTS = new Set(['', '80', '443', '8025'])
const LOCALHOST_HOSTNAMES = ['localhost', '127.0.0.1', '::1', '[::1]']
const DEFAULT_LOCAL_API_BASE = 'http://127.0.0.1:8787'

function isWeixinMiniProgram(systemInfo) {
  // uni-app 在 H5 下同样注入 wx 全局别名，只看 typeof wx 会把本地 H5
  // 误判成小程序并把请求打到公网 HTTPS，因此优先按 uniPlatform 判定。
  if (systemInfo && systemInfo.uniPlatform) return systemInfo.uniPlatform === 'mp-weixin'
  // 避免调用已弃用的 getSystemInfoSync。浏览器里的 wx 别名由 window 判断排除。
  if (typeof window !== 'undefined') return false
  return typeof wx !== 'undefined'
}

/**
 * Resolve the API origin from the current H5 page, or from WeChat runtime
 * (小程序走公网 HTTPS；H5 仍按页面来源配对本机/隧道)。
 * Kept in the main package so App.vue / LocalAdapter never import a subpackage.
 */
export function resolveH5ApiBase({
  appEnv,
  localApiBase,
  weixinApiBase,
  deviceApiBase,
  pageLocation = globalThis.location,
  systemInfo,
} = {}) {
  const info = systemInfo
  const weixinBase = weixinApiBase || deviceApiBase
  if (isWeixinMiniProgram(info) && weixinBase) {
    return weixinBase
  }

  if (PRODUCTION_ENVS.includes(appEnv)) return ''

  if (pageLocation && pageLocation.hostname) {
    const protocol = pageLocation.protocol === 'https:' ? 'https:' : 'http:'
    const port = String(pageLocation.port || (protocol === 'https:' ? '443' : '80'))
    if (SAME_ORIGIN_PORTS.has(port)) return ''
    if (port === TUNNEL_H5_PORT) return `${protocol}//${pageLocation.hostname}:${TUNNEL_API_PORT}`
    if (!LOCALHOST_HOSTNAMES.includes(pageLocation.hostname)) {
      return `${protocol}//${pageLocation.hostname}:${LOCAL_API_PORT}`
    }
  }

  return localApiBase || DEFAULT_LOCAL_API_BASE
}
