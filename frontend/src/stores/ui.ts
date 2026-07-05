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

export interface ConfirmOptions {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  type?: 'warning' | 'info' | 'danger'
}

interface ConfirmState extends ConfirmOptions {
  visible: boolean
  resolve: ((value: boolean) => void) | null
}

let toastId = 0
let confirmId = 0

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(false)
  const toasts = ref<ToastMessage[]>([])
  const confirm = ref<ConfirmState>({
    visible: false,
    title: '',
    message: '',
    confirmText: '确认',
    cancelText: '取消',
    type: 'warning',
    resolve: null,
  })

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

  function showConfirm(options: ConfirmOptions): Promise<boolean> {
    return new Promise((resolve) => {
      ++confirmId
      confirm.value = {
        ...options,
        title: options.title ?? '确认操作',
        confirmText: options.confirmText ?? '确认',
        cancelText: options.cancelText ?? '取消',
        type: options.type ?? 'warning',
        visible: true,
        resolve,
      }
    })
  }

  function closeConfirm(result: boolean) {
    const resolve = confirm.value.resolve
    confirm.value.visible = false
    confirm.value.resolve = null
    if (resolve) resolve(result)
  }

  return {
    sidebarCollapsed,
    toasts,
    confirm,
    toggleSidebar,
    showToast,
    dismissToast,
    showConfirm,
    closeConfirm,
  }
})
