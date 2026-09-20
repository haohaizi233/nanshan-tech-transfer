// 轻量全局 toast：单例容器，自动消失，简单防抖避免连续错误刷屏。

let toastEl = null
let toastTimer = null
let lastMessage = ''
let lastShownAt = 0

const TOAST_ID = 'nanshan-global-toast'

function ensureContainer() {
  if (toastEl && document.body.contains(toastEl)) return toastEl
  const existing = document.getElementById(TOAST_ID)
  if (existing) {
    toastEl = existing
    return toastEl
  }
  const el = document.createElement('div')
  el.id = TOAST_ID
  el.setAttribute('role', 'status')
  el.setAttribute('aria-live', 'polite')
  el.className = 'nanshan-toast'
  el.style.cssText = [
    'position:fixed',
    'top:24px',
    'left:50%',
    'transform:translate(-50%, -16px)',
    'z-index:3000',
    'max-width:80vw',
    'padding:10px 18px',
    'border-radius:8px',
    'background:rgba(38,50,66,.92)',
    'color:#fff',
    'font-size:14px',
    'line-height:1.5',
    'box-shadow:0 8px 24px rgba(20,34,52,.18)',
    'opacity:0',
    'transition:opacity .18s ease, transform .18s ease',
    'pointer-events:none',
    'word-break:break-word',
  ].join(';')
  document.body.appendChild(el)
  toastEl = el
  return el
}

export function showToast(message, { duration = 2400 } = {}) {
  if (typeof document === 'undefined') return
  const text = String(message || '').trim()
  if (!text) return

  // 同一消息在短时间内只弹一次，避免连续报错刷屏。
  const now = Date.now()
  if (text === lastMessage && now - lastShownAt < 1200) return
  lastMessage = text
  lastShownAt = now

  const el = ensureContainer()
  el.textContent = text
  // 重置 transform 以触发动画
  requestAnimationFrame(() => {
    el.style.opacity = '1'
    el.style.transform = 'translate(-50%, 0)'
  })

  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    el.style.opacity = '0'
    el.style.transform = 'translate(-50%, -16px)'
  }, duration)
}

export function hideToast() {
  if (toastTimer) {
    clearTimeout(toastTimer)
    toastTimer = null
  }
  if (toastEl) {
    toastEl.style.opacity = '0'
    toastEl.style.transform = 'translate(-50%, -16px)'
  }
  lastMessage = ''
}
