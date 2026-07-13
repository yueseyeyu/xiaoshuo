/**
 * System Store — 管理全局系统状态
 *
 * 模型状态轮询、版本号、系统健康状态
 * 对应旧版 prototype/js/main.js 中的 window.modelStatusState + checkModelStatus + loadAppVersion
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { DashboardAPI, type ModelStatusData, type ConfigData } from '@/api/dashboard'
import { useUiStore } from '@/stores/ui'

export const useSystemStore = defineStore('system', () => {
  // ── State ──
  const modelStatus = ref<ModelStatusData | null>(null)
  const modelLoading = ref(false)
  const modelToggling = ref(false)
  const config = ref<ConfigData | null>(null)
  const lastModelUpdate = ref(0)

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let visibilityHandler: (() => void) | null = null

  // ── Computed ──
  const mainModel = computed(() => modelStatus.value?.models?.main_model ?? null)
  const crossModel = computed(() => modelStatus.value?.models?.cross_model ?? null)

  const modelRunning = computed(() => {
    const m = mainModel.value
    return !!(m && (m.running || m.healthy))
  })

  const modelError = computed(() => modelStatus.value?.error ?? null)

  const modelName = computed(() => mainModel.value?.name ?? '模型')

  const crossModelRunning = computed(() => {
    const m = crossModel.value
    return !!(m && m.enabled && (m.running || m.healthy))
  })

  const version = computed(() => config.value?.version ?? '?')

  const systemMode = computed(() => config.value?.mode ?? 'local')

  // ── Actions ──

  /** 获取模型状态 */
  async function fetchModelStatus() {
    modelLoading.value = true
    const res = await DashboardAPI.getModelStatus()
    modelLoading.value = false
    if (res.ok && res.data && !res.data.error) {
      modelStatus.value = res.data
      lastModelUpdate.value = Date.now()
    }
    return res
  }

  /** 启动/停止模型 */
  async function toggleModel() {
    if (modelToggling.value) return
    modelToggling.value = true
    try {
      if (modelRunning.value) {
        await DashboardAPI.stopModel()
      } else {
        await DashboardAPI.startModel()
      }
      // 等待 3 秒后刷新状态（模型加载需要时间）
      setTimeout(() => fetchModelStatus(), 3000)
    } finally {
      modelToggling.value = false
    }
  }

  /**
   * 统一大模型入口守卫。
   * 若模型已运行直接返回 true；未运行则弹窗询问用户，确认后启动并等待就绪。
   */
  async function ensureModelRunning(operationName = '此操作'): Promise<boolean> {
    const uiStore = useUiStore()

    // 先刷新一次状态，避免误判
    await fetchModelStatus()
    if (modelRunning.value) return true

    const confirmed = await uiStore.showConfirm({
      title: '需要启动大模型',
      message: `${operationName}会开启本地大模型，期间将占用 GPU 显存并产生功耗。是否继续？`,
      confirmText: '启动并继续',
      cancelText: '取消',
      type: 'warning',
    })
    if (!confirmed) return false

    uiStore.showToast('正在启动大模型，请稍候...', 'info')
    await toggleModel()

    // 轮询等待模型就绪（最长 60 秒）
    const maxWaitMs = 60000
    const pollIntervalMs = 1500
    const startAt = Date.now()
    while (Date.now() - startAt < maxWaitMs) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs))
      await fetchModelStatus()
      if (modelRunning.value) {
        uiStore.showToast('大模型已就绪', 'success')
        return true
      }
    }

    uiStore.showToast('大模型启动超时，请检查硬件监控或手动启动', 'error')
    return false
  }

  /** 加载系统配置（版本号等） */
  async function fetchConfig() {
    const res = await DashboardAPI.getConfig()
    if (res.ok && res.data) {
      config.value = res.data
    }
    return res
  }

  /** 启动轮询 */
  function startPolling(intervalMs = 10000) {
    stopPolling()
    // 立即获取一次
    fetchModelStatus()
    pollTimer = setInterval(() => {
      if (document.hidden) return
      fetchModelStatus()
    }, intervalMs)

    if (!visibilityHandler) {
      visibilityHandler = () => {
        if (!document.hidden && !pollTimer) {
          fetchModelStatus()
          pollTimer = setInterval(() => {
            if (document.hidden) return
            fetchModelStatus()
          }, intervalMs)
        } else if (document.hidden && pollTimer) {
          clearInterval(pollTimer)
          pollTimer = null
        }
      }
      document.addEventListener('visibilitychange', visibilityHandler)
    }
  }

  /** 停止轮询 */
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (visibilityHandler) {
      document.removeEventListener('visibilitychange', visibilityHandler)
      visibilityHandler = null
    }
  }

  return {
    // state
    modelStatus,
    modelLoading,
    modelToggling,
    config,
    lastModelUpdate,
    // computed
    mainModel,
    crossModel,
    modelRunning,
    modelError,
    modelName,
    crossModelRunning,
    version,
    systemMode,
    // actions
    fetchModelStatus,
    toggleModel,
    ensureModelRunning,
    fetchConfig,
    startPolling,
    stopPolling,
  }
})
