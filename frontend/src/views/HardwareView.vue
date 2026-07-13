<script setup lang="ts">
/**
 * HardwareView — 硬件监控页面 (从 prototype 迁移)
 *
 * 功能：
 * - 模型状态网格（主模型 + 交叉审查模型）
 * - 5 项硬件指标卡片（GPU温度/显存/内存/CPU/GPU利用率）含状态色和进度条
 * - 显存分配详情（已用/空闲/总量）
 * - 自动轮询（5s）+ 页面不可见时暂停
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { DashboardAPI, type HardwareData } from '@/api/dashboard'
import MiniLineChart from '@/components/common/MiniLineChart.vue'

const router = useRouter()
const systemStore = useSystemStore()
const uiStore = useUiStore()

// ── 硬件数据 ──
const hw = ref<HardwareData | null>(null)
const loading = ref(false)
let hwTimer: ReturnType<typeof setInterval> | null = null

interface HistoryPoint {
  time: string
  gpuTemp: number
  gpuUtil: number
  vram: number
  cpu: number
  ram: number
}
const history = ref<HistoryPoint[]>([])
const MAX_HISTORY = 60

function recordHistory() {
  if (!hw.value) return
  const now = new Date()
  const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`
  history.value.push({
    time,
    gpuTemp: hw.value.gpu.temp || 0,
    gpuUtil: hw.value.gpu.util || 0,
    vram: hw.value.gpu.vram_pct || 0,
    cpu: hw.value.cpu.pct || 0,
    ram: hw.value.ram.pct || 0,
  })
  if (history.value.length > MAX_HISTORY) {
    history.value = history.value.slice(history.value.length - MAX_HISTORY)
  }
}

const HW_THRESHOLDS = {
  gpu:   { warn: 80, danger: 90 },
  vram:  { warn: 85, danger: 95 },
  ram:   { warn: 85, danger: 94 },
  cpu:   { warn: 85, danger: 95 },
  power: { warn: 80, danger: 95 },
  fan:   { warn: 80, danger: 95 },
} as const

type HwKey = keyof typeof HW_THRESHOLDS

function getStatus(key: HwKey, value: number): 'normal' | 'warn' | 'danger' {
  const t = HW_THRESHOLDS[key]
  if (value >= t.danger) return 'danger'
  if (value >= t.warn) return 'warn'
  return 'normal'
}

function statusLabel(s: string): string {
  return s === 'normal' ? '正常' : s === 'warn' ? '注意' : '告警'
}

function statusColor(s: string): string {
  if (s === 'danger') return 'var(--danger)'
  if (s === 'warn') return 'var(--warning)'
  return 'var(--success)'
}

// ── 指标计算 ──
interface MetricCard {
  key: HwKey
  label: string
  sublabel: string
  value: number
  display: string
  status: 'normal' | 'warn' | 'danger'
  max: number
  pct: number
  icon: string
}

const metrics = computed<MetricCard[]>(() => {
  if (!hw.value?.gpu) return []
  const gpu = hw.value.gpu
  const cpu = hw.value.cpu
  const ram = hw.value.ram

  const items: Array<{ key: HwKey; label: string; sublabel: string; value: number; display: string; max: number; icon: string }> = [
    { key: 'gpu',   label: 'GPU 温度',  sublabel: 'Thermals', value: gpu.temp,     display: `${gpu.temp}°C`,   max: 100, icon: 'M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z' },
    { key: 'vram',  label: '显存占用',  sublabel: 'VRAM',     value: gpu.vram_pct, display: `${gpu.vram_pct}%`, max: 100, icon: 'M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7Zm6 2h2v6H8V9Zm5 0h2v6h-2V9Z' },
    { key: 'ram',   label: '内存占用',  sublabel: 'System',   value: ram.pct,      display: `${ram.pct}%`,     max: 100, icon: 'M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7Zm4 2v2m0 4v2m4-8v2m0 4v2m4-8v2m0 4v2m4-8v2m0 4v2' },
    { key: 'cpu',   label: 'CPU 占用',  sublabel: 'Processor',value: cpu.pct,      display: `${Math.round(cpu.pct)}%`, max: 100, icon: 'M9 3v3m6-3v3M9 18v3m6-3v3M4 9h3m-3 6h3m14-6h-3m3 6h-3M7 7h10v10H7V7Z' },
    { key: 'power', label: 'GPU 利用率',sublabel: 'Compute',  value: gpu.util || 0,display: `${gpu.util || 0}%`, max: 100, icon: 'M13 2 4.09 12.11a2 2 0 0 0 .03 2.74L6.27 17a2 2 0 0 0 2.74.03L19 8M17 4l4 4m-4-4 4 4' },
    { key: 'fan',   label: '风扇转速',  sublabel: 'Fan Speed',value: gpu.fan_speed || 0, display: `${gpu.fan_speed || 0}%`, max: 100, icon: 'M12 12c0-3 2.5-5.5 5.5-5.5S23 9 23 12H12zm0 0c0 3-2.5 5.5-5.5 5.5S1 15 1 12h11zm0 0c3 0 5.5 2.5 5.5 5.5S15 23 12 23V12zM12 12c-3 0-5.5-2.5-5.5-5.5S9 1 12 1v11z' },
  ]

  return items.map((item) => {
    const status = getStatus(item.key, item.value)
    const pct = Math.min(100, Math.round((item.value / item.max) * 100))
    return { ...item, status, pct }
  })
})

// ── VRAM 详情 ──
const vramInfo = computed(() => {
  if (!hw.value?.gpu) return null
  const { vram_used_mb, vram_total_mb } = hw.value.gpu
  if (!vram_total_mb) return null
  const usedGb = (vram_used_mb / 1024).toFixed(1)
  const totalGb = (vram_total_mb / 1024).toFixed(1)
  const freeGb = (Math.max(0, vram_total_mb - vram_used_mb) / 1024).toFixed(1)
  const usedPct = ((vram_used_mb / vram_total_mb) * 100).toFixed(1)
  const freePct = (100 - parseFloat(usedPct)).toFixed(1)
  return { usedGb, totalGb, freeGb, usedPct, freePct }
})

// ── 模型信息 ──
const mainModel = computed(() => systemStore.mainModel)
const crossModel = computed(() => systemStore.crossModel)
const mainRunning = computed(() => systemStore.modelRunning)
const crossRunning = computed(() => systemStore.crossModelRunning)
const modelToggling = computed(() => systemStore.modelToggling)

function modelStatusLabel(running: boolean): string {
  return running ? '运行中' : '未启动'
}

function modelHealthLabel(running: boolean, healthy?: boolean): string {
  if (!running) return '未启动'
  return healthy ? '健康' : '运行中'
}

async function toggleMainModel() {
  await systemStore.toggleModel()
  uiStore.showToast(
    systemStore.modelRunning ? '模型已启动' : '模型已停止',
    systemStore.modelRunning ? 'success' : 'info'
  )
}

// ── 数据获取 ──
async function fetchHw() {
  const { ok, data } = await DashboardAPI.getHardware()
  if (ok && data) {
    hw.value = data
    recordHistory()
  }
}

async function refresh() {
  loading.value = true
  await Promise.all([fetchHw(), systemStore.fetchModelStatus()])
  loading.value = false
}

// ── 生命周期 ──
function onVisibilityChange() {
  if (document.hidden) {
    if (hwTimer) { clearInterval(hwTimer); hwTimer = null }
  } else {
    fetchHw()
    if (!hwTimer) hwTimer = setInterval(fetchHw, 5000)
  }
}

onMounted(async () => {
  await refresh()
  hwTimer = setInterval(fetchHw, 5000)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  if (hwTimer) { clearInterval(hwTimer); hwTimer = null }
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="hardware-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-title">
        <h2>硬件监控</h2>
        <span class="page-subtitle">本地模型与 GPU 资源实时状态</span>
      </div>
      <div class="page-header-actions">
        <button class="btn btn-secondary btn-sm" @click="router.push('/logs')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>
          查看日志
        </button>
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 模型状态 -->
    <div class="section">
      <div class="section-title">模型状态</div>
      <div class="model-grid">
        <div class="model-card" :class="{ active: mainRunning }">
          <div class="model-card-top">
            <div class="model-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <span class="model-status-badge" :class="mainRunning ? 'running' : 'standby'">
              <span class="model-status-dot" :class="{ active: mainRunning }"></span>
              {{ modelStatusLabel(mainRunning) }}
            </span>
          </div>
          <div class="model-name">{{ mainModel?.name || '本地主模型' }}</div>
          <div class="model-meta">
            {{ mainModel?.quant ? `ctx 8192 · ${mainModel.quant}` : 'ctx 8192' }}
            · {{ mainModel?.port ? `localhost:${mainModel.port}` : 'localhost:8000' }}
          </div>
          <div class="model-metrics">
            <div class="model-metric">
              <span class="model-metric-label">健康状态</span>
              <span class="model-metric-value">{{ modelHealthLabel(mainRunning, mainModel?.healthy) }}</span>
            </div>
            <div class="model-metric">
              <span class="model-metric-label">端口</span>
              <span class="model-metric-value">{{ mainModel?.port || '-' }}</span>
            </div>
            <div class="model-metric">
              <span class="model-metric-label">量化</span>
              <span class="model-metric-value">{{ mainModel?.quant || '-' }}</span>
            </div>
          </div>
          <div class="model-actions">
            <button
              class="btn btn-sm"
              :class="mainRunning ? 'btn-secondary' : 'btn-primary'"
              :disabled="modelToggling"
              @click="toggleMainModel"
            >
              {{ modelToggling ? (mainRunning ? '停止中…' : '启动中…') : (mainRunning ? '停止模型' : '启动模型') }}
            </button>
          </div>
        </div>

        <div class="model-card" :class="{ active: crossRunning }">
          <div class="model-card-top">
            <div class="model-icon cross">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
            </div>
            <span class="model-status-badge" :class="crossRunning ? 'running' : 'standby'">
              <span class="model-status-dot" :class="{ active: crossRunning }"></span>
              {{ modelStatusLabel(crossRunning) }}
            </span>
          </div>
          <div class="model-name">{{ crossModel?.name || 'DeepSeek-R1-0528' }}</div>
          <div class="model-meta">
            {{ crossModel?.quant ? `ctx 8192 · ${crossModel.quant}` : 'ctx 8192' }}
            · {{ crossModel?.port ? `localhost:${crossModel.port}` : 'localhost:8002' }}
          </div>
          <div class="model-metrics">
            <div class="model-metric">
              <span class="model-metric-label">健康状态</span>
              <span class="model-metric-value">{{ modelHealthLabel(crossRunning, crossModel?.healthy) }}</span>
            </div>
            <div class="model-metric">
              <span class="model-metric-label">端口</span>
              <span class="model-metric-value">{{ crossModel?.port || '-' }}</span>
            </div>
            <div class="model-metric">
              <span class="model-metric-label">量化</span>
              <span class="model-metric-value">{{ crossModel?.quant || '-' }}</span>
            </div>
          </div>
          <div class="model-actions">
            <span class="model-hint">{{ crossRunning ? '由前端统一管理' : '未启动' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 硬件指标 -->
    <div class="section" v-if="metrics.length">
      <div class="section-title">硬件指标</div>
      <div class="metrics-grid">
        <div
          v-for="m in metrics"
          :key="m.key"
          class="metric-card"
          :class="'status-' + m.status"
        >
          <div class="metric-top">
            <div class="metric-icon" :style="{ color: statusColor(m.status) }">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path :d="m.icon"/></svg>
            </div>
            <span class="metric-status" :style="{ color: statusColor(m.status) }">{{ statusLabel(m.status) }}</span>
          </div>
          <div class="metric-value">{{ m.display }}</div>
          <div class="metric-label">{{ m.label }}</div>
          <div class="metric-sublabel">{{ m.sublabel }}</div>
          <div class="metric-bar">
            <span
              class="metric-bar-fill"
              :style="{ width: m.pct + '%', background: statusColor(m.status) }"
            ></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 趋势图 -->
    <div v-if="history.length > 1" class="section">
      <div class="section-title">最近 5 分钟趋势</div>
      <div class="trend-grid">
        <div class="trend-card">
          <div class="trend-label">GPU 温度</div>
          <MiniLineChart :data="history.map(h => ({ label: h.time, value: h.gpuTemp }))" color="var(--danger)" />
        </div>
        <div class="trend-card">
          <div class="trend-label">显存占用</div>
          <MiniLineChart :data="history.map(h => ({ label: h.time, value: h.vram }))" color="var(--warning)" />
        </div>
        <div class="trend-card">
          <div class="trend-label">CPU 占用</div>
          <MiniLineChart :data="history.map(h => ({ label: h.time, value: h.cpu }))" color="var(--success)" />
        </div>
        <div class="trend-card">
          <div class="trend-label">GPU 利用率</div>
          <MiniLineChart :data="history.map(h => ({ label: h.time, value: h.gpuUtil }))" color="var(--accent)" />
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="hw-empty">
      <div class="hw-empty-icon">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.25">
          <rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 9h6v6H9z" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
        </svg>
      </div>
      <p>{{ loading ? '正在获取硬件数据...' : '硬件数据不可用' }}</p>
      <p v-if="!loading" class="hw-empty-hint">请确认后端服务已启动且 GPU 驱动正常</p>
    </div>

    <!-- 显存分配详情 -->
    <div class="section" v-if="vramInfo">
      <div class="section-title">显存分配详情</div>
      <div class="vram-card">
        <div class="vram-main">
          <div class="vram-info">
            <div class="vram-total">
              <span class="vram-used">{{ vramInfo.usedGb }}</span>
              <span class="vram-separator">/</span>
              <span class="vram-capacity">{{ vramInfo.totalGb }} GB</span>
            </div>
            <div class="vram-label">已用显存</div>
          </div>
          <div class="vram-progress-block">
            <div class="vram-progress-header">
              <span>已用 {{ vramInfo.usedPct }}%</span>
              <span>空闲 {{ vramInfo.freeGb }}GB</span>
            </div>
            <div class="vram-progress-track">
              <div
                class="vram-progress-fill"
                :style="{ width: Math.max(parseFloat(vramInfo.usedPct), 2) + '%' }"
              ></div>
            </div>
          </div>
        </div>
        <div class="vram-stats">
          <div class="vram-stat">
            <div class="vram-stat-value">{{ vramInfo.totalGb }}GB</div>
            <div class="vram-stat-label">总量</div>
          </div>
          <div class="vram-stat">
            <div class="vram-stat-value">{{ vramInfo.usedGb }}GB</div>
            <div class="vram-stat-label">已用</div>
          </div>
          <div class="vram-stat">
            <div class="vram-stat-value">{{ vramInfo.freeGb }}GB</div>
            <div class="vram-stat-label">空闲</div>
          </div>
          <div class="vram-stat">
            <div class="vram-stat-value">{{ vramInfo.freePct }}%</div>
            <div class="vram-stat-label">可用比例</div>
          </div>
        </div>

        <!-- 显存进程明细 -->
        <div v-if="hw?.gpu?.vram_processes?.length" class="vram-processes">
          <div class="vram-processes-title">显存占用进程</div>
          <div class="vram-process-list">
            <div v-for="p in hw.gpu.vram_processes" :key="p.pid" class="vram-process-row">
              <div class="vram-process-info">
                <span class="vram-process-name" :title="p.name">{{ p.name }}</span>
                <span class="vram-process-pid">PID {{ p.pid }}</span>
              </div>
              <div class="vram-process-bar-wrap">
                <div class="vram-process-bar">
                  <div
                    class="vram-process-bar-fill"
                    :style="{ width: Math.min(100, Math.max(2, (p.used_mb / (hw.gpu.vram_total_mb || 1)) * 100)) + '%' }"
                  ></div>
                </div>
                <span class="vram-process-mb">{{ (p.used_mb / 1024).toFixed(2) }} GB</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="hw?.gpu?.vram_total_mb" class="vram-processes-empty">
          当前没有进程占用 GPU 显存
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hardware-page {
  padding: 20px 24px 24px;
  max-width: 1200px;
  margin: 0 auto;
  height: 100%;
  overflow-y: auto;
}

/* ── 页头 ── */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 16px;
}

