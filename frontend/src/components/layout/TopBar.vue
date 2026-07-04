<script setup lang="ts">
/**
 * TopBar — 顶部栏 v3
 *
 * 玻璃拟态 + 品牌色切换器 + 硬件监控 + 模型状态（3 态）
 * 对齐 prototype 视觉标准，复用 DashboardAPI
 */
import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { DashboardAPI, type HardwareData } from '@/api/dashboard'

const projectStore = useProjectStore()
const systemStore = useSystemStore()
const uiStore = useUiStore()

// ── 硬件监控 ──
const hw = ref<HardwareData | null>(null)
const hwOpen = ref(false)
const hwRef = ref<HTMLElement | null>(null)
let hwTimer: ReturnType<typeof setInterval> | null = null

async function fetchHw() {
  const { ok, data } = await DashboardAPI.getHardware()
  if (ok && data) hw.value = data
}

function hwStatusClass(): string {
  if (!hw.value?.gpu) return ''
  const { temp, vram_pct } = hw.value.gpu
  if (temp > 85 || vram_pct > 90) return 'status-danger'
  if (temp > 75 || vram_pct > 80) return 'status-warn'
  return ''
}

function hwLabel(): string {
  if (!hw.value?.gpu) return '硬件检测中…'
  return `${hw.value.gpu.temp}°C / ${hw.value.gpu.vram_pct}%`
}

// ── 品牌色切换 ──
const presets = [
  { key: 'serene', label: '静谧蓝', color: '#38BDF8', rgb: '56,189,248' },
  { key: 'arctic', label: '极光青', color: '#22D3EE', rgb: '34,211,238' },
  { key: 'lavender', label: '薰衣草', color: '#A78BFA', rgb: '167,139,250' },
  { key: 'aurora', label: '极光靛', color: '#818CF8', rgb: '129,140,248' },
]
const activePreset = ref('serene')

function setPreset(key: string) {
  activePreset.value = key
  localStorage.setItem('accent_preset', key)
  const p = presets.find(p => p.key === key)
  if (p) {
    document.documentElement.style.setProperty('--accent', p.color)
    document.documentElement.style.setProperty('--accent-rgb', p.rgb)
    document.documentElement.setAttribute('data-accent', key)
  }
}

function restorePreset() {
  const saved = localStorage.getItem('accent_preset')
  if (saved) {
    activePreset.value = saved
    const p = presets.find(p => p.key === saved)
    if (p) {
      document.documentElement.style.setProperty('--accent', p.color)
      document.documentElement.style.setProperty('--accent-rgb', p.rgb)
      document.documentElement.setAttribute('data-accent', saved)
    }
  }
}

// ── 主题切换（亮色/暗色）──
const currentTheme = ref('midnight')

function toggleTheme(theme: string) {
  currentTheme.value = theme
  localStorage.setItem('theme', theme)
  document.documentElement.setAttribute('data-theme', theme)
}

function restoreTheme() {
  const saved = localStorage.getItem('theme') || 'midnight'
  currentTheme.value = saved
  document.documentElement.setAttribute('data-theme', saved)
}

// ── 项目切换 ──
const projectName = computed(() =>
  projectStore.hasProject ? projectStore.projectTitle : ''
)

async function onProjectChange(e: Event) {
  const select = e.target as HTMLSelectElement
  const id = select.value
  if (!id) return
  await projectStore.loadProject(id)
  uiStore.showToast(`已切换到 ${projectStore.projectTitle}`, 'success')
}

// ── 模型开关 ──
const modelStatusText = computed(() => {
  if (systemStore.modelError) return '模型异常'
  if (systemStore.modelToggling) {
    return systemStore.modelRunning ? '正在停止...' : '正在启动...'
  }
  if (!systemStore.modelStatus) return '模型状态未知'
  return systemStore.modelRunning ? systemStore.modelName : '模型未运行'
})

async function onToggleModel() {
  await systemStore.toggleModel()
  uiStore.showToast(
    systemStore.modelRunning ? '模型已启动' : '模型已停止',
    systemStore.modelRunning ? 'success' : 'info'
  )
}

