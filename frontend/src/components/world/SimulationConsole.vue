<script setup lang="ts">
/**
 * SimulationConsole — 推演控制台
 * 章节范围选择 + 进度条 + 启动/停止/快照
 */
defineProps<{
  currentChapter: number
  factionCount: number
  characterCount: number
  snapshotCount: number
  isSimulating: boolean
  simProgress: number
  simTotalRounds: number
  simFromChapter: number
  simToChapter: number
}>()

const emit = defineEmits<{
  (e: 'update:simFromChapter', v: number): void
  (e: 'update:simToChapter', v: number): void
  (e: 'saveSnapshot'): void
  (e: 'runSimulation'): void
  (e: 'stopSimulation'): void
}>()
</script>

<template>
  <div class="simulation-console">
    <div class="console-body">
      <div class="console-section console-stats">
        <div class="console-section-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
          推演控制台
        </div>
        <div class="stat-row">
          <div class="stat-item">
            <span class="stat-label">当前章节</span>
            <span class="stat-value">{{ currentChapter }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">势力</span>
            <span class="stat-value">{{ factionCount }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">角色</span>
            <span class="stat-value">{{ characterCount }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">快照</span>
            <span class="stat-value">{{ snapshotCount }}</span>
          </div>
        </div>
      </div>

      <div class="console-divider"></div>

      <div class="console-section console-config">
        <div class="console-section-title">推演范围</div>
        <div v-if="isSimulating" class="progress-block">
          <div class="progress-header">
            <span class="progress-status">
              <span class="status-dot"></span>
              推演中
            </span>
            <span class="progress-fraction">{{ simProgress }} / {{ simTotalRounds }} 轮</span>
          </div>
          <div class="sim-progress-bar">
            <div class="sim-progress-fill" :style="{ width: simTotalRounds > 0 ? (simProgress / simTotalRounds * 100) + '%' : '0%' }"></div>
          </div>
        </div>
        <div v-else class="range-inputs">
          <label class="range-label">从第</label>
          <input
            type="number"
            :value="simFromChapter"
            @input="emit('update:simFromChapter', Number(($event.target as HTMLInputElement).value))"
            class="sim-input"
            min="0"
          />
          <label class="range-label">章</label>
          <span class="range-separator">至</span>
          <input
            type="number"
            :value="simToChapter"
            @input="emit('update:simToChapter', Number(($event.target as HTMLInputElement).value))"
            class="sim-input"
            min="1"
          />
          <label class="range-label">章</label>
        </div>
      </div>
    </div>

    <div class="console-actions">
      <button class="btn btn-secondary" @click="emit('saveSnapshot')" :disabled="isSimulating">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
          <circle cx="12" cy="13" r="4" />
        </svg>
        保存快照
      </button>
      <button v-if="isSimulating" class="btn btn-danger" @click="emit('stopSimulation')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="6" y="6" width="12" height="12" rx="2" />
        </svg>
        停止推演
      </button>
      <button v-else class="btn btn-primary" @click="emit('runSimulation')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="5,3 19,12 5,21" />
        </svg>
        启动推演
      </button>
    </div>
  </div>
</template>

<style scoped>
.simulation-console {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 18px 22px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  margin-bottom: 20px;
}

.console-body {
  display: flex;
  align-items: center;
  gap: 22px;
  flex: 1;
}

.console-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.console-section-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.console-divider {
  width: 1px;
  height: 44px;
  background: var(--border);
}

.stat-row {
  display: flex;
  gap: 22px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-muted);
}

.stat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}

.range-inputs {
  display: flex;
  align-items: center;
  gap: 8px;
}

.range-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.range-separator {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0 4px;
}

.sim-input {
  width: 64px;
  padding: 6px 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}

.sim-input:focus {
  outline: none;
  border-color: var(--accent);
}

.progress-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 220px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}

.progress-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--accent);
  font-weight: 600;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.4s ease-in-out infinite;
}

.progress-fraction {
  color: var(--text-secondary);
}

.sim-progress-bar {
  width: 220px;
  height: 6px;
  background: var(--surface-faint);
  border-radius: 3px;
  overflow: hidden;
}

.sim-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), rgba(var(--accent-rgb), 0.7));
  border-radius: 3px;
  transition: width 0.3s ease;
}

.console-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.console-actions .btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@media (max-width: 900px) {
  .simulation-console {
    flex-direction: column;
    align-items: stretch;
  }
  .console-body {
    flex-direction: column;
    align-items: flex-start;
  }
  .console-divider {
    width: 100%;
    height: 1px;
  }
  .console-actions {
    justify-content: flex-end;
  }
}
</style>
