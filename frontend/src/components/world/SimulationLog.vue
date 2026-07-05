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

function eventTypeClass(type: string): string {
  const map: Record<string, string> = {
    battle: 'battle',
    diplomacy: 'diplomacy',
    movement: 'movement',
    discovery: 'discovery',
    faction: 'faction',
    character: 'character',
  }
  return map[type] || 'default'
}

function eventTypeLabel(type: string): string {
  const map: Record<string, string> = {
    battle: '战斗',
    diplomacy: '外交',
    movement: '移动',
    discovery: '发现',
    faction: '势力',
    character: '角色',
  }
  return map[type] || type
}
</script>

<template>
  <div class="simulation-log">
    <!-- 工具栏 -->
    <div class="tools-grid">
      <!-- 快照差异 -->
      <div class="tool-card">
        <div class="tool-header">
          <div class="tool-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>
          <div>
            <div class="tool-title">快照差异对比</div>
            <div class="tool-desc">对比两个章节间的世界状态变化</div>
          </div>
        </div>
        <div class="tool-controls">
          <div class="range-group">
            <label>从第</label>
            <input
              type="number"
              :value="diffFromChapter"
              @input="emit('update:diffFromChapter', Number(($event.target as HTMLInputElement).value))"
              placeholder="0"
              class="tool-input"
              min="0"
            />
            <label>章</label>
          </div>
          <span class="tool-arrow">→</span>
          <div class="range-group">
            <label>到第</label>
            <input
              type="number"
              :value="diffToChapter"
              @input="emit('update:diffToChapter', Number(($event.target as HTMLInputElement).value))"
              placeholder="0"
              class="tool-input"
              min="0"
            />
            <label>章</label>
          </div>
          <button class="btn btn-secondary btn-sm" @click="emit('loadDiff')">对比</button>
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

      <!-- 导出大纲 -->
      <div class="tool-card">
        <div class="tool-header">
          <div class="tool-icon export">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <line x1="9" y1="15" x2="15" y2="15" />
            </svg>
          </div>
          <div>
            <div class="tool-title">推演 → 大纲导出</div>
            <div class="tool-desc">将推演结果转换为章节大纲草稿</div>
          </div>
        </div>
        <div class="tool-controls">
          <div class="range-group">
            <label>从第</label>
            <input
              type="number"
              :value="exportFromChapter"
              @input="emit('update:exportFromChapter', Number(($event.target as HTMLInputElement).value))"
              class="tool-input"
              min="0"
            />
            <label>章</label>
          </div>
          <span class="tool-arrow">→</span>
          <div class="range-group">
            <label>到第</label>
            <input
              type="number"
              :value="exportToChapter"
              @input="emit('update:exportToChapter', Number(($event.target as HTMLInputElement).value))"
              class="tool-input"
              min="1"
            />
            <label>章</label>
          </div>
          <button class="btn btn-primary btn-sm" @click="emit('exportToOutline')" :disabled="exporting">
            {{ exporting ? '导出中...' : '导出大纲草稿' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 导出结果 -->
    <div v-if="showExportPanel && exportResult" class="export-result-panel">
      <div class="export-section-title">导出结果</div>
      <div v-if="exportResult.world_context" class="export-context">
        <div class="export-context-title">世界推演上下文</div>
        <pre class="export-context-text">{{ exportResult.world_context }}</pre>
      </div>
      <div class="export-drafts">
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

    <!-- 事件时间线 -->
    <div class="events-section">
      <div class="events-header">
        <div class="events-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
          </svg>
          推演事件
        </div>
        <span class="events-count" v-if="simulationEvents.length">{{ simulationEvents.length }} 条事件</span>
      </div>

      <div v-if="simulationEvents.length" class="event-timeline">
        <div v-for="ev in simulationEvents" :key="ev.id" class="event-item">
          <div class="event-timeline-line"></div>
          <div class="event-marker" :class="eventTypeClass(ev.type)"></div>
          <div class="event-card">
            <div class="event-card-header">
              <span class="event-chapter">第 {{ ev.chapter }} 章</span>
              <span class="event-type" :class="eventTypeClass(ev.type)">{{ eventTypeLabel(ev.type) }}</span>
            </div>
            <p class="event-desc">{{ ev.description }}</p>
          </div>
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
  </div>
</template>

<style scoped>
.simulation-log {
  display: flex;
  flex-direction: column;
  gap: 20px;
  animation: fadeIn 0.25s ease;
}

/* ── 工具栏 ── */
.tools-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.tool-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tool-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.tool-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  background: rgba(var(--accent-rgb), 0.1);
  flex-shrink: 0;
}

.tool-icon.export {
  color: var(--success);
  background: rgba(var(--success-rgb), 0.1);
}

.tool-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.tool-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.tool-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.range-group {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.tool-input {
  width: 60px;
  padding: 5px 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 6px;
  text-align: center;
}

.tool-input:focus {
  outline: none;
  border-color: var(--accent);
}

.tool-arrow {
  color: var(--text-muted);
  font-size: 12px;
}

.diff-result {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.diff-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--surface-solid);
  border-radius: 6px;
  font-size: 12px;
}

.diff-target { color: var(--text); font-weight: 500; }
.diff-field { color: var(--text-muted); }
.diff-from, .diff-to { color: var(--text); }
.diff-delta { font-weight: 600; margin-left: auto; }
.diff-delta.positive { color: var(--success); }
.diff-delta.negative { color: var(--danger); }

/* ── 导出结果 ── */
.export-result-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
}

