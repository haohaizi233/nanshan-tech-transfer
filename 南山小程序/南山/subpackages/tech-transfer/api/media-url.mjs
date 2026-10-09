import { resolveServiceOrigin } from './api-origin.js'

const LOCAL_MEDIA_SCHEME = /^(wxfile:|file:|blob:|data:)/i

export function isLocalMediaUrl(url) {
  return LOCAL_MEDIA_SCHEME.test(String(url || ''))
}

export function isImageMedia(item) {
  if (!item) return false
  const role = String(item.role || '')
  if (role === 'image' || role === 'cover' || role === 'gallery') return true
  if (String(item.mimeType || '').indexOf('image/') === 0) return true
  return /\.(png|jpe?g|gif|webp|bmp|heic)$/i.test(String(item.name || item.url || item.localPath || ''))
}

export function resolveMediaUrl(url, env = {}, pageLocation = globalThis.location) {
  const value = String(url || '').trim()
  if (!value) return ''
  if (isLocalMediaUrl(value) || /^https?:\/\//i.test(value)) return value
  const origin = resolveServiceOrigin(env, pageLocation)
  const path = value.startsWith('/') ? value : `/${value}`
  return `${origin}${path}`
}

export function withMediaAccessToken(url, token) {
  const value = String(url || '')
  if (!value || !token || isLocalMediaUrl(value)) return value
  if (/[?&]access_token=/.test(value)) return value
  return `${value}${value.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(token)}`
}

/** 发布预览优先本地临时文件；详情页把相对 /files/:id 补成可请求地址。 */
export function mediaDisplayUrl(item, env = {}, token = '', pageLocation = globalThis.location) {
  if (!item) return ''
  if (item.localPath) return item.localPath
  return withMediaAccessToken(resolveMediaUrl(item.url || item.thumbnailUrl, env, pageLocation), token)
}

export function splitDemandAttachments(attachments = []) {
  const list = Array.isArray(attachments) ? attachments : []
  return {
    images: list.filter(isImageMedia),
    files: list.filter((item) => !isImageMedia(item)),
  }
}
