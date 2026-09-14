export function getScannedHttpUrl(value) {
  const text = String(value || '').trim()
  try {
    const url = new URL(text)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : ''
  } catch (e) {
    return ''
  }
}
