<script setup lang="ts">
/**
 * ReportCard — 报告卡片组件
 * 组装 MiniBarChart + TechniqueMiniList + AdviceList 子组件
 */
import MiniBarChart from './MiniBarChart.vue'
import AdviceList, { type AdviceItem } from './AdviceList.vue'
import TechniqueMiniList from './TechniqueMiniList.vue'

export interface ReportCardData {
  type: string
  dotClass: string
  title: string
  insight: string
  meta: string
  tags: string[]
  advice: AdviceItem[]
  detail: string
  chart?: Array<{ label: string; pct: number; color: string }>
  techByCat?: Record<string, Array<{ title: string; content: string; category?: string; id?: string }>>
}

defineProps<{
  card: ReportCardData
}>()

const emit = defineEmits<{
  (e: 'open-detail', card: ReportCardData): void
  (e: 'apply-technique', name: string): void
}>()
</script>

<template>
  <div class="report-card" @click="emit('open-detail', card)">
    <div class="report-header">
      <span class="lifecycle-dot" :class="card.dotClass" />
      <h3>{{ card.title }}</h3>
    </div>
    <p class="report-insight">{{ card.insight }}</p>

    <MiniBarChart v-if="card.chart" :bars="card.chart" />

    <TechniqueMiniList
      v-if="card.type === 'tech' && card.techByCat"
      :tech-by-cat="card.techByCat"
      @apply-technique="(name: string) => emit('apply-technique', name)"
    />

    <AdviceList :advice="card.advice" />

    <div class="report-meta">
      <span>{{ card.meta }}</span>
      <div class="report-tags">
        <span v-for="t in card.tags" :key="t" class="report-tag">{{ t }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.15s;
}
.report-card:hover {
  border-color: var(--border-hover);
  transform: translateY(-2px);
}
.report-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.report-header h3 { font-size: 14px; font-weight: 600; }
.lifecycle-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.lifecycle-dot.green { background: var(--success); }
.lifecycle-dot.amber { background: var(--warning); }
.lifecycle-dot.red { background: var(--danger); }
.lifecycle-dot.purple { background: var(--violet); }
.lifecycle-dot.blue { background: var(--info); }
.report-insight {
  font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;
}
.report-meta {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11px; color: var(--text-secondary);
}
.report-tags { display: flex; gap: 4px; }
.report-tag {
  padding: 1px 6px; border-radius: 3px; background: var(--surface-hover); font-size: 10px;
}
</style>