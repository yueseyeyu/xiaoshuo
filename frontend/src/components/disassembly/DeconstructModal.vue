<script setup lang="ts">
/**
 * DeconstructModal — 小说解构结果模态框
 *
 * 从用户视角展示五段式解构结果：
 * 题材标签 / 结构拆解 / 人物拆解 / 可借鉴元素 / 避雷清单
 * 避免直接堆砌 JSON，优先展示可读文本、列表、关键字段卡片。
 */
import { ref, computed } from 'vue'
import { useUiStore } from '@/stores/ui'
import { CreativeAPI } from '@/api/creative'

const uiStore = useUiStore()

const show = defineModel<boolean>('show', { required: true })
const title = ref('')
const loading = ref(false)

interface DeconstructData {
  genre_tags?: Record<string, unknown>
  structure?: Record<string, unknown>
  characters?: Record<string, unknown>
  borrowable?: Record<string, unknown>
  warnings?: Record<string, unknown>
}

const data = ref<DeconstructData | null>(null)

async function open(book: { title: string; file_path: string }) {
  title.value = book.title
  show.value = true
  loading.value = true
  data.value = null
  const res = await CreativeAPI.runDeconstruction({ file_path: book.file_path })
  if (res.ok && res.data) {
    data.value = res.data as DeconstructData
  } else {
    uiStore.showToast('解构失败: ' + (res.error || ''), 'error')
  }
  loading.value = false
}

function formatKey(key: string): string {
  const map: Record<string, string> = {
    // 题材标签
    target_audience: '目标读者',
    core_appeal: '核心爽点',
    genre_hybrids: '题材融合',
    tone: '整体基调',
    sub_genre: '子题材',
    market_position: '市场定位',
    // 结构拆解
    rhythm_curve: '节奏曲线',
    climax_distribution: '高潮分布',
    chapter_structure: '章节结构',
    pacing: '整体节奏',
    turning_points: '转折点',
    foreshadowing: '伏笔设计',
    plot_threads: '主线支线',
    opening_hook: '开篇钩子',
    ending_design: '结尾设计',
    // 人物拆解
    protagonist: '主角',
    supporting: '配角',
    antagonist: '反派',
    relationships: '人物关系',
    character_arc: '角色成长弧',
    character_map: '人物图谱',
    // 可借鉴元素
    structure_borrow: '可借鉴结构',
    dialogue_borrow: '可借鉴对话',
    emotion_borrow: '可借鉴情绪',
    technique_highlights: '高光技法',
    world_building: '世界观亮点',
    writing_style: '文笔特色',
    plot_templates: '情节模板',
    scene_templates: '场景模板',
    // 避雷清单
    common_mistakes: '常见败笔',
    reader_expectations: '读者预期',
    sensitive_content: '敏感内容',
    banned_points: '避雷要点',
    overused_tropes: '用烂套路',
    pacing_risks: '节奏风险',
  }
  return map[key] || key
}

function isObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}

function isStringOrNumber(v: unknown): v is string | number {
  return typeof v === 'string' || typeof v === 'number'
}

function firstTextField(obj: Record<string, unknown>): string | null {
  for (const key of ['name', 'title', 'point', 'reason', 'risk', 'description', 'summary', 'advice', 'suggestion', 'content', 'text', 'technique']) {
    const val = obj[key]
    if (typeof val === 'string' && val.trim()) return val.trim()
  }
  return null
}

function objectToText(obj: Record<string, unknown>): string {
  const text = firstTextField(obj)
  if (text) return text
  const parts: string[] = []
  for (const [k, v] of Object.entries(obj)) {
    if (isStringOrNumber(v)) parts.push(`${formatKey(k)}: ${v}`)
    else if (typeof v === 'string') parts.push(`${formatKey(k)}: ${v}`)
  }
  return parts.length ? parts.join(' · ') : JSON.stringify(obj)
}

