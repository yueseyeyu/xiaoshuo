<script setup lang="ts">
/**
 * PipelineProgress — 拆书管线进度可视化
 *
 * 从 DashboardView 提取，展示管线阶段步骤条、进度条和已完成书籍。
 */
import { computed } from 'vue'
import type { ProgressData } from '@/api/dashboard'

const props = defineProps<{
  progressData: ProgressData | null
}>()

const emit = defineEmits<{
  stop: []
}>()

const PIPELINE_STAGES = [
  { key: 'chunk', label: '分块', icon: '✂️' },
  { key: 'recursive_summarize', label: '递归摘要', icon: '📜' },
  { key: 'rhythm', label: '节奏分析', icon: '🎵' },
  { key: 'emotion', label: '情绪标注', icon: '💖' },
  { key: 'conflict', label: '冲突检测', icon: '⚡' },
  { key: 'pleasure', label: '爽点分析', icon: '🎀' },
  { key: 'synthesize', label: '综合输出', icon: '📦' },
]

const pipelineStage = computed(() => props.progressData?.pipeline_stage ?? null)
const pipelineRunning = computed(() => props.progressData?.running ?? false)

const pipelinePercent = computed(() => {
  const stage = pipelineStage.value
  if (!stage) {
    const state = props.progressData?.startup_state
    return state?.progress ?? 0
  }
  const total = stage.total || PIPELINE_STAGES.length
  return Math.round(((stage.stage_num - 1) / total) * 100 + (stage.percent / total))
})
</script>

<template>
  <div v-if="pipelineRunning" class="pipeline-station">
    <div class="pipeline-header">
      <div class="pipeline-header-left">
        <h3>拆书进度</h3>
        <span class="pipeline-header-sub">
          {{ pipelineStage?.current_task || progressData?.startup_state?.message || '分析运行中' }}
        </span>
      </div>
      <div class="pipeline-header-right">
        <span class="pipeline-status">{{ progressData?.startup_state?.status || 'running' }}</span>
        <button class="pipeline-action" title="停止管线" @click="emit('stop')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="4" width="16" height="16" />
          </svg>
        </button>
      </div>
    </div>

    <div class="pipeline-stages-viz">
      <!-- 阶段步骤条 -->
      <div class="pipeline-steps-row">
        <div
          v-for="(s, i) in PIPELINE_STAGES"
          :key="s.key"
          class="pipeline-step"
          :class="{
            completed: pipelineStage && i + 1 < (pipelineStage.stage_num || 0),
            running: pipelineStage && i + 1 === (pipelineStage.stage_num || 0),
            error: pipelineStage && i + 1 === (pipelineStage.stage_num || 0) && pipelineStage.status === 'error',
            pending: !pipelineStage || i + 1 > (pipelineStage.stage_num || 0),
          }"
        >
          <div class="pipeline-step-icon">{{ s.icon }}</div>
          <div class="pipeline-step-label">{{ s.label }}</div>
        </div>
      </div>

      <!-- 进度条 -->
      <div class="pipeline-progress-bar">
        <div class="pipeline-progress-fill animated" :style="{ width: pipelinePercent + '%' }" />
      </div>

      <!-- 进度信息 -->
      <div class="pipeline-info-row">
        <span class="pipeline-info-task">{{ pipelineStage?.current_task || '处理中...' }}</span>
        <span v-if="pipelineStage?.current_book" class="pipeline-info-book">📖 {{ pipelineStage.current_book }}</span>
        <span class="pipeline-info-pct">{{ pipelinePercent }}%</span>
      </div>

      <!-- 已完成书籍 -->
      <div v-if="pipelineStage?.completed_books?.length" class="pipeline-completed-books">
        <span class="pipeline-completed-label">已完成 ({{ pipelineStage.completed_books.length }}):</span>
        <span
          v-for="b in pipelineStage.completed_books.slice(-5)"
          :key="b"
          class="pipeline-book-chip"
        >{{ b }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pipeline-station {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}
.pipeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.pipeline-header-left {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.pipeline-header-left h3 {
  font-size: 14px;
  font-weight: 600;
}
.pipeline-header-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
.pipeline-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pipeline-status {
  font-size: 12px;
  color: var(--success);
  text-transform: uppercase;
}
.pipeline-action {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: var(--surface-hover);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.pipeline-action:hover {
  background: var(--danger);
  color: white;
}
.pipeline-stages-viz {
  padding: 16px;
}
.pipeline-steps-row {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  overflow-x: auto;
}
.pipeline-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 80px;
  padding: 8px 4px;
  border-radius: 8px;
  border: 1px solid var(--border);
  opacity: 0.5;
}
.pipeline-step.completed {
  opacity: 1;
  border-color: var(--success);
  background: rgba(34, 197, 94, 0.08);
}
.pipeline-step.running {
  opacity: 1;
  border-color: var(--accent);
  background: rgba(56, 189, 248, 0.08);
  animation: pulse-border 2s infinite;
}
.pipeline-step.error {
  opacity: 1;
  border-color: var(--danger);
  background: rgba(239, 68, 68, 0.08);
}
.pipeline-step-icon {
  font-size: 18px;
}
.pipeline-step-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}
@keyframes pulse-border {
  0%, 100% { box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.3); }
  50% { box-shadow: 0 0 0 4px rgba(56, 189, 248, 0); }
}
.pipeline-progress-bar {
  height: 6px;
  background: var(--surface-solid);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}
.pipeline-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.pipeline-progress-fill.animated {
  background: linear-gradient(90deg, var(--accent), var(--brand-lavender), var(--accent));
  background-size: 200% 100%;
  animation: gradient-flow 2s linear infinite;
}
@keyframes gradient-flow {
  0% { background-position: 0% 0; }
  100% { background-position: 200% 0; }
}
.pipeline-info-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.pipeline-info-task {
  color: var(--text);
  flex: 1;
}
.pipeline-info-book {
  color: var(--text-secondary);
}
.pipeline-info-pct {
  font-weight: 600;
  color: var(--accent);
}
.pipeline-completed-books {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: 11px;
}
.pipeline-completed-label {
  color: var(--text-secondary);
}
.pipeline-book-chip {
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-hover);
  color: var(--text-secondary);
}
</style>
