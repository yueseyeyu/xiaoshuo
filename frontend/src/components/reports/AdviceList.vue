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
    <div v-for="(a, i) in advice" :key="i" class="report-advice">
      <span v-if="a.icon === 'warning'" class="advice-icon warning">&#9888;</span>
      <span v-else-if="a.icon === 'check'" class="advice-icon check">&#10003;</span>
      <span v-else-if="a.icon === 'bolt'" class="advice-icon bolt">&#9889;</span>
      <span v-else class="advice-icon info">&#8505;</span>
      <span>{{ a.text }}</span>
    </div>
  </div>
</template>

<style scoped>
.report-advice-list { margin-bottom: 8px; }
.report-advice {
  display: flex; align-items: flex-start; gap: 6px; font-size: 12px; margin-bottom: 4px;
}
.advice-icon { flex-shrink: 0; font-size: 14px; }
.advice-icon.warning { color: var(--warning); }
.advice-icon.check { color: var(--success); }
.advice-icon.bolt { color: var(--accent); }
.advice-icon.info { color: var(--text-secondary); }
</style>