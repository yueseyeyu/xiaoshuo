<script setup lang="ts">
/**
 * WorldView — WSE 世界推演主页面
 *
 * A3: 从后端 API 加载真实项目数据
 * A4: 集成 Cytoscape 关系图
 * A5: 推演控制台
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useWorldStore } from '@/stores/world'
import { useUiStore } from '@/stores/ui'
import FactionGraph from '@/components/world/FactionGraph.vue'
import CharacterGraph from '@/components/world/CharacterGraph.vue'
import SimulationConsole from '@/components/world/SimulationConsole.vue'
import SimulationLog from '@/components/world/SimulationLog.vue'
import { WorldAPI } from '@/api/world'
import type { SimulationEvent } from '@/types'

const projectStore = useProjectStore()
const worldStore = useWorldStore()
const uiStore = useUiStore()

const activeTab = ref<'factions' | 'characters' | 'graph' | 'simulation'>('factions')

const diffFromChapter = ref(0)
const diffToChapter = ref(0)
const diffResult = ref<unknown>(null)

// ── 导出大纲 (v8.6 WSE 深化) ──
const exportFromChapter = ref(0)
const exportToChapter = ref(5)
const exportResult = ref<{
  world_context: string
  chapter_drafts: Array<{
    chapter: number
    events: SimulationEvent[]
    faction_summary: string
    character_summary: string
    suggested_outline: string
  }>
} | null>(null)
const exporting = ref(false)
const showExportPanel = ref(false)

// ── 项目选择 ──
const selectedProjectId = ref<string>('')

// ── 生命周期 ──
onMounted(async () => {
  await projectStore.loadProjects()
  // 自动选中 demo 项目或第一个项目
  const demo = projectStore.projects.find((p) => p.is_demo)
  if (demo) {
    selectedProjectId.value = demo.id
  } else if (projectStore.projects.length > 0) {
    selectedProjectId.value = projectStore.projects[0].id
  }
})

watch(selectedProjectId, async (id) => {
  if (id) {
    await worldStore.loadProjectData(id)
    await worldStore.loadEvents(id)
  }
})

// ── 推演 ──
const simFromChapter = ref(0)
const simToChapter = ref(5)
const simProgress = ref(0)
const simTotalRounds = ref(0)
let cancelSimulation: (() => void) | null = null

async function runSimulation() {
  if (!selectedProjectId.value) return

  worldStore.startSimulation()
  simProgress.value = 0
  simTotalRounds.value = simToChapter.value - simFromChapter.value
  activeTab.value = 'simulation'

  cancelSimulation = await WorldAPI.startSimulation(
    selectedProjectId.value,
    simFromChapter.value,
    simToChapter.value,
    {
      onEvent: (event: SimulationEvent) => {
        worldStore.addSimulationEvent(event)
      },
      onProgress: (data) => {
        if (data.round && data.total_rounds) {
          simProgress.value = data.round
          simTotalRounds.value = data.total_rounds
        }
      },
      onComplete: async () => {
        worldStore.completeSimulation()
        uiStore.showToast('推演完成！', 'success')
        // 重新加载项目数据以刷新势力/角色状态（保留已积累的推演事件）
        if (selectedProjectId.value) {
          await worldStore.loadProjectData(selectedProjectId.value)
        }
      },
      onError: (error) => {
        worldStore.completeSimulation()
        uiStore.showToast('推演失败: ' + error, 'error')
      },
    }
  )
}

function stopSimulation() {
  if (cancelSimulation) {
    cancelSimulation()
    cancelSimulation = null
  }
  worldStore.completeSimulation()
  uiStore.showToast('推演已停止', 'info')
}

async function saveSnapshot() {
  if (!selectedProjectId.value) return
  const ch = worldStore.currentChapter + 1
  const res = await worldStore.saveSnapshot(selectedProjectId.value, ch)
  if (res.ok) {
    uiStore.showToast(`第${ch}章快照已保存`, 'success')
  } else {
    uiStore.showToast('保存快照失败', 'error')
  }
}

async function loadDiff() {
  if (!selectedProjectId.value) return
  const res = await worldStore.getDiff(
    selectedProjectId.value,
    diffFromChapter.value,
    diffToChapter.value
  )
  if (res.ok && res.data) {
    diffResult.value = res.data
    uiStore.showToast('差异对比完成', 'success')
  } else {
    uiStore.showToast('差异对比失败: ' + (res.error ?? '未知错误'), 'error')
  }
}

function formatPercent(val: number | undefined): string {
  if (val === undefined) return '--'
  return `${Math.round(val * 100)}%`
}

function stateColor(val: number | undefined): string {
  if (val === undefined) return 'var(--text-muted)'
  if (val >= 0.7) return 'var(--success)'
  if (val >= 0.4) return 'var(--warning)'
  return 'var(--danger)'
}

const diffChanges = computed(() => {
  if (!diffResult.value) return []
  const data = diffResult.value as { changes?: Array<Record<string, unknown>> }
  return data.changes ?? []
})

// ── 导出大纲 ──
async function exportToOutline() {
  if (!selectedProjectId.value) return
  exporting.value = true
  showExportPanel.value = true

  const res = await WorldAPI.exportToOutline(
    selectedProjectId.value,
    exportFromChapter.value,
    exportToChapter.value,
  )

  if (res.ok && res.data) {
    exportResult.value = res.data
    uiStore.showToast(`已导出 ${res.data.chapter_drafts.length} 章大纲草稿`, 'success')
  } else {
    uiStore.showToast('导出大纲失败: ' + (res.error ?? '未知错误'), 'error')
  }
  exporting.value = false
}
</script>

<template>
  <div class="world-view">
    <!-- 页头 -->
    <div class="page-header">
      <h2>世界推演</h2>
      <span class="text-muted" v-if="worldStore.isLoaded">
        第 {{ worldStore.currentChapter }} 章 · {{ worldStore.factionCount }} 势力 · {{ worldStore.characterCount }} 角色
      </span>
    </div>

    <!-- 项目选择器 -->
    <div class="project-selector">
      <label>选择项目：</label>
      <select v-model="selectedProjectId" class="project-select">
        <option value="" disabled>请选择...</option>
        <option
          v-for="p in projectStore.projects"
          :key="p.id"
          :value="p.id"
        >
          {{ p.title }}{{ p.is_demo ? ' (示例)' : '' }}
        </option>
      </select>
      <span v-if="worldStore.loading" class="loading-text">加载中...</span>
      <span v-if="worldStore.error" class="error-text">{{ worldStore.error }}</span>
    </div>

    <!-- 加载中 / 空状态 -->
    <div v-if="!selectedProjectId" class="empty-state">
      <div class="empty-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10" /><path d="M12 2a10 10 0 0 1 10 10H12V2z" />
        </svg>
      </div>
      <p>请选择一个项目开始</p>
    </div>

    <template v-else-if="worldStore.isLoaded">
      <!-- 推演控制台 -->
      <SimulationConsole
        :current-chapter="worldStore.currentChapter"
        :faction-count="worldStore.factionCount"
        :character-count="worldStore.characterCount"
        :snapshot-count="worldStore.snapshots.length"
        :is-simulating="worldStore.isSimulating"
        :sim-progress="simProgress"
        :sim-total-rounds="simTotalRounds"
        :sim-from-chapter="simFromChapter"
        :sim-to-chapter="simToChapter"
        @update:sim-from-chapter="simFromChapter = $event"
        @update:sim-to-chapter="simToChapter = $event"
        @save-snapshot="saveSnapshot"
        @run-simulation="runSimulation"
        @stop-simulation="stopSimulation"
      />

      <!-- Tab 切换 -->
      <div class="tab-bar">
        <button
          v-for="tab in [
            { key: 'factions', label: '势力面板' },
            { key: 'characters', label: '角色面板' },
            { key: 'graph', label: '关系图谱' },
            { key: 'simulation', label: '推演日志' },
          ]"
          :key="tab.key"
          class="tab-btn"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key as typeof activeTab"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- 势力面板 -->
      <div v-show="activeTab === 'factions'" class="panel-content">
        <div class="entity-grid" v-if="worldStore.factions.length">
          <div
            v-for="fac in worldStore.factions"
            :key="fac.id || fac.name"
            class="entity-card"
            :class="{ selected: worldStore.selectedFactionId === (fac.id || fac.name) }"
            @click="worldStore.selectFaction(fac.id || fac.name)"
          >
            <div class="entity-header">
              <span class="entity-name">{{ fac.name }}</span>
              <span class="entity-type" v-if="fac.type">{{ fac.type }}</span>
            </div>
            <p class="entity-desc">{{ fac.desc }}</p>
            <div v-if="fac.state" class="state-bars">
              <div class="state-bar">
                <span class="bar-label">稳定</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.stability), background: stateColor(fac.state.stability) }"></div></div>
              </div>
              <div class="state-bar">
                <span class="bar-label">士气</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.morale), background: stateColor(fac.state.morale) }"></div></div>
              </div>
              <div class="state-bar">
                <span class="bar-label">财政</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.treasury), background: stateColor(fac.state.treasury) }"></div></div>
              </div>
              <div class="state-bar">
                <span class="bar-label">威胁</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.threat_level), background: stateColor(fac.state.threat_level) }"></div></div>
              </div>
            </div>
            <div class="entity-footer">
              <span class="power-badge" v-if="fac.state?.power_level">实力 Lv.{{ fac.state.power_level }}</span>
            </div>
          </div>
        </div>
        <div v-else class="empty-inline">暂无势力数据</div>
      </div>

      <!-- 角色面板 -->
      <div v-show="activeTab === 'characters'" class="panel-content">
        <div class="entity-grid" v-if="worldStore.characters.length">
          <div
            v-for="char in worldStore.characters"
            :key="char.name"
            class="entity-card"
            :class="{ selected: worldStore.selectedCharacterId === char.name }"
            @click="worldStore.selectCharacter(char.name)"
          >
            <div class="entity-header">
              <span class="entity-name">{{ char.name }}</span>
              <span class="entity-type role-tag" :class="char.role">{{ char.role }}</span>
            </div>
            <p class="entity-desc">{{ char.desc }}</p>
            <div class="char-ability" v-if="char.ability">
              <span class="ability-label">能力</span>
              <span class="ability-value">{{ char.ability }}</span>
            </div>
            <div v-if="char.dynamic_state" class="char-state">
              <div class="state-bar">
                <span class="bar-label">生命</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(char.dynamic_state.health), background: stateColor(char.dynamic_state.health) }"></div></div>
              </div>
              <div class="char-meta">
                <span>心情: {{ char.dynamic_state.mood }}</span>
                <span>位置: {{ char.dynamic_state.location }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-inline">暂无角色数据</div>
      </div>

      <!-- 关系图谱 -->
      <div v-show="activeTab === 'graph'" class="panel-content">
        <div class="graph-section">
          <h3 class="graph-title">势力关系图</h3>
          <FactionGraph :factions="worldStore.factions" @select="worldStore.selectFaction($event.id || $event.name)" />
        </div>
        <div class="graph-section">
          <h3 class="graph-title">角色关系图</h3>
          <CharacterGraph :characters="worldStore.characters" @select="worldStore.selectCharacter($event.name)" />
        </div>
      </div>

      <!-- 推演日志 -->
      <SimulationLog
        v-show="activeTab === 'simulation'"
        :diff-from-chapter="diffFromChapter"
        :diff-to-chapter="diffToChapter"
        :diff-changes="diffChanges"
        :export-from-chapter="exportFromChapter"
        :export-to-chapter="exportToChapter"
        :exporting="exporting"
        :show-export-panel="showExportPanel"
        :export-result="exportResult"
        :simulation-events="worldStore.simulationEvents"
        @update:diff-from-chapter="diffFromChapter = $event"
        @update:diff-to-chapter="diffToChapter = $event"
        @update:export-from-chapter="exportFromChapter = $event"
        @update:export-to-chapter="exportToChapter = $event"
        @load-diff="loadDiff"
        @export-to-outline="exportToOutline"
      />
    </template>
  </div>
</template>

<style scoped>
.world-view {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.page-header h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}

.text-muted {
  color: var(--text-muted);
  font-size: 13px;
}

/* ── 项目选择器 ── */
.project-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
}

