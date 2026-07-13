<script setup lang="ts">
/**
 * WorldView — WSE 世界推演主页面
 *
 * A3: 从后端 API 加载真实项目数据
 * A4: 集成 Cytoscape 关系图
 * A5: 推演控制台
 */
import { ref, computed, onMounted, watch, onUnmounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useWorldStore } from '@/stores/world'
import { useUiStore } from '@/stores/ui'
import { useSystemStore } from '@/stores/system'
import FactionGraph from '@/components/world/FactionGraph.vue'
import CharacterGraph from '@/components/world/CharacterGraph.vue'
import SimulationConsole from '@/components/world/SimulationConsole.vue'
import SimulationLog from '@/components/world/SimulationLog.vue'
import { WorldAPI } from '@/api/world'
import AppSelect from '@/components/common/AppSelect.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import TabBar from '@/components/common/TabBar.vue'
import type { SimulationEvent } from '@/types'

const projectStore = useProjectStore()
const worldStore = useWorldStore()
const uiStore = useUiStore()
const systemStore = useSystemStore()

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

const projectOptions = computed(() => [
  { value: '', label: '请选择项目...' },
  ...projectStore.projects.map((p) => ({
    value: p.id,
    label: `${p.title}${p.is_demo ? ' (示例)' : ''}`,
  })),
])

// ── 生命周期 ──
onMounted(async () => {
  await projectStore.loadProjects()
  // 优先跟随当前项目，否则回退到 demo 或第一个项目
  if (projectStore.currentProject?.id) {
    selectedProjectId.value = projectStore.currentProject.id
  } else {
    const demo = projectStore.projects.find((p) => p.is_demo)
    if (demo) {
      selectedProjectId.value = demo.id
    } else if (projectStore.projects.length > 0) {
      selectedProjectId.value = projectStore.projects[0].id
    }
  }
})

watch(selectedProjectId, async (id) => {
  if (!id) return
  if (id === projectStore.currentProject?.id) {
    // 当前项目已作为 store 状态加载，避免重复请求
    return
  }
  await worldStore.loadProjectData(id)
  await worldStore.loadEvents(id)
})

watch(() => projectStore.currentProject?.id, async (newId) => {
  if (newId) {
    selectedProjectId.value = newId
    await worldStore.loadProjectData(newId)
    await worldStore.loadEvents(newId)
  } else {
    selectedProjectId.value = ''
    worldStore.clearData()
    diffResult.value = null
    exportResult.value = null
    showExportPanel.value = false
    exporting.value = false
    simProgress.value = 0
    simTotalRounds.value = 0
  }
}, { immediate: true })

// ── 推演 ──
const simFromChapter = ref(0)
const simToChapter = ref(5)
const simProgress = ref(0)
const simTotalRounds = ref(0)
let cancelSimulation: (() => void) | null = null

