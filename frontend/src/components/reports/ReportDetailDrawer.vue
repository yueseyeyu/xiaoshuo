<script setup lang="ts">
/**
 * ReportDetailDrawer — 报告详情抽屉
 * 从 ReportsView 拆分，展示核心洞察 + 创作建议 + 详细分析
 */
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

defineProps<{
  card: ReportCard | null
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'export'): void
}>()
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
              <span v-if="a.icon === 'warning'" class="advice-icon warning">⚠</span>
              <span v-else-if="a.icon === 'check'" class="advice-icon check">✓</span>
              <span v-else-if="a.icon === 'bolt'" class="advice-icon bolt">⚡</span>
              <span v-else class="advice-icon info">ℹ</span>
              <span>{{ a.text }}</span>
            </div>
          </div>
        </div>
        <div class="detail-field">
          <label>详细分析</label>
          <pre class="detail-pre">{{ card.detail }}</pre>
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
  width: 420px;
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

.detail-pre {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  font-family: 'SF Mono', 'Cascadia Code', monospace;
  line-height: 1.6;
  background: var(--surface);
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
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