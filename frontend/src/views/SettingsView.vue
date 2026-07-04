<script setup lang="ts">
/**
 * SettingsView — 设置页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - 双模型配置（主模型+交叉审查模型）
 * - 生成参数（上下文/温度/Top-p/KV Cache）
 * - 编辑器设置（字号/行高/自动保存）
 * - 管线设置（自动入库/拆书/并行数）
 * - 快捷键说明
 * - 数据管理 + 导出/重置
 */
import { ref, onMounted } from 'vue'
import { useUiStore } from '@/stores/ui'
import { DashboardAPI, type ConfigData } from '@/api/dashboard'
import PromptTemplateManager from '@/components/settings/PromptTemplateManager.vue'

const uiStore = useUiStore()

// ── 设置状态 (localStorage 持久化) ──
const settings = ref({
  localModel: '',
  localEndpoint: 'http://localhost:8000',
  crossModel: 'DeepSeek-R1-0528',
  crossEndpoint: 'http://localhost:8002',
  cloudModel: '',
  ctx: 8192,
  temperature: 0.7,
  topP: 0.9,
  kvCache: 'q4',
  swapStrategy: 'vram70',
  fontSize: 18,
  lineHeight: 1.9,
  paragraphGap: 0,
  autoSaveInterval: '60',
  targetWords: 2000,
  typewriter: false,
  autoImport: true,
  autoRhythm: true,
  showHwMonitor: true,
  parallelism: '2',
  s3Strictness: 'normal',
  cacheTtl: '7',
  dataDir: '',
})

const config = ref<ConfigData | null>(null)

// ── 品牌色预设 ──
const presets = [
  { key: 'serene', label: '静谧蓝', color: '#38BDF8', rgb: '56,189,248' },
  { key: 'arctic', label: '极光青', color: '#22D3EE', rgb: '34,211,238' },
  { key: 'lavender', label: '薰衣草', color: '#A78BFA', rgb: '167,139,250' },
  { key: 'aurora', label: '极光靛', color: '#818CF8', rgb: '129,140,248' },
]
const activePreset = ref('serene')

// ── 快捷键列表 ──
const shortcuts = [
  { action: '保存', key: 'Ctrl+S' },
  { action: '专注模式', key: 'Ctrl+B' },
  { action: '上一章', key: 'Ctrl+[' },
  { action: '下一章', key: 'Ctrl+]' },
  { action: 'AI指纹检测', key: 'Ctrl+Shift+A' },
  { action: 'AI辅助面板', key: 'Ctrl+Shift+P' },
  { action: '自检面板', key: 'Ctrl+Shift+C' },
]

// ── 方法 ──
function saveSetting(key: string, value: string | number | boolean) {
  try {
    localStorage.setItem('setting_' + key, String(value))
  } catch (e) { /* ignore */ }
}

function onTextInput(key: string, event: Event) {
  const value = (event.target as HTMLInputElement).value
  saveSetting(key, value)
  uiStore.showToast('已保存 ' + key, 'success')
}

function onNumberInput(key: string, event: Event) {
  const value = (event.target as HTMLInputElement).value
  saveSetting(key, value)
}

function onToggle(key: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  saveSetting(key, checked)
  uiStore.showToast(`${checked ? '已开启' : '已关闭'} ${key}`, 'info')
}

function setAccentPreset(key: string) {
  activePreset.value = key
  localStorage.setItem('accent_preset', key)
  // 应用到 CSS 变量 + data-accent 属性（驱动品牌色氛围系统）
  const preset = presets.find((p) => p.key === key)
  if (preset) {
    document.documentElement.style.setProperty('--accent', preset.color)
    document.documentElement.style.setProperty('--accent-rgb', preset.rgb)
    document.documentElement.setAttribute('data-accent', key)
  }
  uiStore.showToast(`已切换到 ${preset?.label}`, 'success')
}

