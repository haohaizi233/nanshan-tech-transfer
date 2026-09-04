const PRODUCTION_ENVS = ['staging', 'production']
const TUNNEL_H5_PORT = '8077'
const TUNNEL_API_PORT = '8076'
const DEFAULT_LOCAL_API_BASE = 'http://127.0.0.1:8787'

/**
 * Select the API origin for an H5 page without changing its public route.
 *
 * The dev launcher exposes H5 and FastAPI as a paired frp tunnel:
 * :8077 for the page and :8076 for its API.  A phone must never inherit the
 * developer machine's 127.0.0.1 API address from local.env.js.
 */
export function resolveH5ApiBase({ appEnv, localApiBase, pageLocation = globalThis.location } = {}) {
  if (PRODUCTION_ENVS.includes(appEnv)) return ''

  if (pageLocation && String(pageLocation.port) === TUNNEL_H5_PORT && pageLocation.hostname) {
    const protocol = pageLocation.protocol === 'https:' ? 'https:' : 'http:'
    return `${protocol}//${pageLocation.hostname}:${TUNNEL_API_PORT}`
  }

  return localApiBase || DEFAULT_LOCAL_API_BASE
}
