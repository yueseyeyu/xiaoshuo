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
    <div class="console-left">
      <div class="console-title">推演控制台</div>
      <div class="console-meta">
        <span class="meta-item">
          <span class="meta-label">章节</span>
          <span class="meta-value">{{ currentChapter }}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">势力</span>
          <span class="meta-value">{{ factionCount }}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">角色</span>
          <span class="meta-value">{{ characterCount }}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">快照</span>
          <span class="meta-value">{{ snapshotCount }}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">状态</span>
          <span class="meta-value" :class="{ active: isSimulating }">
            {{ isSimulating ? `推演中 ${simProgress}/${simTotalRounds}` : '待命' }}
          </span>
        </span>
      </div>
      <div class="sim-controls" v-if="isSimulating">
        <div class="sim-progress-bar">
          <div class="sim-progress-fill" :style="{ width: simTotalRounds > 0 ? (simProgress / simTotalRounds * 100) + '%' : '0%' }"></div>
        </div>
      </div>
      <div class="sim-controls" v-else>
        <label class="sim-param">推演从第</label>
        <input type="number" :value="simFromChapter" @input="emit('update:simFromChapter', Number(($event.target as HTMLInputElement).value))" class="sim-input" min="0" />
        <label class="sim-param">章到第</label>
        <input type="number" :value="simToChapter" @input="emit('update:simToChapter', Number(($event.target as HTMLInputElement).value))" class="sim-input" min="1" />
        <label class="sim-param">章</label>
      </div>
    </div>
    <div class="console-right">
      <button class="btn btn-ghost" @click="emit('saveSnapshot')" :disabled="isSimulating">保存快照</button>
      <button v-if="isSimulating" class="btn btn-danger" @click="emit('stopSimulation')">停止</button>
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
  align-items: flex-start;
  padding: 16px 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 16px;
  gap: 16px;
}

.console-left { flex: 1; }

.console-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}

.console-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 8px;
}

.meta-item { display: flex; align-items: center; gap: 4px; }
.meta-label { font-size: 12px; color: var(--text-secondary); }
.meta-value { font-size: 13px; font-weight: 600; color: var(--text); }
.meta-value.active { color: var(--accent); }

.sim-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.sim-param { font-size: 12px; color: var(--text-secondary); }
.sim-input {
  width: 56px;
  padding: 4px 6px;
  font-size: 13px;
  color: var(--text);
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 4px;
  text-align: center;
}

.sim-progress-bar {
  flex: 1;
  height: 6px;
  background: var(--surface);
  border-radius: 3px;
  overflow: hidden;
}

.sim-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.console-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>