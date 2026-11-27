import { getScannedHttpUrl } from './scanned-url.mjs'

export function splitHttpLinkText(text) {
  const segments = []
  const pattern = /https?:\/\/[^\s<>"'，。；：！？、（）【】《》“”‘’]+/gi
  let offset = 0

  for (const match of text.matchAll(pattern)) {
    let url = match[0].replace(/[.,!?;:]+$/, '')
    // 外层括号属于正文，网址路径中成对的括号则保留。
    while (url.endsWith(')') && url.split(')').length > url.split('(').length) {
      url = url.slice(0, -1)
    }
    if (!getScannedHttpUrl(url)) continue

    if (match.index > offset) segments.push({ text: text.slice(offset, match.index) })
    segments.push({ text: url, url })
    offset = match.index + url.length
  }

  if (offset < text.length) segments.push({ text: text.slice(offset) })
  return segments
}

export function hasHttpLink(text) {
  return splitHttpLinkText(String(text || '')).some((segment) => Boolean(segment.url))
}

export function parseStandaloneHttpLink(text) {
  const raw = String(text || '').trim()
  if (!raw) return null

  const segments = splitHttpLinkText(raw)
  const urlIndices = []
  for (let i = 0; i < segments.length; i += 1) {
    if (segments[i].url) urlIndices.push(i)
  }
  if (urlIndices.length !== 1) return null

  const urlIndex = urlIndices[0]
  const urlSegment = segments[urlIndex]
  const trailing = segments
    .slice(urlIndex + 1)
    .map((s) => s.text)
    .join('')
    .trim()
  if (trailing) return null

  const leading = segments
    .slice(0, urlIndex)
    .map((s) => s.text)
    .join('')
    .trim()
  if (!leading) {
    return { label: '', url: urlSegment.url, text: urlSegment.text }
  }

  if (leading.length > 24 || /[。！？!?]/.test(leading) || !/[:：]$/.test(leading)) {
    return null
  }

  const label = leading.replace(/[:：]+$/, '').trim()
  if (!label) return null

  return { label, url: urlSegment.url, text: urlSegment.text }
}
