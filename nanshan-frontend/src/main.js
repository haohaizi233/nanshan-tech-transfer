import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'

import './style.css'
import { showToast } from './utils/toast.js'

const app = createApp(App)

// 全局渲染错误兜底：记录日志并提示友好 toast，避免整页白屏。
app.config.errorHandler = (err, _instance, info) => {
  // eslint-disable-next-line no-console
  console.error('[app errorHandler]', err, info)
  if (err && err.name === 'AbortError') return
  showToast('页面渲染异常，请刷新重试')
}

// 未捕获的 Promise rejection 兜底，避免静默失败。
if (typeof window !== 'undefined') {
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event && event.reason
    if (reason && reason.name === 'AbortError') return
    // eslint-disable-next-line no-console
    console.error('[unhandledrejection]', reason)
    showToast('操作失败，请稍后重试')
  })
}

app.use(createPinia())
app.use(router)

app.mount('#app')
