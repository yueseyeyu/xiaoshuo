<script setup lang="ts">
import { computed } from 'vue'

/**
 * MiniBarChart — 轻量级 SVG/ div 柱状图
 */
interface BarItem { label: string; value: number }

const props = defineProps<{
  data: BarItem[]
  color?: string
}>()

const max = computed(() => Math.max(...props.data.map((d) => d.value), 1))
</script>

<template>
  <div class="mini-bar-chart">
    <div
      v-for="item in data"
      :key="item.label"
      class="mini-bar-item"
      :style="{ '--bar-height': `${(item.value / max) * 100}%` }"
    >
      <div class="mini-bar-track">
        <div class="mini-bar-fill" :style="{ background: color || 'var(--accent)' }"></div>
      </div>
      <div class="mini-bar-label">{{ item.label }}</div>
    </div>
  </div>
</template>

<style scoped>
.mini-bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 100%;
}
.mini-bar-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.mini-bar-track {
  width: 100%;
  height: 48px;
  display: flex;
  align-items: flex-end;
  border-radius: 3px;
  overflow: hidden;
}
.mini-bar-fill {
  width: 100%;
  height: var(--bar-height);
  border-radius: 3px 3px 0 0;
  transition: height 0.2s ease;
}
.mini-bar-label {
  font-size: 10px;
  color: var(--text-muted);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}
</style>
