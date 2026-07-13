/**
 * 世界推演 Store — 管理势力/角色/推演状态
 *
 * A3: 添加从后端 API 加载真实数据的 actions
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ProjectAPI } from '@/api/project'
import { WorldAPI } from '@/api/world'
import type {
  Faction,
  Character,
  WorldSnapshot,
  SimulationEvent,
  Region,
  FactionRuntimeState,
  CharacterState,
} from '@/types'

// 后端 world_state 返回的角色运行时状态（与 types/index.ts 的 CharacterState 一致）

export const useWorldStore = defineStore('world', () => {
  // ── State ──
  const factions = ref<Faction[]>([])
  const characters = ref<Character[]>([])
  const regions = ref<Region[]>([])
  const snapshots = ref<WorldSnapshot[]>([])
  const currentSnapshot = ref<WorldSnapshot | null>(null)
  const simulationEvents = ref<SimulationEvent[]>([])
  const isSimulating = ref(false)
  const isLoaded = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const selectedFactionId = ref<string | null>(null)
  const selectedCharacterId = ref<string | null>(null)
  const currentChapter = ref(0)

  // ── Computed ──
  const selectedFaction = computed(() =>
    factions.value.find((f) => f.id === selectedFactionId.value) ?? null
  )

  const selectedCharacter = computed(() =>
    characters.value.find((c) => c.name === selectedCharacterId.value) ?? null
  )

  const factionCount = computed(() => factions.value.length)
  const characterCount = computed(() => characters.value.length)

  // ── Actions: 从后端加载 ──

  /**
   * 从后端加载项目数据：factions + characters + world_state
   * 合并静态定义与运行时状态
   */
  async function loadProjectData(projectId: string) {
    loading.value = true
    error.value = null

    try {
      // 并行加载项目数据 + 世界状态
      const [projectRes, worldStateRes] = await Promise.all([
        ProjectAPI.get(projectId),
        WorldAPI.getState(projectId),
      ])

      if (!projectRes.ok || !projectRes.data) {
        throw new Error(projectRes.error ?? '加载项目失败')
      }

      const project = projectRes.data

      // 合并静态 factions 与运行时状态
      let factionStates: FactionRuntimeState[] = []
      let charStates: CharacterState[] = []

      if (worldStateRes.ok && worldStateRes.data) {
        const ws = worldStateRes.data
        factionStates = ws.factions_state ?? []
        charStates = ws.characters_state ?? []
        currentChapter.value = ws.chapter ?? 0
        snapshots.value = ws.snapshots ?? []
        regions.value = ws.regions ?? []
      }

      // 合并：静态定义 + 运行时状态
      factions.value = (project.factions ?? []).map((fac: Faction) => {
        const runtime = factionStates.find((fs) => fs.id === fac.id)
        return {
          ...fac,
          state: runtime ? {
            stability: runtime.stability,
            morale: runtime.morale,
            treasury: runtime.treasury,
            threat_level: runtime.threat_level,
            power_level: runtime.power_level,
          } : fac.state,
        }
      })

      characters.value = (project.characters ?? []).map((char: Character) => {
        const runtime = charStates.find((cs) => cs.name === char.name)
        return {
          ...char,
          dynamic_state: runtime ? {
            faction_id: runtime.faction_id,
            health: runtime.health,
            mood: runtime.mood,
            location: runtime.location,
            recent_actions: runtime.recent_actions,
          } : char.dynamic_state,
        }
      })

      isLoaded.value = true
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** 加载推演事件 — 使用专用 GET /world_state/events 端点 */
  async function loadEvents(projectId: string) {
    const res = await WorldAPI.getEvents(projectId)
    if (res.ok && res.data) {
      simulationEvents.value = res.data.events ?? []
    }
  }

  /** 保存快照 — 调用专用 POST /world_state/snapshot 端点 */
  async function saveSnapshot(projectId: string, chapter: number) {
    return WorldAPI.saveSnapshot(projectId, chapter)
  }

  /** 获取快照差异 */
  async function getDiff(projectId: string, fromChapter: number, toChapter: number) {
    return WorldAPI.getDiff(projectId, fromChapter, toChapter)
  }

  // ── Actions: 本地操作 ──

  function setFactions(list: Faction[]) {
    factions.value = list
  }

  function setCharacters(list: Character[]) {
    characters.value = list
  }

  function setRegions(list: Region[]) {
    regions.value = list
  }

  function selectFaction(id: string | null) {
    selectedFactionId.value = id
  }

  function selectCharacter(name: string | null) {
    selectedCharacterId.value = name
  }

  function addFaction(faction: Faction) {
    factions.value.push(faction)
  }

  function updateFaction(id: string, updates: Partial<Faction>) {
    const idx = factions.value.findIndex((f) => f.id === id)
    if (idx >= 0) {
      factions.value[idx] = { ...factions.value[idx], ...updates }
    }
  }

  function removeFaction(id: string) {
    factions.value = factions.value.filter((f) => f.id !== id)
    if (selectedFactionId.value === id) {
      selectedFactionId.value = null
    }
  }

  function startSimulation() {
    isSimulating.value = true
    simulationEvents.value = []
  }

  function addSimulationEvent(event: SimulationEvent) {
    simulationEvents.value.push(event)
  }

  function completeSimulation() {
    isSimulating.value = false
  }

  function resetSimulation() {
    isSimulating.value = false
    simulationEvents.value = []
  }

  function clearData() {
    factions.value = []
    characters.value = []
    regions.value = []
    snapshots.value = []
    simulationEvents.value = []
    isLoaded.value = false
    currentChapter.value = 0
    selectedFactionId.value = null
    selectedCharacterId.value = null
  }

  return {
    // State
    factions,
    characters,
    regions,
    snapshots,
    currentSnapshot,
    simulationEvents,
    isSimulating,
    isLoaded,
    loading,
    error,
    selectedFactionId,
    selectedCharacterId,
    currentChapter,
    // Computed
    selectedFaction,
    selectedCharacter,
    factionCount,
    characterCount,
    // Server Actions
    loadProjectData,
    loadEvents,
    saveSnapshot,
    getDiff,
    // Local Actions
    setFactions,
    setCharacters,
    setRegions,
    selectFaction,
    selectCharacter,
    addFaction,
    updateFaction,
    removeFaction,
    startSimulation,
    addSimulationEvent,
    completeSimulation,
    resetSimulation,
    clearData,
  }
})