async function doRunSimulation() {
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

async function runSimulation() {
  if (!selectedProjectId.value) return

  const ok = await systemStore.ensureModelRunning('世界推演')
  if (!ok) return

  await doRunSimulation()
}

function stopSimulation() {
  cleanupSimulation()
  uiStore.showToast('推演已停止', 'info')
}

function cleanupSimulation() {
  if (cancelSimulation) {
    cancelSimulation()
    cancelSimulation = null
  }
  worldStore.completeSimulation()
}

onUnmounted(() => {
  cleanupSimulation()
})

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

const tabs = [
  { key: 'factions', label: '势力', icon: 'flag' },
  { key: 'characters', label: '角色', icon: 'user' },
  { key: 'graph', label: '关系图谱', icon: 'graph' },
  { key: 'simulation', label: '推演日志', icon: 'log' },
] as const

function tabIcon(name: string) {
  const icons: Record<string, string> = {
    flag: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7',
    user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
    graph: 'M18 20V10M12 20V4M6 20v-6',
    log: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8',
  }
  return icons[name] || ''
}

function typeColor(type?: string): string {
  const colors: Record<string, string> = {
    '神秘组织': '#A78BFA',
    '官方组织': '#38BDF8',
    '帮派': '#F59E0B',
    '军事组织': '#EF4444',
    '宗门': '#22D3EE',
    '帝国': '#818CF8',
    '议会': '#22c55e',
  }
  return colors[type || ''] || '#94a3b8'
}
</script>

<template>
  <div class="world-view">
    <!-- 指挥台页头 -->
    <div class="command-header">
      <div class="command-title">
        <div class="command-title-main">
          <h2>世界推演</h2>
          <span v-if="worldStore.isLoaded" class="command-breadcrumb">
            第 {{ worldStore.currentChapter }} 章 · {{ worldStore.factionCount }} 势力 · {{ worldStore.characterCount }} 角色
          </span>
        </div>
      </div>
      <div class="command-project">
        <AppSelect
          v-model="selectedProjectId"
          :options="projectOptions"
          class="project-select"
        />
        <span v-if="worldStore.loading" class="status-pill loading">
          <span class="status-dot pulse"></span>加载中
        </span>
        <span v-if="worldStore.error" class="status-pill error">{{ worldStore.error }}</span>
        <span
          class="status-pill"
          :class="{ 'status-online': systemStore.modelRunning, 'status-offline': !systemStore.modelRunning }"
          :title="systemStore.modelRunning ? systemStore.modelName : '点击启动推演时将提示启动'"
        >
          <span class="status-dot" :class="{ active: systemStore.modelRunning }"></span>
          {{ systemStore.modelRunning ? systemStore.modelName + ' 运行中' : '模型未运行' }}
        </span>
      </div>
    </div>

    <!-- 加载中 / 空状态 -->
    <EmptyState
      v-if="!selectedProjectId"
      icon="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"
      title="请选择一个项目开始推演"
      description="世界状态、势力关系与角色动态将在此聚合呈现。"
    />

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
      <TabBar
        v-model="activeTab"
        :options="tabs.map(t => ({ label: t.label, value: t.key, icon: tabIcon(t.icon) }))"
      />

      <!-- 势力面板 -->
      <div v-show="activeTab === 'factions'" class="panel-content">
        <div class="panel-heading">
          <h3>势力状态</h3>
          <span class="panel-count">{{ worldStore.factions.length }} 个势力</span>
        </div>
        <div class="entity-grid" v-if="worldStore.factions.length">
          <div
            v-for="fac in worldStore.factions"
            :key="fac.id || fac.name"
            class="entity-card"
            :class="{ selected: worldStore.selectedFactionId === (fac.id || fac.name) }"
            @click="worldStore.selectFaction(fac.id || fac.name)"
          >
            <div class="entity-header">
              <div class="entity-identity">
                <div class="entity-avatar" :style="{ background: typeColor(fac.type) }">
                  <span>{{ fac.name.slice(0, 1) }}</span>
                </div>
                <div>
                  <div class="entity-name">{{ fac.name }}</div>
                  <div class="entity-type" v-if="fac.type">{{ fac.type }}</div>
                </div>
              </div>
              <span class="power-badge" v-if="fac.state?.power_level">Lv.{{ fac.state.power_level }}</span>
            </div>
            <p class="entity-desc">{{ fac.desc }}</p>
            <div v-if="fac.state" class="state-bars">
              <div class="state-bar">
                <span class="bar-label">稳定</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.stability), background: stateColor(fac.state.stability) }"></div></div>
                <span class="bar-value">{{ formatPercent(fac.state.stability) }}</span>
              </div>
              <div class="state-bar">
                <span class="bar-label">士气</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.morale), background: stateColor(fac.state.morale) }"></div></div>
                <span class="bar-value">{{ formatPercent(fac.state.morale) }}</span>
              </div>
              <div class="state-bar">
                <span class="bar-label">财政</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.treasury), background: stateColor(fac.state.treasury) }"></div></div>
                <span class="bar-value">{{ formatPercent(fac.state.treasury) }}</span>
              </div>
              <div class="state-bar">
                <span class="bar-label">威胁</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: formatPercent(fac.state.threat_level), background: stateColor(fac.state.threat_level) }"></div></div>
                <span class="bar-value">{{ formatPercent(fac.state.threat_level) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-inline">
          <div class="empty-inline-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.25"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7"/></svg>
          </div>
          <p>暂无势力数据</p>
          <span class="text-muted">启动推演或导入项目以生成势力</span>
        </div>
      </div>

      <!-- 角色面板 -->
      <div v-show="activeTab === 'characters'" class="panel-content">
        <div class="panel-heading">
          <h3>角色动态</h3>
          <span class="panel-count">{{ worldStore.characters.length }} 个角色</span>
        </div>
        <div class="entity-grid" v-if="worldStore.characters.length">
          <div
            v-for="char in worldStore.characters"
            :key="char.name"
            class="entity-card"
            :class="{ selected: worldStore.selectedCharacterId === char.name }"
            @click="worldStore.selectCharacter(char.name)"
          >
            <div class="entity-header">
              <div class="entity-identity">
                <div class="entity-avatar avatar-character">
                  <span>{{ char.name.slice(0, 1) }}</span>
                </div>
                <div>
                  <div class="entity-name">{{ char.name }}</div>
                  <div class="entity-type role-tag" :class="char.role">{{ char.role || '角色' }}</div>
                </div>
              </div>
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
                <span class="bar-value">{{ formatPercent(char.dynamic_state.health) }}</span>
              </div>
              <div class="char-meta">
                <span class="meta-pill"><b>心情</b>{{ char.dynamic_state.mood }}</span>
                <span class="meta-pill"><b>位置</b>{{ char.dynamic_state.location }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-inline">
          <div class="empty-inline-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.25"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"/></svg>
          </div>
          <p>暂无角色数据</p>
          <span class="text-muted">启动推演或导入项目以生成角色</span>
        </div>
      </div>

      <!-- 关系图谱 -->
      <div v-show="activeTab === 'graph'" class="panel-content">
        <div class="graph-layout">
          <div class="graph-card">
            <div class="graph-card-header">
              <h3>势力关系图</h3>
              <span class="graph-hint">节点大小 = 实力，连线 = 关系强度</span>
            </div>
            <FactionGraph :factions="worldStore.factions" @select="worldStore.selectFaction($event.id || $event.name)" />
          </div>
          <div class="graph-card">
            <div class="graph-card-header">
              <h3>角色关系图</h3>
              <span class="graph-hint">点击节点查看角色详情</span>
            </div>
            <CharacterGraph :characters="worldStore.characters" @select="worldStore.selectCharacter($event.name)" />
          </div>
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
  width: 100%;
  margin: 0 auto;
}

/* ── 指挥台页头 ── */
.command-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.command-title-main {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.command-title h2 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
}

.command-breadcrumb {
  color: var(--text-secondary);
  font-size: 13px;
}

.command-project {
  display: flex;
  align-items: center;
  gap: 10px;
}

.project-select {
  min-width: 220px;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
}

.project-select:focus {
  outline: none;
  border-color: var(--accent);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}

.status-pill.error {
  color: var(--danger);
  border-color: rgba(var(--danger-rgb), 0.3);
  background: rgba(var(--danger-rgb), 0.06);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

.status-dot.pulse {
  animation: pulse 1.6s ease-in-out infinite;
}

.status-dot.active {
  background: var(--success);
}

.status-pill.status-online {
  color: var(--success);
  border-color: rgba(var(--success-rgb), 0.35);
  background: rgba(var(--success-rgb), 0.08);
}

.status-pill.status-offline {
  color: var(--text-muted);
}

/* ── 面板内容 ── */
.panel-content {
  animation: fadeIn 0.25s ease;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.panel-heading h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}

.panel-count {
  font-size: 12px;
  color: var(--text-muted);
  padding: 3px 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
}

/* ── 实体卡片 ── */
.entity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.entity-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 14px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.entity-card:hover {
  border-color: var(--accent);
  background: var(--surface);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.entity-card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent), 0 8px 24px rgba(var(--accent-rgb), 0.12);
}

.entity-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.entity-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.entity-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  text-shadow: 0 1px 2px rgba(0,0,0,0.2);
}

.avatar-character {
  background: linear-gradient(135deg, var(--accent), rgba(var(--accent-rgb), 0.6));
}

.entity-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.3;
}

