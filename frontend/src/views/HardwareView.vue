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
import { DashboardAPI, type HardwareData } from '@/api/dashboard'

const router = useRouter()
const systemStore = useSystemStore()

// ── 硬件数据 ──
const hw = ref<HardwareData | null>(null)
const loading = ref(false)
let hwTimer: ReturnType<typeof setInterval> | null = null

const HW_THRESHOLDS = {
  gpu:   { warn: 75, danger: 85 },
  vram:  { warn: 80, danger: 90 },
  cpu:   { warn: 80, danger: 92 },
  ram:   { warn: 85, danger: 94 },
  power: { warn: 80, danger: 95 },
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
  value: number
  display: string
  status: 'normal' | 'warn' | 'danger'
  max: number
  pct: number
}

const metrics = computed<MetricCard[]>(() => {
  if (!hw.value?.gpu) return []
  const gpu = hw.value.gpu
  const cpu = hw.value.cpu
  const ram = hw.value.ram

  const items: Array<{ key: HwKey; label: string; value: number; display: string; max: number }> = [
    { key: 'gpu',   label: 'GPU 温度',   value: gpu.temp,     display: `${gpu.temp}°C`,   max: 100 },
    { key: 'vram',  label: '显存占用',   value: gpu.vram_pct,  display: `${gpu.vram_pct}%`, max: 100 },
    { key: 'ram',   label: '内存占用',   value: ram.pct,       display: `${ram.pct}%`,     max: 100 },
    { key: 'cpu',   label: 'CPU 占用',   value: cpu.pct,       display: `${Math.round(cpu.pct)}%`, max: 100 },
    { key: 'power', label: 'GPU 利用率', value: gpu.util || 0, display: `${gpu.util || 0}%`, max: 100 },
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

// ── 数据获取 ──
async function fetchHw() {
  const { ok, data } = await DashboardAPI.getHardware()
  if (ok && data) hw.value = data
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
      <h2>硬件</h2>
      <div class="page-header-actions">
        <button class="btn btn-secondary btn-sm" @click="router.push('/logs')">查看日志</button>
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <div class="hardware-layout">
      <div class="hardware-main">
        <!-- 模型状态网格 -->
        <div class="model-status-grid">
          <!-- 主模型 -->
          <div class="model-status-card" :class="{ active: mainRunning, standby: !mainRunning }">
            <div class="model-status-header">
              <span class="model-dot" :class="{ active: mainRunning }"></span>
              <h4>主模型</h4>
              <span class="model-badge" :class="mainRunning ? 'running' : 'standby'">
                {{ mainRunning ? '运行中' : '已停止' }}
              </span>
            </div>
            <div class="model-name">{{ mainModel?.name || '未配置' }}</div>
            <div class="model-meta">
              {{ mainModel?.quant ? `ctx 8192 · ${mainModel.quant}` : 'ctx 8192' }}
              · {{ mainModel?.port ? `localhost:${mainModel.port}` : 'localhost:8000' }}
            </div>
            <div class="model-metrics">
              <div class="model-metric">
                <b>状态</b>
                <span>{{ mainModel?.healthy ? '健康' : mainRunning ? '运行中' : '-' }}</span>
              </div>
              <div class="model-metric">
                <b>端口</b>
                <span>{{ mainModel?.port || '-' }}</span>
              </div>
              <div class="model-metric">
                <b>量化</b>
                <span>{{ mainModel?.quant || '-' }}</span>
              </div>
            </div>
          </div>

          <!-- 交叉审查模型 -->
          <div class="model-status-card" :class="{ active: crossRunning, standby: !crossRunning }">
            <div class="model-status-header">
              <span class="model-dot" :class="{ active: crossRunning }"></span>
              <h4>交叉模型</h4>
              <span class="model-badge" :class="crossRunning ? 'running' : 'standby'">
                {{ crossRunning ? '运行中' : '待机' }}
              </span>
            </div>
            <div class="model-name">{{ crossModel?.name || 'DeepSeek-R1-0528' }}</div>
            <div class="model-meta">
              {{ crossModel?.quant ? `ctx 8192 · ${crossModel.quant}` : 'ctx 8192' }}
              · {{ crossModel?.port ? `localhost:${crossModel.port}` : 'localhost:8002' }}
            </div>
            <div class="model-metrics">
              <div class="model-metric">
                <b>状态</b>
                <span>{{ crossModel?.healthy ? '健康' : crossRunning ? '运行中' : '待机' }}</span>
              </div>
              <div class="model-metric">
                <b>端口</b>
                <span>{{ crossModel?.port || '-' }}</span>
              </div>
              <div class="model-metric">
                <b>量化</b>
                <span>{{ crossModel?.quant || '-' }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 硬件指标卡片 -->
        <div class="hardware-metrics-row" v-if="metrics.length">
          <div
            v-for="m in metrics"
            :key="m.key"
            class="metric-card"
            :class="'status-' + m.status"
          >
            <div class="metric-main">
              <div class="metric-value" :style="{ color: statusColor(m.status) }">{{ m.display }}</div>
              <div class="metric-label">{{ m.label }}</div>
            </div>
            <div class="metric-bar">
              <span
                class="metric-bar-fill"
                :style="{ width: m.pct + '%', background: statusColor(m.status) }"
              ></span>
            </div>
            <div class="metric-status" :style="{ color: statusColor(m.status) }">
              {{ statusLabel(m.status) }}
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="hw-empty">
          <div class="hw-empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 9h6v6H9z" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
            </svg>
          </div>
          <p>{{ loading ? '正在获取硬件数据...' : '硬件数据不可用' }}</p>
          <p v-if="!loading" class="hw-empty-hint">请确认后端服务已启动且 GPU 驱动正常</p>
        </div>

        <!-- 显存分配详情 -->
        <div class="vram-breakdown-card" v-if="vramInfo">
          <div class="vram-header">
            <h4>显存分配详情</h4>
            <span class="vram-subtitle">共 <b>{{ vramInfo.totalGb }}GB</b></span>
          </div>
          <div class="vram-progress-wrapper">
            <div class="vram-progress-track">
              <div
                class="vram-progress-fill"
                :style="{ width: Math.max(parseFloat(vramInfo.usedPct), 2) + '%' }"
              ></div>
            </div>
            <div class="vram-progress-labels">
              <span>已用 {{ vramInfo.usedGb }}GB ({{ vramInfo.usedPct }}%)</span>
              <span>空闲 {{ vramInfo.freeGb }}GB ({{ vramInfo.freePct }}%)</span>
            </div>
          </div>
          <div class="vram-stats-grid">
            <div class="vram-stat">
              <div class="vram-stat-label">总量</div>
              <div class="vram-stat-value">{{ vramInfo.totalGb }}GB</div>
            </div>
            <div class="vram-stat">
              <div class="vram-stat-label">已用</div>
              <div class="vram-stat-value">{{ vramInfo.usedGb }}GB</div>
            </div>
            <div class="vram-stat">
              <div class="vram-stat-label">空闲</div>
              <div class="vram-stat-value">{{ vramInfo.freeGb }}GB</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hardware-page {
  padding: 16px 24px;
  height: 100%;
  overflow-y: auto;
}

/* ── 页头 ── */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}
.page-header-actions {
  display: flex;
  gap: 8px;
}

/* ── 布局 ── */
.hardware-layout {
  display: flex;
  gap: 16px;
}
.hardware-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 900px;
}

/* ── 模型状态网格 ── */
.model-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.model-status-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  transition: border-color 0.2s;
}
.model-status-card.active {
  border-color: rgba(var(--success-rgb), 0.3);
}
.model-status-card.standby {
  border-color: var(--border);
  opacity: 0.85;
}

.model-status-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.model-status-header h4 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  flex: 1;
}

.model-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  transition: background 0.2s;
}
.model-dot.active {
  background: var(--success);
  box-shadow: 0 0 0 2px rgba(var(--success-rgb), 0.25);
  animation: pulse 2s ease-in-out infinite;
}

