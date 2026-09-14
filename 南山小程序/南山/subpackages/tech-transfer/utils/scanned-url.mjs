export function getScannedHttpUrl(value) {
  // 微信小程序 JavaScriptCore 不保证提供浏览器的 URL 构造器。
  // 二维码中的换行并非 URL 的有效组成部分，去掉后再作协议与主机校验。
  const text = String(value || '').replace(/\s+/g, '')
  if (!/^https?:\/\/[^/?#]+(?:[/?#][^\s]*)?$/i.test(text)) return ''
  return text
}