.export-section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}

.export-context {
  padding: 12px 14px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 12px;
}

.export-context-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}

.export-context-text {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  margin: 0;
  line-height: 1.5;
}

.export-drafts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.export-draft-card {
  padding: 14px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.export-draft-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.export-draft-chapter { font-size: 13px; font-weight: 600; color: var(--text); }
.export-draft-events { font-size: 11px; color: var(--text-muted); }

.export-draft-row { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.export-draft-label { font-size: 11px; color: var(--text-muted); flex-shrink: 0; }
.export-draft-value { font-size: 12px; color: var(--text); }

.export-draft-outline { margin-top: 8px; }
.export-draft-text { font-size: 11px; color: var(--text-secondary); white-space: pre-wrap; margin: 6px 0 0; line-height: 1.5; }

/* ── 事件时间线 ── */
.events-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
}

.events-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.events-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.events-count {
  font-size: 12px;
  color: var(--text-muted);
  padding: 3px 10px;
  background: var(--surface-faint);
  border-radius: 20px;
}

.event-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
}

.event-item {
  display: flex;
  gap: 14px;
  position: relative;
  padding-bottom: 16px;
}

.event-item:last-child {
  padding-bottom: 0;
}

.event-timeline-line {
  position: absolute;
  left: 5px;
  top: 12px;
  bottom: 0;
  width: 2px;
  background: var(--border);
}

.event-item:last-child .event-timeline-line {
  display: none;
}

.event-marker {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
  margin-top: 6px;
  z-index: 1;
  border: 2px solid var(--surface);
}

.event-marker.battle { background: var(--danger); }
.event-marker.diplomacy { background: var(--accent); }
.event-marker.movement { background: var(--success); }
.event-marker.discovery { background: var(--warning); }
.event-marker.faction { background: var(--indigo); }
.event-marker.character { background: var(--violet); }

.event-card {
  flex: 1;
  padding: 12px 14px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.event-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.event-chapter {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}

.event-type {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.event-type.battle { background: rgba(var(--danger-rgb), 0.1); color: var(--danger); }
.event-type.diplomacy { background: rgba(var(--accent-rgb), 0.1); color: var(--accent); }
.event-type.movement { background: rgba(var(--success-rgb), 0.1); color: var(--success); }
.event-type.discovery { background: rgba(var(--warning-rgb), 0.1); color: var(--warning); }
.event-type.faction { background: rgba(var(--indigo-rgb), 0.08); color: var(--indigo); }
.event-type.character { background: rgba(var(--violet-rgb), 0.1); color: var(--violet); }
.event-type.default { background: var(--surface-faint); color: var(--text-secondary); }

.event-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  text-align: center;
}

.empty-icon {
  color: var(--text-muted);
  margin-bottom: 12px;
  opacity: 0.45;
}

.empty-state p {
  font-size: 15px;
  color: var(--text);
  font-weight: 500;
  margin: 0 0 4px 0;
}

.empty-state .text-muted {
  font-size: 12px;
  color: var(--text-muted);
}

.text-muted { color: var(--text-muted); }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 1024px) {
  .tools-grid {
    grid-template-columns: 1fr;
  }
}
</style>
