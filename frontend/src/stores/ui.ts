/**
 * UI Store — 管理界面状态（侧边栏/主题/通知）
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface ToastMessage {
  id: number
  text: string
  type: 'success' | 'error' | 'info'
}

let toastId = 0

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(false)
  const toasts = ref<ToastMessage[]>([])

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function showToast(text: string, type: ToastMessage['type'] = 'info') {
    const id = ++toastId
    toasts.value.push({ id, text, type })
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, 3000)
  }

  function dismissToast(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  return {
    sidebarCollapsed,
    toasts,
    toggleSidebar,
    showToast,
    dismissToast,
  }
})