.page-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title .page-subtitle {
  font-size: 13px;
  color: var(--text-muted);
}

.page-header-actions {
  display: flex;
  gap: 10px;
}

.page-header-actions .btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* ── 章节标题 ── */
.section {
  margin-bottom: 16px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
}

/* ── 模型卡片 ── */
.model-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.model-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.model-card.active {
  border-color: rgba(var(--success-rgb), 0.45);
  background: linear-gradient(180deg, rgba(var(--success-rgb), 0.06) 0%, var(--surface-solid) 100%);
}

.model-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.model-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  background: rgba(var(--accent-rgb), 0.1);
}

.model-icon.cross {
  color: var(--success);
  background: rgba(var(--success-rgb), 0.1);
}

.model-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
}

.model-status-badge.running {
  background: rgba(var(--success-rgb), 0.12);
  color: var(--success);
}

.model-status-badge.standby {
  background: var(--surface-faint);
  color: var(--text-muted);
}

.model-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.model-status-dot.active {
  animation: pulse 2s ease-in-out infinite;
}

.model-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}

.model-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.model-metrics {
  display: flex;
  gap: 24px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.model-metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.model-metric-label {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
}

.model-metric-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.model-actions {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.model-actions .btn {
  min-width: 92px;
}

.model-hint {
  font-size: 12px;
  color: var(--text-muted);
}

/* ── 硬件指标卡片 ── */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}

.metric-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 14px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.metric-card.status-warn {
  border-color: rgba(var(--warning-rgb), 0.35);
}

/* ── 趋势图 ── */
.trend-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.trend-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trend-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.trend-card .mini-line-chart {
  height: 40px;
  min-height: 40px;
}

.metric-card.status-danger {
  border-color: rgba(var(--danger-rgb), 0.4);
  background: rgba(var(--danger-rgb), 0.03);
}

.metric-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.metric-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.metric-status {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.metric-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.1;
}

.metric-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.metric-sublabel {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: -6px;
}

.metric-bar {
  height: 5px;
  border-radius: 3px;
  background: var(--surface-faint);
  overflow: hidden;
  margin-top: auto;
}

.metric-bar-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease, background 0.3s ease;
}

