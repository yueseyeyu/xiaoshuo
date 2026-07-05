<script setup lang="ts">
/**
 * ReportDetailDrawer — 报告详情抽屉
 * 将 ReportsView 生成的纯文本 detail 解析为结构化卡片展示。
 */
import { computed } from 'vue'

interface AdviceItem {
  icon: 'warning' | 'check' | 'bolt' | 'info'
  text: string
}

interface ReportCard {
  title: string
  insight: string
  advice: AdviceItem[]
  detail: string
}

interface DetailRow {
  key: string
  value: string
}

interface DetailSection {
  title: string
  rows: DetailRow[]
}

const props = defineProps<{
  card: ReportCard | null
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'export'): void
}>()

const detailSections = computed<DetailSection[]>(() => {
  if (!props.card?.detail) return []
  const lines = props.card.detail.split('\n').map((l) => l.trim()).filter(Boolean)
  const sections: DetailSection[] = []
  let current: DetailSection | null = null

  for (const line of lines) {
    if (line.startsWith('【') && line.endsWith('】')) {
      current = { title: line.slice(1, -1), rows: [] }
      sections.push(current)
      continue
    }
    if (!current) {
      current = { title: '详细数据', rows: [] }
      sections.push(current)
    }
    const sepIndex = Math.max(line.indexOf(':'), line.indexOf('：'))
    if (sepIndex > 0) {
      current.rows.push({
        key: line.slice(0, sepIndex).trim(),
        value: line.slice(sepIndex + 1).trim(),
      })
    } else {
      current.rows.push({ key: '', value: line })
    }
  }
  return sections
})
</script>

<template>
  <div v-if="open" class="detail-overlay" @click="emit('close')" />
  <div class="detail-drawer" :class="{ open }">
    <template v-if="card">
      <div class="detail-header">
        <h3>{{ card.title }}</h3>
        <button class="icon-btn" @click="emit('close')">×</button>
      </div>
      <div class="detail-body">
        <div class="detail-field">
          <label>核心洞察</label>
          <div class="detail-text">{{ card.insight }}</div>
        </div>
        <div v-if="card.advice.length" class="detail-field">
          <label>创作建议</label>
          <div class="report-advice-list">
            <div v-for="(a, i) in card.advice" :key="i" class="report-advice">
              <span v-if="a.icon === 'warning'" class="advice-icon warning"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
              <span v-else-if="a.icon === 'check'" class="advice-icon check"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg></span>
              <span v-else-if="a.icon === 'bolt'" class="advice-icon bolt"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg></span>
              <span v-else class="advice-icon info"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></span>
              <span>{{ a.text }}</span>
            </div>
          </div>
        </div>
        <div class="detail-field">
          <label>详细分析</label>
          <div class="detail-sections">
            <div v-for="(section, si) in detailSections" :key="si" class="detail-section">
              <div class="detail-section-title">{{ section.title }}</div>
              <div class="detail-section-body">
                <div v-for="(row, ri) in section.rows" :key="ri" class="detail-row" :class="{ 'plain': !row.key }">
                  <div v-if="row.key" class="detail-row-key">{{ row.key }}</div>
                  <div class="detail-row-value">{{ row.value }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="detail-footer">
        <button class="btn btn-secondary btn-sm" @click="emit('export')">导出报告</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.detail-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  z-index: 100;
  opacity: 0;
  animation: fade-in 0.2s forwards;
}
@keyframes fade-in { to { opacity: 1; } }

.detail-drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: 460px;
  max-width: 90vw;
  height: 100vh;
  background: var(--surface-solid);
  border-left: 1px solid var(--border);
  z-index: 101;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.2s ease;
}
.detail-drawer.open { transform: translateX(0); }

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.detail-header h3 { font-size: 16px; font-weight: 600; }

.detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-field label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.detail-text { font-size: 14px; color: var(--text); }

.detail-sections {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.detail-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.detail-section-title {
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
  background: rgba(var(--text-rgb), 0.03);
  border-bottom: 1px solid var(--border);
}
.detail-section-body {
  padding: 6px 0;
}
.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 7px 12px;
  font-size: 12px;
}
.detail-row:not(:last-child) {
  border-bottom: 1px solid rgba(var(--text-rgb), 0.04);
}
.detail-row.plain {
  justify-content: flex-start;
}
.detail-row-key {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.detail-row-value {
  color: var(--text);
  font-weight: 600;
  text-align: right;
}

.detail-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
}

.icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-btn:hover { background: var(--surface-hover); }

.report-advice-list { margin-bottom: 8px; }
.report-advice {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 4px;
}
.advice-icon { flex-shrink: 0; font-size: 14px; }
.advice-icon.warning { color: var(--warning); }
.advice-icon.check   { color: var(--success); }
.advice-icon.bolt    { color: var(--accent); }
.advice-icon.info    { color: var(--text-secondary); }

@media (max-width: 768px) {
  .detail-drawer { width: 100vw; }
}
</style>