.entity-type {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.role-tag.主角 { color: var(--accent); }
.role-tag.女主 { color: var(--success); }
.role-tag.导师 { color: var(--indigo); }
.role-tag.反派 { color: var(--danger); }
.role-tag.配角 { color: var(--warning); }

.entity-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.55;
  margin: 0 0 14px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── 状态条 ── */
.state-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.state-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bar-label {
  font-size: 11px;
  color: var(--text-muted);
  width: 30px;
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
  transition: width 0.4s ease;
}

.bar-value {
  font-size: 11px;
  color: var(--text-secondary);
  width: 32px;
  text-align: right;
  flex-shrink: 0;
}

.power-badge {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 20px;
  background: rgba(var(--indigo-rgb), 0.12);
  color: var(--indigo);
  font-weight: 600;
  flex-shrink: 0;
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
  gap: 10px;
}

.char-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-pill {
  font-size: 11px;
  color: var(--text-secondary);
  padding: 4px 10px;
  background: var(--surface-faint);
  border-radius: 20px;
}

.meta-pill b {
  color: var(--text-muted);
  margin-right: 6px;
  font-weight: 500;
}

/* ── 关系图 ── */
.graph-layout {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.graph-card {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.graph-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.graph-card-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}

.graph-hint {
  font-size: 11px;
  color: var(--text-muted);
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-icon {
  color: var(--text-muted);
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state p {
  font-size: 16px;
  color: var(--text);
  font-weight: 500;
  margin: 0 0 6px 0;
}

.empty-state .text-muted {
  font-size: 13px;
  color: var(--text-muted);
}

.empty-inline {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 60px 20px;
  color: var(--text-secondary);
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: 14px;
}

.empty-inline-icon {
  color: var(--text-muted);
  margin-bottom: 12px;
  opacity: 0.45;
}

.empty-inline p {
  margin: 0 0 4px 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.empty-inline .text-muted {
  font-size: 12px;
  color: var(--text-muted);
}

.text-muted {
  color: var(--text-muted);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 1024px) {
  .graph-layout {
    grid-template-columns: 1fr;
  }
  .command-header {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (max-width: 768px) {
  .entity-grid {
    grid-template-columns: 1fr;
  }
  .tab-bar {
    width: 100%;
    overflow-x: auto;
  }
}
</style>
