<script setup lang="ts">
/**
 * ReportCard — 报告卡片组件
 * 组装 MiniBarChart + TechniqueMiniList + AdviceList 子组件
 */
import MiniBarChart from './MiniBarChart.vue'
import AdviceList, { type AdviceItem } from './AdviceList.vue'
import TechniqueMiniList from './TechniqueMiniList.vue'

const typeMeta: Record<string, { icon: string; color: string }> = {
  overview: { icon: 'stack', color: 'green' },
  quality: { icon: 'shield', color: 'cyan' },
  score: { icon: 'check', color: 'blue' },
  rhythm: { icon: 'pulse', color: 'purple' },
  pleasure: { icon: 'bolt', color: 'amber' },
  tech: { icon: 'star', color: 'rose' },
}

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

function getIcon(type: string): string {
  return typeMeta[type]?.icon || 'stack'
}
</script>

<template>
  <div class="report-card" :class="[`accent-${typeMeta[card.type]?.color || 'blue'}`]" @click="emit('open-detail', card)">
    <div class="report-card-top">
      <div class="report-icon">
        <svg v-if="getIcon(card.type) === 'stack'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        <svg v-else-if="getIcon(card.type) === 'shield'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        <svg v-else-if="getIcon(card.type) === 'check'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        <svg v-else-if="getIcon(card.type) === 'pulse'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
        <svg v-else-if="getIcon(card.type) === 'bolt'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <svg v-else-if="getIcon(card.type) === 'star'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
      </div>
      <div class="report-header-text">
        <h3>{{ card.title }}</h3>
        <div class="report-meta-row">
          <span v-for="t in card.tags" :key="t" class="report-tag">{{ t }}</span>
        </div>
      </div>
    </div>

    <p class="report-insight">{{ card.insight }}</p>

    <MiniBarChart v-if="card.chart" :bars="card.chart" />

    <TechniqueMiniList
      v-if="card.type === 'tech' && card.techByCat"
      :tech-by-cat="card.techByCat"
      @apply-technique="(name: string) => emit('apply-technique', name)"
    />

    <AdviceList :advice="card.advice" />

    <div class="report-footer">
      <span class="report-meta">{{ card.meta }}</span>
      <span class="report-action">查看详情</span>
    </div>
  </div>
</template>

<style scoped>
.report-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 14px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: relative;
  overflow: hidden;
  outline: none;
}
.report-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(var(--accent-rgb), 0.04) 0%, transparent 50%);
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.2s;
}
.report-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(0,0,0,0.14);
}
.report-card:hover::before {
  opacity: 1;
}
.report-card:focus-visible {
  box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.25), 0 10px 28px rgba(0,0,0,0.14);
  border-color: var(--accent);
}
.report-card:active {
  transform: translateY(0) scale(0.995);
}

.report-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.report-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(var(--accent-rgb), 0.12);
  color: var(--accent);
}
.report-header-text {
  flex: 1;
  min-width: 0;
}
.report-header-text h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 4px;
  color: var(--text);
}
.report-meta-row {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.report-tag {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-faint);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 500;
  border: 1px solid var(--border);
}

.report-insight {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.45;
  margin: 0;
}

.report-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.report-meta {
  font-size: 11px;
  color: var(--text-muted);
}
.report-action {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  opacity: 1;
  transform: translateX(0);
  transition: all 0.2s ease;
}
.report-card:hover .report-action {
  color: var(--text);
}

/* 类型色 */
.report-card.accent-green { --accent: var(--success); --accent-rgb: var(--success-rgb); }
.report-card.accent-cyan { --accent: var(--brand-arctic); --accent-rgb: 34, 211, 238; }
.report-card.accent-blue { --accent: var(--info); --accent-rgb: var(--info-rgb); }
.report-card.accent-purple { --accent: var(--violet); --accent-rgb: var(--violet-rgb); }
.report-card.accent-amber { --accent: var(--warning); --accent-rgb: var(--warning-rgb); }
.report-card.accent-rose { --accent: var(--danger); --accent-rgb: var(--danger-rgb); }
</style>