function renderRhythmCurve(val: unknown): string {
  const arr = Array.isArray(val) ? val : []
  if (arr.length === 0) return '无数据'
  const nums = arr
    .map((v) => (typeof v === 'number' ? v : Number(v)))
    .filter((n) => !Number.isNaN(n))
  if (nums.length === 0) return '无数值数据'
  const avg = (nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1)
  const max = Math.max(...nums).toFixed(1)
  const min = Math.min(...nums).toFixed(1)
  return `共 ${nums.length} 个节奏点 · 均值 ${avg} · 峰值 ${max} · 谷值 ${min}`
}

interface KvEntry { key: string; label: string; value: unknown }

function sectionEntries(section?: Record<string, unknown>): KvEntry[] {
  if (!section) return []
  return Object.entries(section)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => ({ key: k, label: formatKey(k), value: v }))
}

function renderList(items: unknown[]): Array<{ title?: string; body?: string }> {
  return items.map((item) => {
    if (typeof item === 'string') return { body: item }
    if (isObject(item)) {
      const text = firstTextField(item)
      if (text) {
        const detail = Object.entries(item)
          .filter(([k, v]) => !['name', 'title', 'point'].includes(k) && isStringOrNumber(v))
          .map(([k, v]) => `${formatKey(k)}: ${v}`)
          .join(' · ')
        return { title: text, body: detail || undefined }
      }
      return { body: objectToText(item) }
    }
    return { body: String(item) }
  })
}

const genreTagEntries = computed(() => sectionEntries(data.value?.genre_tags))
const structureEntries = computed(() => sectionEntries(data.value?.structure))
const characterGroups = computed(() => {
  const chars = data.value?.characters
  if (!chars) return []
  return Object.entries(chars)
    .filter(([, v]) => Array.isArray(v) && v.length > 0)
    .map(([k, v]) => ({ key: k, label: formatKey(k), items: renderList(v as unknown[]) }))
})
const borrowableEntries = computed(() => sectionEntries(data.value?.borrowable))
const warningGroups = computed(() => {
  const warns = data.value?.warnings
  if (!warns) return []
  return Object.entries(warns)
    .filter(([, v]) => Array.isArray(v) && v.length > 0)
    .map(([k, v]) => ({ key: k, label: formatKey(k), items: renderList(v as unknown[]) }))
})

function renderSectionValue(entry: KvEntry): string {
  const { key, value } = entry
  if (key === 'rhythm_curve') return renderRhythmCurve(value)
  if (Array.isArray(value)) {
    return value
      .map((it) => (typeof it === 'string' ? it : isObject(it) ? objectToText(it) : String(it)))
      .join(' · ')
  }
  if (isObject(value)) return objectToText(value)
  return String(value)
}

defineExpose({ open })
</script>