.project-selector label {
  font-size: 13px;
  color: var(--text-secondary);
}

.project-select {
  padding: 6px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  min-width: 200px;
}

.project-select:focus {
  outline: none;
  border-color: var(--accent);
}

.loading-text {
  font-size: 12px;
  color: var(--text-muted);
}

.error-text {
  font-size: 12px;
  color: var(--danger);
}

/* ── Tab ── */
.tab-bar {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.tab-btn {
  padding: 8px 16px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn:hover { color: var(--text); }

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

/* ── 实体卡片 ── */
.entity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.entity-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.15s;
}

.entity-card:hover {
  border-color: var(--border-hover);
  background: var(--surface-hover);
}

.entity-card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.entity-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.entity-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.entity-type {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--surface-highlight);
  color: var(--text-secondary);
}

.role-tag.主角 { background: rgba(56,189,248,0.15); color: var(--accent); }
.role-tag.女主 { background: rgba(34,197,94,0.15); color: var(--success); }
.role-tag.导师 { background: rgba(129,140,248,0.15); color: var(--indigo); }
.role-tag.反派 { background: rgba(239,68,68,0.15); color: var(--danger); }
.role-tag.配角 { background: rgba(245,158,11,0.15); color: var(--warning); }

.entity-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 12px 0;
}

/* ── 状态条 ── */
.state-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.state-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bar-label {
  font-size: 11px;
  color: var(--text-muted);
  width: 28px;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 6px;
  background: var(--surface-faint);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.entity-footer {
  display: flex;
  justify-content: flex-end;
}

.power-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(129,140,248,0.15);
  color: var(--indigo);
  font-weight: 600;
}

.char-ability {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 12px;
}

.ability-label { color: var(--text-muted); }
.ability-value { color: var(--brand-lavender); font-weight: 500; }

.char-state {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.char-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}

/* ── 关系图 ── */
.graph-section {
  margin-bottom: 24px;
}

.graph-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.empty-icon { color: var(--text-muted); margin-bottom: 12px; }

.empty-state p {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0 0 4px 0;
}

.empty-inline {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 14px;
}
</style>
