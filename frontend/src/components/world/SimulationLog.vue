<script setup lang="ts">
/**
 * SimulationLog — 推演日志面板
 * 快照差异对比 + 导出大纲 + 实时事件列表
 */
import type { SimulationEvent } from '@/types'

defineProps<{
  diffFromChapter: number
  diffToChapter: number
  diffChanges: Array<Record<string, unknown>>
  exportFromChapter: number
  exportToChapter: number
  exporting: boolean
  showExportPanel: boolean
  exportResult: {
    world_context: string
    chapter_drafts: Array<{
      chapter: number
      events: SimulationEvent[]
      faction_summary: string
      character_summary: string
      suggested_outline: string
    }>
  } | null
  simulationEvents: SimulationEvent[]
}>()

const emit = defineEmits<{
  (e: 'update:diffFromChapter', v: number): void
  (e: 'update:diffToChapter', v: number): void
  (e: 'update:exportFromChapter', v: number): void
  (e: 'update:exportToChapter', v: number): void
  (e: 'loadDiff'): void
  (e: 'exportToOutline'): void
}>()
</script>

<template>
  <div class="panel-content">
    <!-- 快照差异对比 -->
    <div class="diff-tool">
      <div class="diff-title">快照差异对比</div>
      <div class="diff-controls">
        <input type="number" :value="diffFromChapter" @input="emit('update:diffFromChapter', Number(($event.target as HTMLInputElement).value))" placeholder="从第几章" class="diff-input" />
        <span class="diff-arrow">→</span>
        <input type="number" :value="diffToChapter" @input="emit('update:diffToChapter', Number(($event.target as HTMLInputElement).value))" placeholder="到第几章" class="diff-input" />
        <button class="btn btn-ghost btn-sm" @click="emit('loadDiff')">对比</button>
      </div>
      <div v-if="diffChanges.length" class="diff-result">
        <div v-for="(change, idx) in diffChanges" :key="idx" class="diff-row">
          <span class="diff-target">{{ (change as Record<string, string>).target_type }}: {{ (change as Record<string, string>).target_id }}</span>
          <span class="diff-field">{{ (change as Record<string, string>).field }}</span>
          <span class="diff-from">{{ (change as Record<string, number>).from }}</span>
          <span class="diff-arrow">→</span>
          <span class="diff-to">{{ (change as Record<string, number>).to }}</span>
          <span class="diff-delta" :class="{ negative: (change as Record<string, number>).delta < 0, positive: (change as Record<string, number>).delta > 0 }">
            {{ (change as Record<string, number>).delta > 0 ? '+' : '' }}{{ (change as Record<string, number>).delta }}
          </span>
        </div>
      </div>
    </div>

    <!-- 导出到大纲 -->
    <div class="export-tool">
      <div class="diff-title">推演 → 大纲导出</div>
      <div class="diff-controls">
        <label class="sim-param">从第</label>
        <input type="number" :value="exportFromChapter" @input="emit('update:exportFromChapter', Number(($event.target as HTMLInputElement).value))" class="diff-input" min="0" />
        <label class="sim-param">章到第</label>
        <input type="number" :value="exportToChapter" @input="emit('update:exportToChapter', Number(($event.target as HTMLInputElement).value))" class="diff-input" min="1" />
        <label class="sim-param">章</label>
        <button class="btn btn-primary btn-sm" @click="emit('exportToOutline')" :disabled="exporting">
          {{ exporting ? '导出中...' : '导出大纲草稿' }}
        </button>
      </div>

      <!-- 导出结果 -->
      <div v-if="showExportPanel && exportResult" class="export-result">
        <div v-if="exportResult.world_context" class="export-context">
          <div class="export-context-title">世界推演上下文</div>
          <pre class="export-context-text">{{ exportResult.world_context }}</pre>
        </div>
        <div v-for="draft in exportResult.chapter_drafts" :key="draft.chapter" class="export-draft-card">
          <div class="export-draft-header">
            <span class="export-draft-chapter">第 {{ draft.chapter }} 章</span>
            <span class="export-draft-events">{{ draft.events.length }} 条推演事件</span>
          </div>
          <div v-if="draft.faction_summary" class="export-draft-row">
            <span class="export-draft-label">势力状态</span>
            <span class="export-draft-value">{{ draft.faction_summary }}</span>
          </div>
          <div v-if="draft.character_summary" class="export-draft-row">
            <span class="export-draft-label">角色状态</span>
            <span class="export-draft-value">{{ draft.character_summary }}</span>
          </div>
          <div class="export-draft-outline">
            <span class="export-draft-label">建议大纲</span>
            <pre class="export-draft-text">{{ draft.suggested_outline }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- 事件列表 -->
    <div v-if="simulationEvents.length" class="event-list">
      <div v-for="ev in simulationEvents" :key="ev.id" class="event-item">
        <span class="event-chapter">第{{ ev.chapter }}章</span>
        <span class="event-type" :class="ev.type">{{ ev.type }}</span>
        <span class="event-desc">{{ ev.description }}</span>
      </div>
    </div>
    <div v-else class="empty-state">
      <div class="empty-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        </svg>
      </div>
      <p>暂无推演记录</p>
      <span class="text-muted">启动推演后，事件将实时显示在此处</span>
    </div>
  </div>
</template>

<style scoped>
.panel-content { padding: 16px; }

.diff-tool, .export-tool {
  padding: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
}

.diff-title { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 8px; }

.diff-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.diff-input {
  width: 72px;
  padding: 4px 6px;
  font-size: 13px;
  color: var(--text);
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 4px;
  text-align: center;
}

.diff-arrow { color: var(--text-secondary); font-size: 12px; }

.sim-param { font-size: 12px; color: var(--text-secondary); }

.diff-result { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }

.diff-row {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 8px; background: var(--surface-solid); border-radius: 4px;
  font-size: 12px;
}

.diff-target { color: var(--text); font-weight: 500; }
.diff-field { color: var(--text-secondary); }
.diff-from, .diff-to { color: var(--text); }
.diff-delta { font-weight: 600; }
.diff-delta.positive { color: var(--success); }
.diff-delta.negative { color: var(--danger); }

/* 导出结果 */
.export-result { margin-top: 12px; }

.export-context {
  padding: 10px 12px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 10px;
}

.export-context-title { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.export-context-text { font-size: 11px; color: var(--text-secondary); white-space: pre-wrap; margin: 0; }

.export-draft-card {
  padding: 10px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 8px;
}

.export-draft-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 6px;
}

.export-draft-chapter { font-size: 13px; font-weight: 600; color: var(--text); }
.export-draft-events { font-size: 11px; color: var(--text-secondary); }

.export-draft-row { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
.export-draft-label { font-size: 11px; color: var(--text-secondary); flex-shrink: 0; }
.export-draft-value { font-size: 12px; color: var(--text); }

.export-draft-outline { margin-top: 6px; }
.export-draft-text { font-size: 11px; color: var(--text-secondary); white-space: pre-wrap; margin: 4px 0 0; }

/* 事件列表 */
.event-list { display: flex; flex-direction: column; gap: 6px; }

.event-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}

.event-chapter { font-weight: 600; color: var(--accent); flex-shrink: 0; }

.event-type {
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;
  text-transform: uppercase; flex-shrink: 0;
}
.event-type.battle { background: rgba(var(--danger-rgb), 0.1); color: var(--danger); }
.event-type.diplomacy { background: rgba(var(--accent-rgb), 0.1); color: var(--accent); }
.event-type.movement { background: rgba(var(--success-rgb), 0.1); color: var(--success); }
.event-type.discovery { background: rgba(var(--warning-rgb), 0.1); color: var(--warning); }
.event-type.faction { background: rgba(var(--accent-rgb), 0.08); color: var(--accent); }
.event-type.character { background: rgba(var(--brand-lavender-rgb), 0.1); color: var(--brand-lavender); }

.event-desc { flex: 1; color: var(--text-secondary); }

.empty-state { text-align: center; padding: 32px; color: var(--text-secondary); }
.empty-icon { margin-bottom: 8px; color: var(--text-muted); }
.empty-state p { margin: 4px 0; font-size: 14px; }
.text-muted { font-size: 12px; color: var(--text-muted); }
</style>