/* ── VRAM 卡片 ── */
.vram-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 22px;
}

.vram-main {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.vram-info {
  min-width: 140px;
}

.vram-total {
  display: flex;
  align-items: baseline;
  gap: 4px;
  color: var(--text);
}

.vram-used {
  font-size: 36px;
  font-weight: 700;
  line-height: 1;
}

.vram-separator {
  font-size: 18px;
  color: var(--text-muted);
}

.vram-capacity {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-secondary);
}

.vram-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 6px;
}

.vram-progress-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vram-progress-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary);
}

.vram-progress-track {
  height: 10px;
  border-radius: 5px;
  background: var(--surface-faint);
  overflow: hidden;
}

.vram-progress-fill {
  height: 100%;
  border-radius: 5px;
  background: linear-gradient(90deg, var(--accent), rgba(var(--accent-rgb), 0.6));
  transition: width 0.5s ease;
}

.vram-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.vram-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.vram-stat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}

.vram-stat-label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

/* ── 显存进程明细 ── */
.vram-processes {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
.vram-processes-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}
.vram-process-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.vram-process-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 12px;
  background: var(--surface-solid);
  border-radius: var(--radius-sm);
}
.vram-process-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 120px;
  max-width: 40%;
}
.vram-process-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vram-process-pid {
  font-size: 11px;
  color: var(--text-muted);
}
.vram-process-bar-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}
.vram-process-bar {
  flex: 1;
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}
.vram-process-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}
.vram-process-mb {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  min-width: 64px;
  text-align: right;
}
.vram-processes-empty {
  margin-top: 20px;
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--surface-solid);
  border-radius: var(--radius-sm);
}

/* ── 空状态 ── */
.hw-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 70px 20px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: 16px;
}

.hw-empty-icon {
  color: var(--text-muted);
  margin-bottom: 16px;
  opacity: 0.35;
}

.hw-empty p {
  font-size: 15px;
  color: var(--text);
  font-weight: 500;
  margin: 0 0 4px 0;
}

.hw-empty-hint {
  font-size: 12px;
  color: var(--text-muted);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@media (max-width: 1024px) {
  .metrics-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .model-grid {
    grid-template-columns: 1fr;
  }
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .vram-stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .vram-main {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
  .page-header {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
