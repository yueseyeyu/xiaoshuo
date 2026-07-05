/**
 * useVisibilityPause — 页面不可见时自动暂停轮询
 *
 * 用法：
 * const { start, stop } = useVisibilityPause(() => { fetchData() }, 3000)
 * onMounted(start)
 * onUnmounted(stop)
 */
import { onMounted, onUnmounted } from 'vue'

export function useVisibilityPause(callback: () => void, intervalMs: number) {
  let timer: ReturnType<typeof setInterval> | null = null

  function tick() {
    if (document.hidden) return
    callback()
  }

  function start() {
    if (timer) return
    tick()
    timer = setInterval(tick, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function onVisibilityChange() {
    if (document.hidden) {
      stop()
    } else {
      start()
    }
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    stop()
  })

  return { start, stop }
}
