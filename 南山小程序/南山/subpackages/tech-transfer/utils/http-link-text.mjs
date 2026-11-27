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
