export function previewImageUrls(urls, currentUrl = '') {
  const list = (Array.isArray(urls) ? urls : [])
    .map((item) => String(item || '').trim())
    .filter(Boolean)
  if (!list.length) return false
  const candidate = String(currentUrl || '').trim()
  const current = candidate && list.includes(candidate) ? candidate : (candidate || list[0])
  if (typeof uni !== 'undefined' && typeof uni.previewImage === 'function') {
    uni.previewImage({
      urls: list,
      current,
    })
    return true
  }
  return false
}

export function previewSingleImage(url) {
  const clean = String(url || '').trim()
  if (!clean) return false
  return previewImageUrls([clean], clean)
}