.model-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.model-badge.running {
  background: rgba(var(--success-rgb), 0.12);
  color: var(--success);
}
.model-badge.standby {
  background: var(--surface-highlight);
  color: var(--text-secondary);
}

.model-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}

.model-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.model-metrics {
  display: flex;
  gap: 16px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.model-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.model-metric b {
  font-size: 10px;
  color: var(--text-muted);
  font-weight: 500;
  text-transform: uppercase;
}
.model-metric span {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

/* ── 硬件指标卡片 ── */
.hardware-metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.metric-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.2s;
}
.metric-card.status-warn {
  border-color: rgba(var(--warning-rgb), 0.3);
}
.metric-card.status-danger {
  border-color: rgba(var(--danger-rgb), 0.35);
  background: rgba(var(--danger-rgb), 0.03);
}

.metric-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
}

.metric-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.metric-bar {
  height: 4px;
  border-radius: 2px;
  background: var(--surface-faint);
  overflow: hidden;
}
.metric-bar-fill {
  display: block;
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease, background 0.3s ease;
}

.metric-status {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

/* ── VRAM 分解 ── */
.vram-breakdown-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
}

.vram-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}
.vram-header h4 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}
.vram-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
}
.vram-subtitle b {
  color: var(--text);
  font-weight: 600;
}

.vram-progress-wrapper {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vram-progress-track {
  height: 8px;
  border-radius: 4px;
  background: var(--surface-faint);
  overflow: hidden;
}
.vram-progress-fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--accent), rgba(var(--accent-rgb), 0.6));
  transition: width 0.5s ease;
}
.vram-progress-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-secondary);
}

.vram-stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.vram-stat {
  text-align: center;
}
.vram-stat-label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin-bottom: 2px;
}
.vram-stat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}

/* ── 空状态 ── */
.hw-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}
.hw-empty-icon {
  color: var(--text-muted);
  margin-bottom: 12px;
  opacity: 0.4;
}
.hw-empty p {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 4px 0;
}
.hw-empty-hint {
  font-size: 12px;
  color: var(--text-muted);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

@media (max-width: 768px) {
  .hardware-metrics-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .model-status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