// click-outside 关闭硬件下拉
function onDocClick(e: MouseEvent) {
  if (hwRef.value && !hwRef.value.contains(e.target as Node)) {
    hwOpen.value = false
  }
}

// ── 生命周期 ──
onMounted(async () => {
  restorePreset()
  restoreTheme()
  document.addEventListener('click', onDocClick)
  await Promise.all([
    systemStore.fetchConfig(),
    systemStore.fetchModelStatus(),
    projectStore.loadProjects(),
    fetchHw(),
  ])
  systemStore.startPolling(10000)
  hwTimer = setInterval(fetchHw, 5000)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  systemStore.stopPolling()
  if (hwTimer) { clearInterval(hwTimer); hwTimer = null }
})
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <div class="brand-logo">番</div>
      <span class="brand-text">番茄小说 AI 辅助创作</span>
      <span class="version-badge">v{{ systemStore.version }}</span>
    </div>

    <div class="topbar-center">
      <select
        v-if="projectStore.projects.length > 0"
        class="project-select"
        :value="projectStore.currentProject?.id ?? ''"
        @change="onProjectChange"
        title="切换作品"
      >
        <option value="">切换作品</option>
        <option v-for="p in projectStore.projects" :key="p.id" :value="p.id">
          {{ p.title || '未命名' }}{{ p.is_demo ? ' (示例)' : '' }}
        </option>
      </select>
      <span v-if="projectName" class="topbar-project-name">{{ projectName }}</span>
    </div>

    <div class="topbar-right">
      <!-- 品牌色切换器 -->
      <div class="preset-switcher">
        <button
          v-for="p in presets"
          :key="p.key"
          class="preset-dot"
          :class="{ active: activePreset === p.key }"
          :style="{ background: p.color }"
          :title="p.label"
          @click="setPreset(p.key)"
        ></button>
      </div>

      <!-- 主题切换（亮色/暗色） -->
      <div class="theme-switcher" title="切换亮色/暗色主题">
        <button
          class="theme-dot"
          :class="{ active: currentTheme === 'midnight' }"
          data-theme="midnight"
          @click="toggleTheme('midnight')"
        ></button>
        <button
          class="theme-dot"
          :class="{ active: currentTheme === 'light' }"
          data-theme="light"
          @click="toggleTheme('light')"
        ></button>
      </div>

      <!-- 硬件监控 -->
      <div class="hw-monitor" ref="hwRef">
        <button class="hw-pill" :class="hwStatusClass()" @click="hwOpen = !hwOpen">
          <span class="hw-dot"></span>
          <span class="hw-text">{{ hwLabel() }}</span>
          <svg class="hw-chevron" :class="{ open: hwOpen }" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        <div class="hw-dropdown" :class="{ open: hwOpen }">
          <div class="hw-dropdown-header">
            <span class="hw-dropdown-title">硬件监控</span>
            <span class="hw-dropdown-subtitle">RTX 5060 8GB</span>
          </div>
          <div class="hw-dropdown-body">
            <div class="hw-metric" v-if="hw?.gpu">
              <span class="hw-key">GPU</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar"><span :class="hw.gpu.temp > 75 ? 'hw-bar-fill warn' : 'hw-bar-fill'" :style="{ width: (hw.gpu.temp / 100 * 100) + '%' }"></span></div>
              </div>
              <span class="hw-value">{{ hw.gpu.temp }}°C</span>
            </div>
            <div class="hw-metric" v-if="hw?.gpu">
              <span class="hw-key">显存</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar"><span :class="hw.gpu.vram_pct > 80 ? 'hw-bar-fill warn' : 'hw-bar-fill'" :style="{ width: hw.gpu.vram_pct + '%' }"></span></div>
              </div>
              <span class="hw-value">{{ hw.gpu.vram_pct }}%</span>
            </div>
            <div class="hw-metric" v-if="hw?.ram">
              <span class="hw-key">内存</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar"><span :class="hw.ram.pct > 80 ? 'hw-bar-fill warn' : 'hw-bar-fill'" :style="{ width: hw.ram.pct + '%' }"></span></div>
              </div>
              <span class="hw-value">{{ hw.ram.pct }}%</span>
            </div>
            <div class="hw-metric" v-if="hw?.cpu">
              <span class="hw-key">CPU</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar"><span :class="hw.cpu.pct > 80 ? 'hw-bar-fill warn' : 'hw-bar-fill'" :style="{ width: hw.cpu.pct + '%' }"></span></div>
              </div>
              <span class="hw-value">{{ Math.round(hw.cpu.pct) }}%</span>
            </div>
          </div>
          <div class="hw-dropdown-footer">
            <button class="btn btn-ghost btn-sm" style="width:100%;" @click="hwOpen = false; $router.push('/hardware')">
              查看完整监控 →
            </button>
          </div>
        </div>
      </div>

      <!-- 模型状态 -->
      <div
        class="model-pill"
        :class="{
          'status-error': !!systemStore.modelError,
          'status-online': !systemStore.modelError && systemStore.modelRunning,
          'status-offline': !systemStore.modelError && !systemStore.modelRunning
        }"
        :title="systemStore.modelRunning ? '点击停止模型' : '点击启动模型'"
      >
        <span class="model-dot" :class="{ active: systemStore.modelRunning }"></span>
        <span class="model-text">{{ modelStatusText }}</span>
        <button
          class="model-toggle-btn"
          :class="{ running: systemStore.modelRunning }"
          :disabled="systemStore.modelToggling"
          @click="onToggleModel"
        >
          <svg v-if="systemStore.modelRunning" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
          <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--topbar-height);
  padding: 0 16px;
  background: var(--topbar-glass);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  gap: 12px;
  z-index: 50;
}
@supports not (backdrop-filter: blur(12px)) {
  .topbar { background: var(--surface-solid); }
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: linear-gradient(135deg, var(--accent), var(--brand-lavender));
  color: white;
  font-weight: 700;
  font-size: 16px;
  display: grid;
  place-items: center;
}

