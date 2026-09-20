import { onBeforeUnmount, ref } from 'vue'
import { api } from './client'

// 可取消的 API 请求 composable：
// - 每次 run() 自动取消上一次在途请求，避免快速导航时旧响应覆盖新状态
// - 组件卸载时自动取消在途请求
// - 被取消的请求 resolve 为 null（不抛错），调用方据此跳过状态写入
export function useAbortable() {
  const controller = ref(null)

  function abort() {
    if (controller.value) {
      controller.value.abort()
      controller.value = null
    }
  }

  async function run(path, options) {
    abort()
    const ac = new AbortController()
    controller.value = ac
    try {
      const data = await api(path, { ...options, signal: ac.signal })
      return data
    } catch (err) {
      if (err && err.name === 'AbortError') {
        return null
      }
      throw err
    } finally {
      if (controller.value === ac) {
        controller.value = null
      }
    }
  }

  onBeforeUnmount(abort)

  return { run, abort }
}
