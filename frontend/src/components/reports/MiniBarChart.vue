<script setup lang="ts">
/**
 * MiniBarChart — 迷你条形图
 * 纯展示组件，用于节奏/爽点/情绪分布
 */
defineProps<{
  bars: Array<{ label: string; pct: number; color: string }>
}>()
</script>

<template>
  <div class="report-chart">
    <div v-for="bar in bars" :key="bar.label" class="mini-bar-row">
      <span class="mini-bar-label">{{ bar.label }}</span>
      <div class="mini-bar-track">
        <div class="mini-bar-fill" :style="{ width: bar.pct + '%', background: bar.color }" />
      </div>
      <span class="mini-bar-value">{{ bar.pct }}%</span>
    </div>
  </div>
</template>

<style scoped>
.report-chart { margin-bottom: 8px; }
.mini-bar-row {
  display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
}
.mini-bar-label {
  width: 60px; font-size: 11px; color: var(--text-secondary); flex-shrink: 0;
}
.mini-bar-track {
  flex: 1; height: 8px; background: var(--surface-solid); border-radius: 4px; overflow: hidden;
}
.mini-bar-fill {
  height: 100%; border-radius: 4px; transition: width 0.3s ease;
}
.mini-bar-value {
  width: 36px; text-align: right; font-size: 11px; color: var(--text-secondary);
}
</style>