.brand-text {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: var(--text);
  white-space: nowrap;
}

.version-badge {
  font-size: 11px;
  color: var(--text-secondary);
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--surface);
  border: 1px solid var(--border);
}

/* ── 中间区域 ── */
.topbar-center {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  justify-content: center;
  min-width: 0;
}

.project-select {
  height: 28px;
  padding: 0 8px;
  font-size: 12px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  outline: none;
  max-width: 200px;
  transition: border-color 0.15s;
}
.project-select:hover, .project-select:focus { border-color: var(--accent); }

.topbar-project-name {
  font-size: 13px;
  color: var(--text-secondary);
  padding: 2px 8px;
  background: var(--surface);
  border-radius: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 160px;
}

/* ── 右侧区域 ── */
.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

/* 品牌色切换器 */
.preset-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
}

.preset-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid var(--border);
  cursor: pointer;
  opacity: 0.6;
  padding: 0;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s, opacity 0.15s;
}

.preset-dot:hover { transform: scale(1.12); opacity: 0.85; }

.preset-dot.active {
  opacity: 1;
  border-color: var(--text);
  box-shadow: 0 0 0 1px var(--bg), 0 0 0 3px var(--accent), 0 0 12px rgba(var(--accent-rgb), 0.45);
  transform: scale(1.15);
}

/* 主题切换 */
.theme-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
}

.theme-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid var(--border);
  cursor: pointer;
  padding: 0;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
}

.theme-dot[data-theme="midnight"] { background: var(--brand-serene); }
.theme-dot[data-theme="light"]    { background: #f8fafc; }

.theme-dot:hover { transform: scale(1.12); }

.theme-dot.active {
  border-color: var(--text);
  box-shadow: 0 0 0 1px var(--bg);
  transform: scale(1.15);
}

/* 硬件监控 */
.hw-monitor { position: relative; }

.hw-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px 4px 8px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.hw-pill:hover { background: var(--surface-hover); border-color: var(--border-hover); color: var(--text); }
.hw-pill.status-warn { color: var(--warning); border-color: rgba(var(--warning-rgb), 0.4); }
.hw-pill.status-danger { color: var(--danger); border-color: rgba(var(--danger-rgb), 0.45); background: rgba(var(--danger-rgb), 0.08); }

.hw-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--success); box-shadow: 0 0 0 2px rgba(var(--success-rgb), 0.25);
}
.hw-pill.status-warn .hw-dot { background: var(--warning); box-shadow: 0 0 0 2px rgba(var(--warning-rgb), 0.25); }
.hw-pill.status-danger .hw-dot { background: var(--danger); box-shadow: 0 0 0 2px rgba(var(--danger-rgb), 0.25); animation: hw-pulse 1.2s ease-in-out infinite; }

