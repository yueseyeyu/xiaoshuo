<script setup lang="ts">
/**
 * AdviceList — 创作建议列表
 * 纯展示组件，4 种图标映射
 */
export interface AdviceItem {
  icon: 'warning' | 'check' | 'bolt' | 'info'
  text: string
}

defineProps<{
  advice: AdviceItem[]
}>()
</script>

<template>
  <div v-if="advice.length" class="report-advice-list">
    <div v-for="(a, i) in advice" :key="i" class="report-advice" :class="`advice-${a.icon}`">
      <span class="advice-icon">
        <svg v-if="a.icon === 'warning'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <svg v-else-if="a.icon === 'check'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
        <svg v-else-if="a.icon === 'bolt'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
      </span>
      <span class="advice-text">{{ a.text }}</span>
    </div>
  </div>
</template>

<style scoped>
.report-advice-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.report-advice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--text-secondary);
  padding: 5px 7px;
  border-radius: 8px;
  background: var(--surface-faint);
  border: 1px solid transparent;
  transition: all 0.15s;
}
.report-advice:hover {
  background: var(--surface-solid);
  border-color: var(--border);
}
.advice-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 0;
}
.advice-text {
  flex: 1;
}

.advice-warning .advice-icon { color: var(--warning); background: rgba(var(--warning-rgb), 0.12); }
.advice-check .advice-icon { color: var(--success); background: rgba(var(--success-rgb), 0.12); }
.advice-bolt .advice-icon { color: var(--violet); background: rgba(var(--violet-rgb), 0.12); }
.advice-info .advice-icon { color: var(--info); background: rgba(var(--info-rgb), 0.12); }

.advice-warning:hover { border-color: rgba(var(--warning-rgb), 0.35); }
.advice-check:hover { border-color: rgba(var(--success-rgb), 0.35); }
.advice-bolt:hover { border-color: rgba(var(--violet-rgb), 0.35); }
.advice-info:hover { border-color: rgba(var(--info-rgb), 0.35); }
</style>
