/**
 * 安全导航辅助：集中处理 WeChat MP 页面栈上限（10 层）与“提示后返回”模式。
 *
 * 背景：CR R2-23 / R2-25 指出多个页面在调用 uni.navigateBack 前没有检查页面栈深度，
 * 且 setTimeout(() => uni.navigateBack(), 1200) 的写法在快速切换页面时会触发到错误页面。
 */

const MAX_PAGE_STACK = 10

function buildUrl(path, params) {
  if (!params) return path
  const query = Object.keys(params || {})
    .map((key) => {
      const value = params[key]
      if (value === undefined || value === null) return ''
      return `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`
    })
    .filter(Boolean)
    .join('&')
  if (!query) return path
  return path + (path.indexOf('?') >= 0 ? '&' : '?') + query
}

/** 包装 uni.navigateTo：页面栈满 10 层时改用 redirectTo，避免 MP 报错或静默失败。 */
export function safeNavigateTo(path, params = {}) {
  const url = buildUrl(path, params)
  const pages = (typeof getCurrentPages === 'function' ? getCurrentPages() : []) || []
  if (pages.length && pages.length < MAX_PAGE_STACK) {
    uni.navigateTo({ url })
    return
  }
  uni.redirectTo({ url })
}

/** 包装 uni.navigateBack：栈深度不足时静默返回，避免 MP 报错。 */
export function safeNavigateBack(delta = 1) {
  const pages = (typeof getCurrentPages === 'function' ? getCurrentPages() : []) || []
  if (pages.length > delta) {
    uni.navigateBack({ delta })
    return
  }
  // 栈里没有足够页面可回退（如直接从分享链接进入），退回首页避免卡在空白页。
  uni.switchTab?.({
    url: '/pages/dev-home/dev-home',
    fail() {
      uni.reLaunch({ url: '/pages/dev-home/dev-home' })
    },
  })
}

/**
 * “提示后返回”统一入口：先弹 toast，再延迟返回。
 * 关键修复：模块级只保留一个 pending 定时器，新调用会先清掉旧定时器，
 * 避免快速切换页面后旧定时器在错误页面触发 navigateBack。
 *
 * 返回当前定时器 id，调用方如有需要可自行保存；通常无需保存，
 * 因为下一次 safeBackWithToast 会自动清掉上一次的定时器。
 */
let pendingBackTimer = null

export function safeBackWithToast(message, delay = 1200) {
  if (pendingBackTimer) {
    clearTimeout(pendingBackTimer)
    pendingBackTimer = null
  }
  if (message) {
    uni.showToast({ title: message, icon: 'none' })
  }
  pendingBackTimer = setTimeout(() => {
    pendingBackTimer = null
    safeNavigateBack(1)
  }, delay)
  return pendingBackTimer
}

/** 供页面 onUnload 主动取消挂起的返回定时器（例如用户在 toast 期间手动返回）。 */
export function clearPendingBack() {
  if (pendingBackTimer) {
    clearTimeout(pendingBackTimer)
    pendingBackTimer = null
  }
}