@keyframes hw-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }

.hw-chevron { transition: transform 0.2s; }
.hw-chevron.open { transform: rotate(180deg); }

.hw-dropdown {
  position: absolute; top: calc(100% + 8px); right: 0; width: 220px;
  background: var(--surface-solid); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: 0 8px 32px rgba(0,0,0,0.35);
  opacity: 0; transform: translateY(-6px); pointer-events: none;
  transition: opacity 0.18s, transform 0.18s; z-index: 100;
}
.hw-dropdown.open { opacity: 1; transform: translateY(0); pointer-events: auto; }

.hw-dropdown-header {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 10px 12px 6px; border-bottom: 1px solid var(--border);
}
.hw-dropdown-title { font-size: 13px; font-weight: 600; color: var(--text); }
.hw-dropdown-subtitle { font-size: 11px; color: var(--text-secondary); }

.hw-dropdown-body { padding: 8px 12px; display: flex; flex-direction: column; gap: 8px; }

.hw-metric { display: flex; align-items: center; gap: 8px; }
.hw-key { width: 32px; font-size: 11px; color: var(--text-secondary); flex-shrink: 0; }
.hw-bar-wrap { flex: 1; }
.hw-bar { height: 4px; border-radius: 2px; background: var(--surface); overflow: hidden; }
.hw-bar-fill { display: block; height: 100%; border-radius: 2px; background: var(--success); transition: width 0.5s ease; }
.hw-bar-fill.warn { background: var(--warning); }
.hw-value { width: 38px; font-size: 11px; color: var(--text-secondary); text-align: right; flex-shrink: 0; }

.hw-dropdown-footer {
  padding: 8px 12px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
}

/* 模型状态 */
.model-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  background: rgba(var(--warning-rgb), 0.08);
  border: 1px solid rgba(var(--warning-rgb), 0.35);
  color: var(--warning);
  transition: all 0.2s;
}
.model-pill.status-online {
  background: rgba(var(--success-rgb), 0.08);
  border-color: rgba(var(--success-rgb), 0.35);
  color: var(--success);
}
.model-pill.status-offline {
  background: rgba(var(--warning-rgb), 0.08);
  border-color: rgba(var(--warning-rgb), 0.35);
  color: var(--warning);
}
.model-pill.status-error {
  background: rgba(var(--danger-rgb), 0.08);
  border-color: rgba(var(--danger-rgb), 0.35);
  color: var(--danger);
}

.model-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--warning); transition: background 0.2s;
}
.model-dot.active {
  background: var(--success);
  box-shadow: 0 0 0 2px rgba(var(--success-rgb), 0.25);
  animation: pulse 2s ease-in-out infinite;
}
.status-error .model-dot {
  background: var(--danger);
  box-shadow: 0 0 0 2px rgba(var(--danger-rgb), 0.25);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }

.model-text { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.model-toggle-btn {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; padding: 0; border-radius: 50%;
  background: var(--surface); border: 1px solid var(--border);
  color: var(--text-secondary); cursor: pointer;
  transition: all 0.2s ease; flex-shrink: 0;
}
.model-toggle-btn:hover:not(:disabled) {
  border-color: var(--accent); color: var(--accent);
  background: rgba(var(--accent-rgb), 0.08);
}
.model-toggle-btn.running {
  border-color: var(--success); color: var(--success);
  background: rgba(var(--success-rgb), 0.08);
}
.model-toggle-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── 响应式 ── */
@media (max-width: 768px) {
  .brand-text { display: none; }
  .topbar-center { justify-content: flex-start; }
  .project-select { max-width: 120px; }
  .preset-switcher { display: none; }
}
</style>