<template>
  <div v-if="show" class="modal-overlay" @click.self="show = false">
    <div class="modal-box modal-lg">
      <div class="modal-header">
        <h3>小说解构 · {{ title }}</h3>
        <button class="modal-close" @click="show = false">×</button>
      </div>
      <div class="modal-body">
        <div class="deconstruct-hint">
          小说解构把一本书拆成五段式分析：题材标签、结构拆解、人物拆解、可借鉴元素、避雷清单。帮助你快速理解爆款小说的骨架、人物关系与可复用技法。
        </div>

        <div v-if="loading" class="dis-loading" style="height: 200px;">
          <div class="spinner" />
          <span>正在解构，请稍候（大文件可能需要 30-60 秒）…</span>
        </div>

        <div v-else-if="data" class="deconstruct-result">
          <!-- 1. 题材标签 -->
          <section class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">1</span>题材标签</div>
            <div v-if="genreTagEntries.length" class="deconstruct-tags">
              <div v-for="e in genreTagEntries" :key="e.key" class="deconstruct-tag-row">
                <span class="deconstruct-tag-label">{{ e.label }}</span>
                <span class="deconstruct-tag-value">{{ renderSectionValue(e) }}</span>
              </div>
            </div>
            <div v-else class="deconstruct-empty">暂无题材标签数据</div>
          </section>

          <!-- 2. 结构拆解 -->
          <section class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">2</span>结构拆解</div>
            <div v-if="structureEntries.length" class="deconstruct-tags">
              <div v-for="e in structureEntries" :key="e.key" class="deconstruct-tag-row">
                <span class="deconstruct-tag-label">{{ e.label }}</span>
                <span class="deconstruct-tag-value" :class="{ 'rhythm-curve': e.key === 'rhythm_curve' }">{{ renderSectionValue(e) }}</span>
              </div>
            </div>
            <div v-else class="deconstruct-empty">暂无结构拆解数据</div>
          </section>

          <!-- 3. 人物拆解 -->
          <section class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">3</span>人物拆解</div>
            <div v-if="characterGroups.length">
              <div v-for="g in characterGroups" :key="g.key" class="deconstruct-subsection">
                <div class="deconstruct-subtitle">{{ g.label }}</div>
                <div class="deconstruct-list">
                  <div v-for="(it, i) in g.items" :key="i" class="deconstruct-list-item">
                    <div v-if="it.title" class="list-item-title">{{ it.title }}</div>
                    <div v-if="it.body" class="list-item-body">{{ it.body }}</div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="deconstruct-empty">暂无人物拆解数据</div>
          </section>

          <!-- 4. 可借鉴元素 -->
          <section class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">4</span>可借鉴元素</div>
            <div v-if="borrowableEntries.length" class="deconstruct-tags">
              <div v-for="e in borrowableEntries" :key="e.key" class="deconstruct-tag-row">
                <span class="deconstruct-tag-label">{{ e.label }}</span>
                <span class="deconstruct-tag-value">{{ renderSectionValue(e) }}</span>
              </div>
            </div>
            <div v-else class="deconstruct-empty">暂无可借鉴元素</div>
          </section>

          <!-- 5. 避雷清单 -->
          <section class="deconstruct-section deconstruct-warnings">
            <div class="deconstruct-section-title"><span class="deconstruct-icon warn">5</span>避雷清单</div>
            <div v-if="warningGroups.length">
              <div v-for="g in warningGroups" :key="g.key" class="deconstruct-subsection">
                <div class="deconstruct-subtitle">{{ g.label }}</div>
                <div class="deconstruct-list">
                  <div v-for="(it, i) in g.items" :key="i" class="deconstruct-list-item warn">
                    <div v-if="it.title" class="list-item-title">{{ it.title }}</div>
                    <div v-if="it.body" class="list-item-body">{{ it.body }}</div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="deconstruct-empty">暂无避雷提示</div>
          </section>
        </div>

        <div v-else class="deconstruct-empty" style="padding: 16px;">
          解构失败，请确认文件存在且后端正常
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-box {
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border);
  max-width: 500px;
  width: 90%;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}
.modal-lg {
  max-width: 820px;
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
.modal-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}
.modal-close:hover {
  color: var(--text);
}
.modal-body {
  padding: 16px 18px;
  overflow-y: auto;
  flex: 1;
}
.deconstruct-hint {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  padding: 10px 12px;
  background: rgba(var(--accent-rgb), 0.06);
  border: 1px solid rgba(var(--accent-rgb), 0.15);
  border-radius: 8px;
  margin-bottom: 16px;
}
.deconstruct-section {
  margin-bottom: 18px;
  padding: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.deconstruct-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 12px;
}
.deconstruct-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: rgba(var(--accent-rgb), 0.12);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
}
.deconstruct-icon.warn {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
}
.deconstruct-tags {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.deconstruct-tag-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 8px;
}
.deconstruct-tag-label {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 600;
}
.deconstruct-tag-value {
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
}
.deconstruct-tag-value.rhythm-curve {
  color: var(--accent);
  font-weight: 600;
}
.deconstruct-subsection {
  margin-bottom: 12px;
}
.deconstruct-subtitle {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.deconstruct-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.deconstruct-list-item {
  padding: 10px 12px;
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}
.deconstruct-list-item.warn {
  border-color: rgba(239, 68, 68, 0.25);
  background: rgba(239, 68, 68, 0.04);
}
.list-item-title {
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}
.list-item-body {
  font-size: 12px;
  color: var(--text-secondary);
}
.deconstruct-empty {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 12px;
}
.dis-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}
.spinner {
  width: 28px;
  height: 28px;
  border: 2px solid var(--border-hover);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 640px) {
  .deconstruct-tags {
    grid-template-columns: 1fr;
  }
}
</style>
