import { resolveH5ApiBase } from '../../../config/api-origin.js'

export { resolveH5ApiBase }

/** 媒体/专利等需直接给 <image> 用的绝对 origin（小程序不能走页面相对路径）。 */
export function resolveServiceOrigin(env = {}, pageLocation = globalThis.location) {
  if (env.hostMode === 'local') {
    return resolveH5ApiBase({
      appEnv: env.appEnv,
      localApiBase: env.apiBase,
      pageLocation,
    })
  }
  if (env.apiBase) return String(env.apiBase).replace(/\/$/, '')
  try {
    if (pageLocation && pageLocation.origin) return pageLocation.origin
  } catch (e) {
    // ignore
  }
  return ''
}
