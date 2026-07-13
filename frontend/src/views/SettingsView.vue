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
import { SettingsAPI, type SettingsMap } from '@/api/settings'
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

const sections = [
  { id: 'models', label: '双模型配置', icon: 'M2 3h20v14H2zM8 21h8M12 17v4' },
  { id: 'generation', label: '生成参数', icon: 'M12 1v22M1 12h22' },
  { id: 'editor', label: '编辑器', icon: 'M12 20h9M16.5 3.5 7 19l-4 1 1-4L16.5 3.5z' },
  { id: 'brand', label: '品牌色', icon: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z' },
  { id: 'pipeline', label: '管线', icon: 'M22 12h-4l-3 9L9 3l-3 9H2' },
  { id: 'shortcuts', label: '快捷键', icon: 'M4 7h16M4 12h16M4 17h16' },
  { id: 'data', label: '数据管理', icon: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z' },
]

// ── 方法 ──
async function saveSetting(key: string, value: string | number | boolean) {
  try {
    localStorage.setItem('setting_' + key, String(value))
  } catch (e) { /* ignore */ }
  // 同步到后端
  const payload: SettingsMap = {}
  for (const [k, v] of Object.entries(settings.value)) {
    payload[k] = v
  }
  await SettingsAPI.save(payload)
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

async function setAccentPreset(key: string) {
  activePreset.value = key
  localStorage.setItem('accent_preset', key)
  // 应用到 CSS 变量 + data-accent 属性（驱动品牌色氛围系统）
  const preset = presets.find((p) => p.key === key)
  if (preset) {
    document.documentElement.style.setProperty('--accent', preset.color)
    document.documentElement.style.setProperty('--accent-rgb', preset.rgb)
    document.documentElement.setAttribute('data-accent', key)
  }
  // 同步到后端
  const payload: SettingsMap = {}
  for (const [k, v] of Object.entries(settings.value)) {
    payload[k] = v
  }
  payload.accent_preset = key
  await SettingsAPI.save(payload)
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

async function resetSettings() {
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
  await SettingsAPI.save({})
  await setAccentPreset('serene')
  uiStore.showToast('偏好已重置', 'info')
}

// ── 从后端加载设置（以 localStorage 为缓存兜底） ──
async function loadSettings() {
  const backend = await SettingsAPI.get()
  const remote: SettingsMap = backend.ok && backend.data ? backend.data : {}
  const get = (key: string): unknown => {
    const local = localStorage.getItem('setting_' + key)
    return local ?? remote[key] ?? null
  }

  const toStr = (v: unknown) => (v == null ? '' : String(v))
  const toInt = (v: unknown) => parseInt(toStr(v), 10)
  const toFloat = (v: unknown) => parseFloat(toStr(v))
  const toBool = (v: unknown) => v === true || v === 'true' || v === '1' || v === 1

  const s = settings.value
  s.localModel = toStr(get('localModel')) || s.localModel
  s.localEndpoint = toStr(get('localEndpoint')) || s.localEndpoint
  s.crossModel = toStr(get('crossModel')) || s.crossModel
  s.crossEndpoint = toStr(get('crossEndpoint')) || s.crossEndpoint
  s.dataDir = toStr(get('dataDir')) || s.dataDir
  const ctx = get('ctx'); if (ctx != null) s.ctx = toInt(ctx)
  const temp = get('temperature'); if (temp != null) s.temperature = toFloat(temp)
  const topP = get('topP'); if (topP != null) s.topP = toFloat(topP)
  const kv = get('kvCache'); if (kv != null) s.kvCache = toStr(kv)
  const swap = get('swapStrategy'); if (swap != null) s.swapStrategy = toStr(swap)
  const fs = get('fontSize'); if (fs != null) s.fontSize = toInt(fs)
  const lh = get('lineHeight'); if (lh != null) s.lineHeight = toFloat(lh)
  const pg = get('paragraphGap'); if (pg != null) s.paragraphGap = toInt(pg)
  const asv = get('autoSaveInterval'); if (asv != null) s.autoSaveInterval = toStr(asv)
  const tw = get('targetWords'); if (tw != null) s.targetWords = toInt(tw)
  const tw_mode = get('typewriter'); if (tw_mode != null) s.typewriter = toBool(tw_mode)
  const ai = get('autoImport'); if (ai != null) s.autoImport = toBool(ai)
  const ar = get('autoRhythm'); if (ar != null) s.autoRhythm = toBool(ar)
  const hw = get('showHwMonitor'); if (hw != null) s.showHwMonitor = toBool(hw)
  const par = get('parallelism'); if (par != null) s.parallelism = toStr(par)
  const s3 = get('s3Strictness'); if (s3 != null) s.s3Strictness = toStr(s3)
  const ct = get('cacheTtl'); if (ct != null) s.cacheTtl = toStr(ct)

  const preset = localStorage.getItem('accent_preset') || (remote.accent_preset as string)
  if (preset) {
    activePreset.value = preset
    const p = presets.find((p) => p.key === preset)
    if (p) {
      document.documentElement.style.setProperty('--accent', p.color)
      document.documentElement.style.setProperty('--accent-rgb', p.rgb)
      document.documentElement.setAttribute('data-accent', preset)
    }
  }

  // 首次加载成功后将后端数据写回 localStorage 做缓存
  if (backend.ok && backend.data) {
    for (const [k, v] of Object.entries(backend.data)) {
      if (v !== null && v !== undefined) {
        localStorage.setItem('setting_' + k, String(v))
      }
    }
  }
}

onMounted(async () => {
  await loadSettings()
  // 从后端加载系统配置
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
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-title">
        <h2>设置</h2>
        <span class="page-subtitle">模型、编辑器与系统偏好</span>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" @click="exportSettings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          导出配置
        </button>
        <button class="btn btn-ghost btn-sm" @click="resetSettings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          重置偏好
        </button>
      </div>
    </div>

    <div class="settings-layout">
      <!-- 左侧导航 -->
      <nav class="settings-nav">
        <a v-for="section in sections" :key="section.id" :href="'#' + section.id" class="nav-item">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path :d="section.icon"/></svg>
          {{ section.label }}
        </a>
      </nav>

      <!-- 右侧内容 -->
      <div class="settings-content">
        <!-- 双模型配置 -->
        <section id="models" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <div>
              <h3 class="section-title">双模型配置</h3>
              <p class="section-desc">主模型与交叉审查模型的端点配置</p>
            </div>
          </div>
          <div class="settings-card">
            <div class="card-subtitle">主模型</div>
            <div class="form-row two-col">
              <label class="form-field">
                <span class="field-label">模型名</span>
                <input type="text" class="settings-input" v-model="settings.localModel" @change="onTextInput('localModel', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">端点</span>
                <input type="text" class="settings-input" v-model="settings.localEndpoint" @change="onTextInput('localEndpoint', $event)" />
              </label>
            </div>
            <div class="card-subtitle">交叉审查模型</div>
            <div class="form-row two-col">
              <label class="form-field">
                <span class="field-label">模型名</span>
                <input type="text" class="settings-input" v-model="settings.crossModel" @change="onTextInput('crossModel', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">端点</span>
                <input type="text" class="settings-input" v-model="settings.crossEndpoint" @change="onTextInput('crossEndpoint', $event)" />
              </label>
            </div>
          </div>
        </section>

        <!-- 生成参数 -->
        <section id="generation" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 6v6m4.22-10.22 4.24-4.24M6.34 6.34 2.1 2.1m17.8 17.8-4.24-4.24M6.34 17.66l-4.24 4.24M23 12h-6m-6 0H1m20.07-4.93-4.24 4.24M6.34 6.34l-4.24-4.24"/></svg>
            </div>
            <div>
              <h3 class="section-title">生成参数</h3>
              <p class="section-desc">控制大模型输出的采样与量化策略</p>
            </div>
          </div>
          <div class="settings-card">
            <div class="form-row three-col">
              <label class="form-field">
                <span class="field-label">最大上下文</span>
                <input type="number" class="settings-input" v-model.number="settings.ctx" step="1024" @change="onNumberInput('ctx', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">温度 (Temperature)</span>
                <input type="number" class="settings-input" v-model.number="settings.temperature" step="0.1" min="0" max="2" @change="onNumberInput('temperature', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">Top-p</span>
                <input type="number" class="settings-input" v-model.number="settings.topP" step="0.05" min="0" max="1" @change="onNumberInput('topP', $event)" />
              </label>
            </div>
            <div class="form-row two-col">
              <label class="form-field">
                <span class="field-label">KV Cache 量化</span>
                <select class="settings-input" v-model="settings.kvCache" @change="onTextInput('kvCache', $event)">
                  <option value="none">无</option>
                  <option value="q4">Q4 非对称</option>
                  <option value="q8">Q8</option>
                </select>
              </label>
              <label class="form-field">
                <span class="field-label">切换策略</span>
                <select class="settings-input" v-model="settings.swapStrategy" @change="onTextInput('swapStrategy', $event)">
                  <option value="manual">手动</option>
                  <option value="vram70">VRAM > 70% 自动 swap_to</option>
                  <option value="always">始终交叉审查</option>
                </select>
              </label>
            </div>
          </div>
        </section>

        <!-- 编辑器设置 -->
        <section id="editor" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            </div>
            <div>
              <h3 class="section-title">编辑器设置</h3>
              <p class="section-desc">写作界面的版式与行为</p>
            </div>
          </div>
          <div class="settings-card">
            <div class="form-row four-col">
              <label class="form-field">
                <span class="field-label">字体大小</span>
                <input type="number" class="settings-input" v-model.number="settings.fontSize" @change="onNumberInput('fontSize', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">行高</span>
                <input type="number" class="settings-input" v-model.number="settings.lineHeight" step="0.1" @change="onNumberInput('lineHeight', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">段落间距</span>
                <input type="number" class="settings-input" v-model.number="settings.paragraphGap" @change="onNumberInput('paragraphGap', $event)" />
              </label>
              <label class="form-field">
                <span class="field-label">目标字数提醒</span>
                <input type="number" class="settings-input" v-model.number="settings.targetWords" step="500" @change="onNumberInput('targetWords', $event)" />
              </label>
            </div>
            <div class="form-row two-col">
              <label class="form-field">
                <span class="field-label">自动保存间隔</span>
                <select class="settings-input" v-model="settings.autoSaveInterval" @change="onTextInput('autoSaveInterval', $event)">
                  <option value="0">关闭</option>
                  <option value="30">30 秒</option>
                  <option value="60">60 秒</option>
                  <option value="300">5 分钟</option>
                </select>
              </label>
              <div class="form-field inline">
                <span class="field-label">打字机模式</span>
                <label class="toggle">
                  <input type="checkbox" v-model="settings.typewriter" @change="onToggle('typewriter', $event)" />
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>
          </div>
        </section>

        <!-- 品牌色 -->
        <section id="brand" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r="2.5"/><path d="M13.5 9c-3.5 0-6.5 2.5-6.5 6.5 0 1.5.5 2.8 1.3 3.8L4 21l1.7-4.3c1-1 2.3-1.5 3.8-1.5 4 0 6.5-3 6.5-6.5z"/></svg>
            </div>
            <div>
              <h3 class="section-title">品牌色</h3>
              <p class="section-desc">选择界面强调色</p>
            </div>
          </div>
          <div class="settings-card">
            <div class="brand-current">
              <span class="field-label">当前预设</span>
              <span class="brand-label">{{ presets.find(p => p.key === activePreset)?.label || '静谧蓝' }}</span>
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
              >
                <svg v-if="activePreset === p.key" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              </button>
            </div>
          </div>
        </section>

        <!-- 管线设置 -->
        <section id="pipeline" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            </div>
            <div>
              <h3 class="section-title">管线设置</h3>
              <p class="section-desc">自动化任务与资源控制</p>
            </div>
          </div>
          <div class="settings-card">
            <div class="form-row three-col toggles">
              <label class="toggle-field">
                <span class="toggle-label">自动入库</span>
                <span class="toggle-desc">新书自动加入书库</span>
                <label class="toggle">
                  <input type="checkbox" v-model="settings.autoImport" @change="onToggle('auto-import', $event)" />
                  <span class="toggle-slider"></span>
                </label>
              </label>
              <label class="toggle-field">
                <span class="toggle-label">拆书分析</span>
                <span class="toggle-desc">入库后自动拆书</span>
                <label class="toggle">
                  <input type="checkbox" v-model="settings.autoRhythm" @change="onToggle('auto-rhythm', $event)" />
                  <span class="toggle-slider"></span>
                </label>
              </label>
              <label class="toggle-field">
                <span class="toggle-label">顶部硬件状态</span>
                <span class="toggle-desc">在顶部栏显示监控</span>
                <label class="toggle">
                  <input type="checkbox" v-model="settings.showHwMonitor" @change="onToggle('show-hw-monitor', $event)" />
                  <span class="toggle-slider"></span>
                </label>
              </label>
            </div>
            <div class="form-row three-col">
              <label class="form-field">
                <span class="field-label">拆书并行数</span>
                <select class="settings-input" v-model="settings.parallelism" @change="onTextInput('parallelism', $event)">
                  <option value="1">1 本</option>
                  <option value="2">2 本</option>
                  <option value="4">4 本</option>
                </select>
              </label>
              <label class="form-field">
                <span class="field-label">S3 评审严格度</span>
                <select class="settings-input" v-model="settings.s3Strictness" @change="onTextInput('s3Strictness', $event)">
                  <option value="loose">宽松</option>
                  <option value="normal">标准</option>
                  <option value="strict">严格</option>
                </select>
              </label>
              <label class="form-field">
                <span class="field-label">缓存保留时长</span>
                <select class="settings-input" v-model="settings.cacheTtl" @change="onTextInput('cacheTtl', $event)">
                  <option value="1">1 天</option>
                  <option value="7">7 天</option>
                  <option value="30">30 天</option>
                </select>
              </label>
            </div>
          </div>
        </section>

        <!-- 快捷键 -->
        <section id="shortcuts" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="7" y1="7" x2="7" y2="7"/><line x1="12" y1="7" x2="12" y2="7"/><line x1="17" y1="7" x2="17" y2="7"/><line x1="7" y1="12" x2="7" y2="12"/><line x1="12" y1="12" x2="12" y2="12"/><line x1="17" y1="12" x2="17" y2="12"/><line x1="7" y1="17" x2="7" y2="17"/><line x1="12" y1="17" x2="12" y2="17"/><line x1="17" y1="17" x2="17" y2="17"/></svg>
            </div>
            <div>
              <h3 class="section-title">快捷键</h3>
              <p class="section-desc">常用操作的键盘映射</p>
            </div>
          </div>
          <div class="settings-card shortcuts-card">
            <div v-for="sc in shortcuts" :key="sc.action" class="shortcut-row">
              <span class="shortcut-action">{{ sc.action }}</span>
              <kbd>{{ sc.key }}</kbd>
            </div>
          </div>
        </section>

        <!-- 数据管理 -->
        <section id="data" class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
            </div>
            <div>
              <h3 class="section-title">数据管理</h3>
              <p class="section-desc">当前运行环境与配置信息</p>
            </div>
          </div>
          <div class="settings-card data-card">
            <div class="data-grid">
              <div class="data-item">
                <span class="data-label">版本</span>
                <span class="data-value">{{ config?.version ? `v${config.version}` : '-' }}</span>
              </div>
              <div class="data-item">
                <span class="data-label">默认题材</span>
                <span class="data-value">{{ config?.genre || '末世' }}</span>
              </div>
              <div class="data-item">
                <span class="data-label">运行模式</span>
                <span class="data-value">{{ config?.mode || 'local' }}</span>
              </div>
              <div class="data-item">
                <span class="data-label">LLM 端口</span>
                <span class="data-value">{{ config?.llm_port || 8000 }}</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 提示词模板管理 -->
        <section class="settings-section">
          <PromptTemplateManager />
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  padding: 24px;
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

.page-actions {
  display: flex;
  gap: 10px;
}

.page-actions .btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* ── 布局 ── */
.settings-layout {
  display: flex;
  gap: 24px;
}

.settings-nav {
  width: 180px;
  flex-shrink: 0;
  position: sticky;
  top: 16px;
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: var(--surface);
  border: 1px solid var(--border-hover);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.nav-item {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  transition: all 0.15s;
}

.nav-item:hover {
  background: var(--surface-hover);
  color: var(--text);
}

.nav-item:active,
.nav-item:focus-visible {
  background: rgba(var(--accent-rgb), 0.12);
  color: var(--accent);
  font-weight: 600;
}

.settings-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* ── 章节 ── */
.settings-section {
  scroll-margin-top: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.section-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  background: rgba(var(--accent-rgb), 0.1);
  flex-shrink: 0;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}

.section-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* ── 卡片 ── */
.settings-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.card-subtitle {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: 0.4px;
  margin-bottom: 12px;
}

.card-subtitle:not(:first-child) {
  margin-top: 20px;
}

/* ── 表单 ── */
.form-row {
  display: grid;
  gap: 16px;
  margin-bottom: 16px;
}

.form-row:last-child {
  margin-bottom: 0;
}

.form-row.two-col { grid-template-columns: repeat(2, 1fr); }
.form-row.three-col { grid-template-columns: repeat(3, 1fr); }
.form-row.four-col { grid-template-columns: repeat(4, 1fr); }

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field.inline {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.settings-input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  width: 100%;
  transition: all 0.15s;
}

.settings-input:focus {
  outline: none;
  border-color: var(--accent);
  background: var(--surface-solid);
}

/* ── 开关 ── */
.toggle {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--surface-faint);
  border: 1px solid var(--border);
  border-radius: 22px;
  transition: all 0.2s;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background: var(--text-secondary);
  border-radius: 50%;
  transition: all 0.2s;
}

.toggle input:checked + .toggle-slider {
  background: rgba(var(--accent-rgb), 0.2);
  border-color: var(--accent);
}

.toggle input:checked + .toggle-slider::before {
  transform: translateX(18px);
  background: var(--accent);
}

.toggle-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  position: relative;
}

.toggle-field .toggle {
  position: absolute;
  top: 14px;
  right: 14px;
}

.toggle-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  padding-right: 48px;
}

.toggle-desc {
  font-size: 11px;
  color: var(--text-muted);
  padding-right: 48px;
}

/* ── 品牌色 ── */
.brand-current {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.brand-label {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.preset-switcher {
  display: flex;
  gap: 12px;
}

.preset-dot {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preset-dot.active {
  border-color: rgba(var(--text-rgb), 0.9);
  box-shadow: 0 0 0 2px var(--accent);
}

/* ── 快捷键 ── */
.shortcuts-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.shortcut-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.shortcut-row:last-child {
  border-bottom: none;
}

.shortcut-action {
  color: var(--text-secondary);
}

kbd {
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-mono);
  font-weight: 600;
}

/* ── 数据管理 ── */
.data-card {
  padding: 16px 20px;
}

.data-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.data-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.data-label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.data-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .settings-layout {
    flex-direction: column;
  }
  .settings-nav {
    width: 100%;
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
  }
  .form-row.four-col { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 12px;
  }
  .form-row.two-col,
  .form-row.three-col,
  .form-row.four-col {
    grid-template-columns: 1fr;
  }
  .data-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
