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
        <div class="mini-bar-fill" :style="{ width: bar.pct + '%', background: bar.color }">
          <span v-if="bar.pct > 15" class="mini-bar-fill-label">{{ bar.pct }}%</span>
        </div>
      </div>
      <span v-if="bar.pct <= 15" class="mini-bar-value">{{ bar.pct }}%</span>
    </div>
  </div>
</template>

<style scoped>
.report-chart {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.mini-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mini-bar-label {
  width: 48px;
  font-size: 11px;
  color: var(--text-secondary);
  flex-shrink: 0;
  font-weight: 500;
}
.mini-bar-track {
  flex: 1;
  height: 18px;
  background: var(--surface-faint);
  border-radius: 5px;
  overflow: hidden;
  position: relative;
  border: 1px solid var(--border);
}
.mini-bar-fill {
  height: 100%;
  border-radius: 4px;
  min-width: 4px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 6px;
  transition: width 0.4s ease;
  box-shadow: inset 0 1px 0 rgba(var(--text-rgb),0.18), 0 1px 2px rgba(0,0,0,0.08);
}
.mini-bar-fill-label,
.mini-bar-value {
  font-size: 10px;
  font-weight: 700;
  color: rgba(var(--text-rgb),0.95);
  text-shadow: 0 1px 2px rgba(0,0,0,0.25);
}
.mini-bar-value {
  width: 28px;
  text-align: right;
  color: var(--text-secondary);
  text-shadow: none;
  font-weight: 600;
}
</style>
