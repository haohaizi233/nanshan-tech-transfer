const PRODUCTION_ENVS = ['staging', 'production']
const TUNNEL_H5_PORT = '8077'
const TUNNEL_API_PORT = '8076'
const LOCAL_API_PORT = '8787'
const SAME_ORIGIN_PORTS = new Set(['', '80', '443'])
const LOCALHOST_HOSTNAMES = ['localhost', '127.0.0.1', '::1', '[::1]']
const DEFAULT_LOCAL_API_BASE = 'http://127.0.0.1:8787'

function readUniSystemInfo() {
  try {
    if (typeof uni !== 'undefined' && typeof uni.getSystemInfoSync === 'function') {
      return uni.getSystemInfoSync()
    }
  } catch (e) {
    // ignore
  }
  return null
}

function isWeixinMiniProgram(systemInfo) {
  if (!systemInfo) return false
  if (systemInfo.uniPlatform === 'mp-weixin') return true
  if (typeof wx !== 'undefined') return true
  return false
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

  const info = systemInfo || readUniSystemInfo()
  const weixinBase = weixinApiBase || deviceApiBase
  if (isWeixinMiniProgram(info) && weixinBase) {
    return weixinBase
  }

  return localApiBase || DEFAULT_LOCAL_API_BASE
}