function exportSettings() {
  try {
    const data: Record<string, string> = {}
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith('setting_')) data[k] = localStorage.getItem(k) || ''
    }
    data['accent_preset'] = activePreset.value
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `fanqie-settings-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(a.href)
    uiStore.showToast('配置已导出', 'success')
  } catch (e) {
    uiStore.showToast('导出失败', 'error')
  }
}

function resetSettings() {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (k && (k.startsWith('setting_') || k === 'accent_preset')) keys.push(k)
  }
  keys.forEach((k) => localStorage.removeItem(k))
  // 重置到默认值
  settings.value = {
    localModel: '',
    localEndpoint: 'http://localhost:8000',
    crossModel: 'DeepSeek-R1-0528',
    crossEndpoint: 'http://localhost:8002',
    cloudModel: '',
    ctx: 8192, temperature: 0.7, topP: 0.9,
    kvCache: 'q4', swapStrategy: 'vram70',
    fontSize: 18, lineHeight: 1.9, paragraphGap: 0,
    autoSaveInterval: '60', targetWords: 2000, typewriter: false,
    autoImport: true, autoRhythm: true, showHwMonitor: true,
    parallelism: '2', s3Strictness: 'normal', cacheTtl: '7', dataDir: '',
  }
  setAccentPreset('serene')
  uiStore.showToast('偏好已重置', 'info')
}

// ── 从 localStorage 恢复 ──
function restoreFromStorage() {
  const get = (key: string) => localStorage.getItem('setting_' + key)
  const s = settings.value
  s.localModel = get('localModel') || s.localModel
  s.localEndpoint = get('localEndpoint') || s.localEndpoint
  s.crossModel = get('crossModel') || s.crossModel
  s.crossEndpoint = get('crossEndpoint') || s.crossEndpoint
  s.dataDir = get('dataDir') || s.dataDir
  const ctx = get('ctx'); if (ctx) s.ctx = parseInt(ctx)
  const temp = get('temperature'); if (temp) s.temperature = parseFloat(temp)
  const topP = get('topP'); if (topP) s.topP = parseFloat(topP)
  const kv = get('kvCache'); if (kv) s.kvCache = kv
  const swap = get('swapStrategy'); if (swap) s.swapStrategy = swap
  const fs = get('fontSize'); if (fs) s.fontSize = parseInt(fs)
  const lh = get('lineHeight'); if (lh) s.lineHeight = parseFloat(lh)
  const pg = get('paragraphGap'); if (pg) s.paragraphGap = parseInt(pg)
  const asv = get('autoSaveInterval'); if (asv) s.autoSaveInterval = asv
  const tw = get('targetWords'); if (tw) s.targetWords = parseInt(tw)
  const tw_mode = get('typewriter'); if (tw_mode !== null) s.typewriter = tw_mode === '1'
  const ai = get('auto-import'); if (ai !== null) s.autoImport = ai === '1'
  const ar = get('auto-rhythm'); if (ar !== null) s.autoRhythm = ar === '1'
  const hw = get('show-hw-monitor'); if (hw !== null) s.showHwMonitor = hw === '1'
  const par = get('parallelism'); if (par) s.parallelism = par
  const s3 = get('s3Strictness'); if (s3) s.s3Strictness = s3
  const ct = get('cacheTtl'); if (ct) s.cacheTtl = ct
  const preset = localStorage.getItem('accent_preset')
  if (preset) {
    activePreset.value = preset
    const p = presets.find((p) => p.key === preset)
    if (p) {
      document.documentElement.style.setProperty('--accent', p.color)
      document.documentElement.style.setProperty('--accent-rgb', p.rgb)
      document.documentElement.setAttribute('data-accent', preset)
    }
  }
}

onMounted(async () => {
  restoreFromStorage()
  // 从后端加载配置
  const res = await DashboardAPI.getConfig()
  if (res.ok && res.data) {
    config.value = res.data
    // 仅当用户未手动覆盖时更新
    if (!localStorage.getItem('setting_localModel') && res.data.local_model) {
      settings.value.localModel = res.data.local_model
    }
    if (!localStorage.getItem('setting_cloudModel') && res.data.cloud_model) {
      settings.value.cloudModel = res.data.cloud_model + (res.data.cloud_provider ? ` (${res.data.cloud_provider})` : '')
    }
  }
})
</script>

<template>
  <div class="settings-page">
    <div class="page-header">
      <h2>设置</h2>
    </div>

    <div class="settings-grid">
      <!-- 双模型配置 -->
      <div class="settings-card">
        <div class="settings-title">
          <span class="settings-dot" style="background: var(--accent)" />
          双模型配置
        </div>
        <div class="settings-subtitle">主模型</div>
        <label class="settings-row settings-row-stack">
          <span>模型名</span>
          <input type="text" class="settings-input" v-model="settings.localModel" @change="onTextInput('localModel', $event)" />
        </label>
        <label class="settings-row settings-row-stack">
          <span>端点</span>
          <input type="text" class="settings-input" v-model="settings.localEndpoint" @change="onTextInput('localEndpoint', $event)" />
        </label>
        <div class="settings-subtitle">交叉审查模型</div>
        <label class="settings-row settings-row-stack">
          <span>模型名</span>
          <input type="text" class="settings-input" v-model="settings.crossModel" @change="onTextInput('crossModel', $event)" />
        </label>
        <label class="settings-row settings-row-stack">
          <span>端点</span>
          <input type="text" class="settings-input" v-model="settings.crossEndpoint" @change="onTextInput('crossEndpoint', $event)" />
        </label>
      </div>

      <!-- 生成参数 -->
      <div class="settings-card">
        <div class="settings-title">生成参数</div>
        <label class="settings-row">
          <span>最大上下文</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.ctx" step="1024" @change="onNumberInput('ctx', $event)" />
        </label>
        <label class="settings-row">
          <span>温度 (Temperature)</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.temperature" step="0.1" min="0" max="2" @change="onNumberInput('temperature', $event)" />
        </label>
        <label class="settings-row">
          <span>Top-p</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.topP" step="0.05" min="0" max="1" @change="onNumberInput('topP', $event)" />
        </label>
        <label class="settings-row">
          <span>KV Cache 量化</span>
          <select class="settings-input" v-model="settings.kvCache" @change="onTextInput('kvCache', $event)">
            <option value="none">无</option>
            <option value="q4">Q4 非对称</option>
            <option value="q8">Q8</option>
          </select>
        </label>
        <label class="settings-row">
          <span>切换策略</span>
          <select class="settings-input" v-model="settings.swapStrategy" @change="onTextInput('swapStrategy', $event)">
            <option value="manual">手动</option>
            <option value="vram70">VRAM > 70% 自动 swap_to</option>
            <option value="always">始终交叉审查</option>
          </select>
        </label>
      </div>

      <!-- 编辑器设置 -->
      <div class="settings-card">
        <div class="settings-title">编辑器设置</div>
        <label class="settings-row">
          <span>字体大小</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.fontSize" @change="onNumberInput('fontSize', $event)" />
        </label>
        <label class="settings-row">
          <span>行高</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.lineHeight" step="0.1" @change="onNumberInput('lineHeight', $event)" />
        </label>
        <label class="settings-row">
          <span>段落间距</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.paragraphGap" @change="onNumberInput('paragraphGap', $event)" />
        </label>
        <label class="settings-row">
          <span>自动保存间隔</span>
          <select class="settings-input" v-model="settings.autoSaveInterval" @change="onTextInput('autoSaveInterval', $event)">
            <option value="0">关闭</option>
            <option value="30">30 秒</option>
            <option value="60">60 秒</option>
            <option value="300">5 分钟</option>
          </select>
        </label>
        <label class="settings-row">
          <span>目标字数提醒</span>
          <input type="number" class="settings-input settings-input-sm" v-model.number="settings.targetWords" step="500" @change="onNumberInput('targetWords', $event)" />
        </label>
        <label class="settings-row">
          <span>打字机模式</span>
          <input type="checkbox" v-model="settings.typewriter" @change="onToggle('typewriter', $event)" />
        </label>
      </div>

      <!-- 品牌色 -->
      <div class="settings-card">
        <div class="settings-title">品牌色（强调色）</div>
        <div class="settings-row">
          <span>当前预设</span>
          <span>{{ presets.find(p => p.key === activePreset)?.label || '静谧蓝' }}</span>
        </div>
        <div class="preset-switcher">
          <button
            v-for="p in presets"
            :key="p.key"
            class="preset-dot"
            :class="{ active: activePreset === p.key }"
            :style="{ background: p.color }"
            :aria-label="p.label"
            @click="setAccentPreset(p.key)"
          />
        </div>
      </div>

      <!-- 管线设置 -->
      <div class="settings-card">
        <div class="settings-title">管线设置</div>
        <label class="settings-row">
          <span>自动入库</span>
          <input type="checkbox" v-model="settings.autoImport" @change="onToggle('auto-import', $event)" />
        </label>
        <label class="settings-row">
          <span>拆书分析</span>
          <input type="checkbox" v-model="settings.autoRhythm" @change="onToggle('auto-rhythm', $event)" />
        </label>
        <label class="settings-row">
          <span>顶部显示硬件状态</span>
          <input type="checkbox" v-model="settings.showHwMonitor" @change="onToggle('show-hw-monitor', $event)" />
        </label>
        <label class="settings-row">
          <span>拆书并行数</span>
          <select class="settings-input" v-model="settings.parallelism" @change="onTextInput('parallelism', $event)">
            <option value="1">1 本</option>
            <option value="2">2 本</option>
            <option value="4">4 本</option>
          </select>
        </label>
        <label class="settings-row">
          <span>S3 评审严格度</span>
          <select class="settings-input" v-model="settings.s3Strictness" @change="onTextInput('s3Strictness', $event)">
            <option value="loose">宽松</option>
            <option value="normal">标准</option>
            <option value="strict">严格</option>
          </select>
        </label>
        <label class="settings-row">
          <span>缓存保留时长</span>
          <select class="settings-input" v-model="settings.cacheTtl" @change="onTextInput('cacheTtl', $event)">
            <option value="1">1 本</option>
            <option value="7">7 分</option>
            <option value="30">30 秒</option>
          </select>
        </label>
      </div>

      <!-- 快捷键 -->
      <div class="settings-card">
        <div class="settings-title">快捷键</div>
        <div v-for="sc in shortcuts" :key="sc.action" class="settings-row">
          <span>{{ sc.action }}</span>
          <kbd>{{ sc.key }}</kbd>
        </div>
      </div>

      <!-- 数据管理 -->
      <div class="settings-card">
        <div class="settings-title">数据管理</div>
        <div class="settings-row">
          <span>数据目录</span>
          <span class="text-muted">{{ config?.version ? `v${config.version}` : '-' }}</span>
        </div>
        <div class="settings-row">
          <span>默认题材</span>
          <span class="text-muted">{{ config?.genre || '末世' }}</span>
        </div>
        <div class="settings-row">
          <span>运行模式</span>
          <span class="text-muted">{{ config?.mode || 'local' }}</span>
        </div>
        <div class="settings-row">
          <span>LLM 端口</span>
          <span class="text-muted">{{ config?.llm_port || 8000 }}</span>
        </div>
        <div class="settings-actions" style="margin-top: 12px;">
          <button class="btn btn-secondary btn-sm" @click="exportSettings">导出配置</button>
          <button class="btn btn-ghost btn-sm" @click="resetSettings">重置偏好</button>
        </div>
      </div>

      <!-- 提示词模板管理 -->
      <PromptTemplateManager />
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  padding: 16px 24px;
  height: 100%;
  overflow-y: auto;
}
.page-header {
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 18px;
  font-weight: 600;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.settings-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}

.settings-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.settings-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.settings-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 10px 0 6px;
}

.settings-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
  gap: 12px;
}
.settings-row-stack {
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}
.settings-row-stack span {
  font-size: 11px;
  color: var(--text-secondary);
}

.settings-input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  width: 100%;
}
.settings-input:focus {
  outline: none;
  border-color: var(--accent);
}
.settings-input-sm {
  width: 80px;
}

.settings-row input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}

.preset-switcher {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}
.preset-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.preset-dot.active {
  border-color: white;
  box-shadow: 0 0 0 2px var(--accent);
}

kbd {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface-solid);
  color: var(--text-secondary);
  font-family: monospace;
}

.text-muted {
  color: var(--text-secondary);
}

.settings-actions {
  display: flex;
  gap: 8px;
}

/* ── 按钮 — 全局 style.css 接管 ── */

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
