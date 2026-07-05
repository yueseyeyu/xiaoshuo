<script setup lang="ts">
/**
 * DesignView — 设计页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - 子页签：粗纲 / 细纲 / 世界观 / 势力 / 角色
 * - 粗纲：卷卡片网格（标题/范围/摘要/进度/标签）
 * - 细纲：段卡片（目标/冲突/结果 + 钩子/爽点/伏笔/期待感 + 场景列表）
 * - 世界观：核心设定 + 能力体系 + 维度卡片
 * - 势力：SVG 关系图 + 势力卡片列表
 * - 角色：SVG 关系图 + 角色卡片列表
 * - 编辑抽屉：点击任意卡片编辑内容
 * - 侧边栏：写作进度统计 + 最近修改
 * - 快速开始向导（5步）
 * - 从拆书页联动（sessionStorage）
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { useSystemStore } from '@/stores/system'
import { ProjectAPI } from '@/api/project'
import { ReportsAPI } from '@/api/reports'
import type { Volume, SkeletonChapter, WorldInfo, Character, Faction } from '@/types'
import TabBar from '@/components/common/TabBar.vue'
import QuickStartWizard from '@/components/design/QuickStartWizard.vue'
import DesignEditModal, { type EditType } from '@/components/design/DesignEditModal.vue'
import FactionGraph from '@/components/design/FactionGraph.vue'

const projectStore = useProjectStore()
const uiStore = useUiStore()
const systemStore = useSystemStore()

// ── 页面状态 ──
const activeTab = ref<'rough' | 'detailed' | 'world' | 'factions' | 'characters'>('rough')
const loading = ref(false)

// ── 数据 ──
const volumes = ref<Volume[]>([])
const chapters = ref<SkeletonChapter[]>([])
const worldData = ref<WorldInfo>({ core: '', powers: '' })
const characters = ref<Character[]>([])
const factions = ref<Faction[]>([])

// ── 编辑抽屉 ──
const editModalOpen = ref(false)
const editTitle = ref('')
const editType = ref<EditType | null>(null)
const editIndex = ref<number | null>(null)
const editForm = ref<Record<string, string>>({})

// ── 快速开始向导 ──
const quickStartOpen = ref(false)

// ── 拆书联动提示 ──
const disassemblyHint = ref<string | null>(null)

// ── 骨架/蓝图 ──
const skeletonText = ref('')
const skeletonLoading = ref(false)
const blueprintResult = ref<Record<string, unknown> | null>(null)
const blueprintLoading = ref(false)

async function loadSkeleton() {
  skeletonLoading.value = true
  const res = await ReportsAPI.getSkeleton('demo', '末世')
  if (res.ok && res.data) skeletonText.value = res.data.skeleton || ''
  skeletonLoading.value = false
}

async function loadBlueprint() {
  const ok = await systemStore.ensureModelRunning('生成章节蓝图')
  if (!ok) return
  blueprintLoading.value = true
  const res = await ReportsAPI.getBlueprint({
    chapter: 1,
    total_chapters: 300,
    genre: projectStore.projectGenre || '末世',
    project_id: projectStore.currentProject?.id,
  })
  if (res.ok && res.data) blueprintResult.value = res.data
  blueprintLoading.value = false
}

// ── 计算属性 ──
const hasProject = computed(() => projectStore.hasProject)
const currentProject = computed(() => projectStore.currentProject)

const totalChapters = computed(() => currentProject.value?.meta.total_chapters ?? 0)
const writtenChapters = computed(() => currentProject.value?.meta.written_chapters ?? 0)
const plannedChapters = computed(() => Math.max(0, totalChapters.value - writtenChapters.value))
const progressPct = computed(() => totalChapters.value > 0 ? Math.round((writtenChapters.value / totalChapters.value) * 100) : 0)

// ── 子页签定义 ──
const tabs = [
  { key: 'rough' as const, label: '粗纲', icon: 'layers' },
  { key: 'detailed' as const, label: '细纲', icon: 'list' },
  { key: 'world' as const, label: '世界观', icon: 'globe' },
  { key: 'characters' as const, label: '角色', icon: 'user' },
  { key: 'factions' as const, label: '势力', icon: 'shield' },
]

const tabIcons: Record<string, string> = {
  layers: 'M12 2L2 7l10 5 10-5-10-5z M2 17l10 5 10-5 M2 12l10 5 10-5',
  list: 'M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01',
  globe: 'M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z M2 12h20 M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z',
  user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
}

// ── 能力体系拆分 ──
const powersList = computed(() => {
  if (!worldData.value.powers) return []
  return worldData.value.powers.split(/[，,；;\n]/).map(s => s.trim()).filter(Boolean)
})

// ── 方法 ──
async function loadDesignData() {
  if (!currentProject.value?.id) return
  loading.value = true
  try {
    const [skelRes, worldRes, charRes, facRes] = await Promise.all([
      ProjectAPI.getSkeleton(currentProject.value.id),
      ProjectAPI.getWorld(currentProject.value.id),
      ProjectAPI.getCharacters(currentProject.value.id),
      ProjectAPI.getFactions(currentProject.value.id),
    ])
    if (skelRes.ok && skelRes.data) {
      volumes.value = skelRes.data.volumes || []
      chapters.value = skelRes.data.chapters || []
    }
    if (worldRes.ok && worldRes.data) {
      worldData.value = worldRes.data
    }
    if (charRes.ok && charRes.data) {
      characters.value = charRes.data
    }
    if (facRes.ok && facRes.data) {
      factions.value = facRes.data
    }
  } catch (e) {
    uiStore.showToast('加载设计数据失败', 'error')
  }
  loading.value = false
}

// ── 编辑：打开/保存 ──
function openEditVolume(idx: number) {
  const v = volumes.value[idx]
  if (!v) return
  editType.value = 'volume'
  editIndex.value = idx
  editTitle.value = `编辑 ${v.title}`
  editForm.value = {
    title: v.title || '',
    range: v.chapters || v.range || '',
    subtitle: v.subtitle || '',
    summary: v.summary || '',
    tags: (v.tags || []).join(','),
  }
  editModalOpen.value = true
}

function openEditChapter(idx: number) {
  const c = chapters.value[idx]
  if (!c) return
  editType.value = 'chapter'
  editIndex.value = idx
  editTitle.value = `编辑 ${c.title}`
  editForm.value = {
    title: c.title || '',
    goal: c.goal || '',
    conflict: c.conflict || '',
    result: c.result || '',
    hook: c.hook || '',
    pleasure: c.pleasure || '',
    foreshadowing: c.foreshadowing || '',
    expectation: c.expectation || '',
    scenes: (c.scenes || []).join('\n'),
  }
  editModalOpen.value = true
}

function openEditCharacter(idx: number) {
  const c = characters.value[idx]
  if (!c) return
  editType.value = 'character'
  editIndex.value = idx
  editTitle.value = `编辑角色：${c.name}`
  editForm.value = {
    name: c.name || '',
    role: c.role || '',
    desc: c.desc || '',
  }
  editModalOpen.value = true
}

function openEditWorld() {
  editType.value = 'world'
  editIndex.value = null
  editTitle.value = '编辑世界观'
  editForm.value = {
    core: worldData.value.core || '',
    powers: worldData.value.powers || '',
  }
  editModalOpen.value = true
}

function openEditFaction(idx: number) {
  const f = factions.value[idx]
  if (!f) return
  editType.value = 'faction'
  editIndex.value = idx
  editTitle.value = `编辑势力：${f.name}`
  editForm.value = {
    name: f.name || '',
    desc: f.desc || '',
  }
  editModalOpen.value = true
}

function closeEdit() {
  editModalOpen.value = false
  editType.value = null
  editIndex.value = null
}

function onEditFormUpdate(key: string, value: string) {
  editForm.value[key] = value
}

async function saveEdit() {
  if (!currentProject.value?.id) {
    uiStore.showToast('请先选择或创建一个项目', 'error')
    return
  }
  const pid = currentProject.value.id
  try {
    if (editType.value === 'volume' && editIndex.value !== null) {
      const v = volumes.value[editIndex.value]
      v.title = editForm.value.title
      v.chapters = editForm.value.range
      v.subtitle = editForm.value.subtitle
      v.summary = editForm.value.summary
      v.tags = editForm.value.tags.split(',').map(t => t.trim()).filter(Boolean)
      await ProjectAPI.updateSkeleton(pid, { volumes: volumes.value, chapters: chapters.value })
    } else if (editType.value === 'chapter' && editIndex.value !== null) {
      const c = chapters.value[editIndex.value]
      c.title = editForm.value.title
      c.goal = editForm.value.goal
      c.conflict = editForm.value.conflict
      c.result = editForm.value.result
      c.hook = editForm.value.hook
      c.pleasure = editForm.value.pleasure
      c.foreshadowing = editForm.value.foreshadowing
      c.expectation = editForm.value.expectation
      c.scenes = editForm.value.scenes.split('\n').map(s => s.trim()).filter(Boolean)
      await ProjectAPI.updateSkeleton(pid, { volumes: volumes.value, chapters: chapters.value })
    } else if (editType.value === 'character' && editIndex.value !== null) {
      const c = characters.value[editIndex.value]
      c.name = editForm.value.name
      c.role = editForm.value.role
      c.desc = editForm.value.desc
      await ProjectAPI.updateCharacters(pid, characters.value)
    } else if (editType.value === 'world') {
      worldData.value.core = editForm.value.core
      worldData.value.powers = editForm.value.powers
      await ProjectAPI.updateWorld(pid, worldData.value)
    } else if (editType.value === 'faction' && editIndex.value !== null) {
      const f = factions.value[editIndex.value]
      f.name = editForm.value.name
      f.desc = editForm.value.desc
      await ProjectAPI.updateFactions(pid, factions.value)
    }
    uiStore.showToast('已保存')
    closeEdit()
  } catch (e) {
    uiStore.showToast('保存失败', 'error')
  }
}

// ── 从 AI 生成骨架 ──
async function loadFromAI() {
  if (!currentProject.value?.id) return
  const ok = await systemStore.ensureModelRunning('AI 生成骨架')
  if (!ok) return
  uiStore.showToast('模型已就绪，正在生成骨架...', 'info')
  const skelRes = await ProjectAPI.getSkeleton(currentProject.value.id)
  if (skelRes.ok && skelRes.data && skelRes.data.volumes?.length > 0) {
    await loadDesignData()
    uiStore.showToast('项目骨架已加载')
  } else {
    uiStore.showToast('骨架暂未生成，请使用快速开始向导', 'info')
    openQuickStart()
  }
}

function openQuickStart() {
  quickStartOpen.value = true
}

async function onQuickStartGenerated() {
  loading.value = true
  await loadDesignData()
  loading.value = false
}

// ── 生命周期 ──
onMounted(async () => {
  // 检查拆书页联动
  try {
    const hint = sessionStorage.getItem('disassembly_to_design')
    if (hint) {
      const parsed = JSON.parse(hint)
      disassemblyHint.value = parsed.advice || null
      sessionStorage.removeItem('disassembly_to_design')
    }
  } catch { /* ignore */ }

  if (!projectStore.currentProject?.id) {
    await projectStore.restoreCurrentProject()
  }
})

watch(() => projectStore.currentProject, async (project) => {
  if (project?.id) {
    await loadDesignData()
  } else {
    volumes.value = []
    chapters.value = []
    characters.value = []
    factions.value = []
    worldData.value = { core: '', powers: '' }
    skeletonText.value = ''
    blueprintResult.value = null
  }
}, { immediate: true })
</script>

<template>
  <div class="design-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-main">
        <h2>设计</h2>
        <span class="page-subtitle">粗纲、细纲、世界观、角色与势力</span>
      </div>
      <button v-if="hasProject" class="btn btn-primary btn-sm" @click="openQuickStart">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        快速开始
      </button>
    </div>

    <!-- 拆书联动提示 -->
    <div v-if="disassemblyHint" class="dis-hint-bar">
      <span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:4px;"><path d="M9.663 17h4.673M12 3v1M6.343 4.343l-.707-.707M18.364 4.343l.707-.707M4 12h1M19 12h1M6.343 19.657l-.707.707M18.364 19.657l.707.707M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"/></svg>
        拆书建议：{{ disassemblyHint }}
      </span>
      <button class="dis-hint-close" @click="disassemblyHint = null">×</button>
    </div>

    <!-- 无项目空状态 -->
    <div v-if="!hasProject" class="design-empty">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.3;margin-bottom:16px;">
        <path d="M12 19l7-7 3 3-7 7-3-3z" /><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" /><path d="M2 2l7.586 7.586" />
      </svg>
      <h3 class="empty-title">开始设计你的小说</h3>
      <p class="empty-desc">从一句话梗概开始，系统帮你生成完整的大纲骨架。<br>也可以先体验示例项目，了解设计页的全部能力。</p>
      <div class="empty-actions">
        <button class="btn btn-primary btn-lg" @click="openQuickStart">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          快速开始
        </button>
      </div>
      <div class="empty-features">
        <div class="empty-feature" @click="openQuickStart">
          <svg class="feat-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <div><b>AI 生成骨架</b><span>选题材 → 写梗概 → 自动生成五卷粗纲</span></div>
        </div>
        <div class="empty-feature" @click="activeTab = 'detailed'">
          <svg class="feat-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01"/></svg>
          <div><b>网文细纲</b><span>钩子 / 爽点 / 伏笔 / 期待感，专为网文设计</span></div>
        </div>
        <div class="empty-feature" @click="activeTab = 'characters'">
          <svg class="feat-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"/></svg>
          <div><b>角色 & 势力</b><span>结构化卡片 + 关系图，不再前后矛盾</span></div>
        </div>
      </div>
    </div>

    <!-- 有项目时 -->
    <template v-else>
      <!-- 子导航 -->
      <nav class="design-subnav">
        <TabBar
          v-model="activeTab"
          :options="tabs.map(t => ({ label: t.label, value: t.key, icon: tabIcons[t.icon] }))"
        />
        <div class="subnav-right">
          <button class="btn btn-secondary btn-sm" :disabled="skeletonLoading" @click="loadSkeleton">{{ skeletonLoading ? '加载中...' : '示例骨架' }}</button>
          <button class="btn btn-secondary btn-sm" :disabled="blueprintLoading" @click="loadBlueprint">{{ blueprintLoading ? '加载中...' : '蓝图' }}</button>
          <button class="btn btn-secondary btn-sm" @click="loadFromAI">从AI生成骨架</button>
          <button class="btn btn-primary btn-sm" @click="openQuickStart">快速开始</button>
        </div>
      </nav>

      <div class="design-body">
        <div class="design-content">
          <div v-if="loading" class="design-loading">
            <div class="spinner" /><span>加载中...</span>
          </div>

          <!-- 粗纲 -->
          <div v-show="activeTab === 'rough'" class="design-pane">
            <div v-if="volumes.length === 0" class="pane-empty">
              暂无粗纲数据。点击右上角「从AI生成骨架」或使用「快速开始」。
            </div>
            <div v-else class="volume-grid">
              <div
                v-for="(v, idx) in volumes"
                :key="idx"
                class="volume-card"
                @click="openEditVolume(idx)"
              >
                <div class="vol-header">
                  <span class="vol-title">{{ v.title }}</span>
                  <span class="vol-range">{{ v.chapters || v.range }}</span>
                </div>
                <div class="vol-subtitle">{{ v.subtitle }}</div>
                <p class="vol-summary">{{ v.summary || '暂无摘要' }}</p>
                <div v-if="v.tags?.length" class="vol-tags">
                  <span v-for="t in v.tags" :key="t" class="tag">{{ t }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 细纲 -->
          <div v-show="activeTab === 'detailed'" class="design-pane">
            <div v-if="chapters.length === 0" class="pane-empty">
              暂无细纲数据。可在粗纲页生成骨架后自动填充。
            </div>
            <div v-else class="segment-grid">
              <div
                v-for="(c, idx) in chapters"
                :key="idx"
                class="segment-card"
                @click="openEditChapter(idx)"
              >
                <div class="seg-header">
                  <div class="seg-title">{{ c.title }}</div>
                  <span class="seg-status planned">规划中</span>
                </div>
                <div class="seg-fields">
                  <div class="seg-field"><b>目标</b><p>{{ c.goal || '-' }}</p></div>
                  <div class="seg-field"><b>冲突</b><p>{{ c.conflict || '-' }}</p></div>
                  <div class="seg-field"><b>结果</b><p>{{ c.result || '-' }}</p></div>
                </div>
                <div v-if="c.hook || c.pleasure || c.foreshadowing || c.expectation" class="seg-fields seg-web-fields">
                  <div v-if="c.hook" class="seg-field seg-field-hook"><b>钩子</b><p>{{ c.hook }}</p></div>
                  <div v-if="c.pleasure" class="seg-field seg-field-pleasure"><b>爽点</b><p>{{ c.pleasure }}</p></div>
                  <div v-if="c.foreshadowing" class="seg-field seg-field-foreshadow"><b>伏笔</b><p>{{ c.foreshadowing }}</p></div>
                  <div v-if="c.expectation" class="seg-field seg-field-expect"><b>期待感</b><p>{{ c.expectation }}</p></div>
                </div>
                <ul v-if="c.scenes?.length" class="seg-scenes">
                  <li v-for="(s, si) in c.scenes" :key="si">{{ s }}</li>
                </ul>
              </div>
            </div>
          </div>

          <!-- 世界观 -->
          <div v-show="activeTab === 'world'" class="design-pane">
            <div class="world-card" @click="openEditWorld" style="cursor:pointer;">
              <h4>世界观核心</h4>
              <p class="world-summary">{{ worldData.core || '暂无核心设定，点击编辑' }}</p>
            </div>
            <div v-if="powersList.length" class="world-card">
              <h4>能力体系</h4>
              <ul class="world-powers">
                <li v-for="(p, i) in powersList" :key="i">{{ p }}</li>
              </ul>
            </div>
          </div>

          <!-- 角色 -->
          <div v-show="activeTab === 'characters'" class="design-pane">
            <div v-if="characters.length === 0" class="pane-empty">暂无角色数据</div>
            <div v-else class="char-grid">
              <div
                v-for="(c, idx) in characters"
                :key="idx"
                class="char-card"
                @click="openEditCharacter(idx)"
              >
                <h4>{{ c.name }}</h4>
                <div class="char-role">{{ c.role }}</div>
                <p>{{ c.desc }}</p>
              </div>
            </div>
          </div>

          <!-- 势力 -->
          <div v-show="activeTab === 'factions'" class="design-pane">
            <div class="faction-graph-card">
              <h4>势力关系图</h4>
              <FactionGraph v-if="factions.length > 0" :factions="factions" @edit-faction="openEditFaction" />
              <div v-else class="pane-empty" style="padding:40px;">暂无势力数据，请在下方添加</div>
            </div>
            <div class="faction-list-card">
              <div class="faction-list-header"><h4>势力设定</h4><span class="text-muted">点击卡片编辑</span></div>
              <div class="faction-list">
                <div
                  v-for="(f, idx) in factions"
                  :key="idx"
                  class="faction-item"
                  @click="openEditFaction(idx)"
                >
                  <div class="faction-item-body">
                    <b>{{ f.name }}</b>
                    <p>{{ f.desc }}</p>
                  </div>
                  <span class="faction-edit-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 侧边栏 -->
        <aside class="design-sidebar">
          <div class="side-card">
            <h4>当前状态</h4>
            <div class="status-row"><span>总章数</span><b>{{ totalChapters }}</b></div>
            <div class="status-row"><span>已写作</span><b class="status-good">{{ writtenChapters }}</b></div>
            <div class="status-row"><span>规划中</span><b class="status-warn">{{ plannedChapters }}</b></div>
            <div class="status-progress"><div class="status-progress-bar" :style="{ width: progressPct + '%' }" /></div>
            <div class="status-hint">写作进度 {{ progressPct }}%</div>
          </div>
        </aside>
      </div>
    </template>

    <!-- 编辑抽屉 -->
    <DesignEditModal
      :open="editModalOpen"
      :title="editTitle"
      :type="editType"
      :form="editForm"
      @close="closeEdit"
      @save="saveEdit"
      @update:form="onEditFormUpdate"
    />

    <!-- 快速开始向导 -->
    <QuickStartWizard
      v-if="quickStartOpen"
      @close="quickStartOpen = false"
      @generated="onQuickStartGenerated"
    />
  </div>
</template>

<style scoped>
.design-page { padding: 16px 24px; height: 100%; overflow-y: auto; background: radial-gradient(circle at 50% 0%, rgba(var(--accent-rgb), 0.05), transparent 35%), var(--bg); }

/* 拆书联动提示 */
.dis-hint-bar { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px; margin-bottom: 12px; background: rgba(56, 189, 248, 0.08); border: 1px solid var(--accent); border-radius: 8px; font-size: 13px; color: var(--text); }
.dis-hint-close { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 16px; }

/* 空状态 */
.design-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; min-height: 500px; text-align: center; }
.empty-title { font-size: 20px; font-weight: 600; margin-bottom: 8px; }
.empty-desc { font-size: 14px; color: var(--text-secondary); margin-bottom: 20px; line-height: 1.6; }
.empty-actions { display: flex; gap: 12px; margin-bottom: 32px; }
.empty-features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; max-width: 700px; }
.empty-feature { display: flex; align-items: flex-start; gap: 10px; padding: 14px; border: 1px solid var(--border); border-radius: 10px; cursor: pointer; transition: all 0.15s; }
.empty-feature:hover { border-color: var(--accent); background: rgba(56, 189, 248, 0.04); }
.feat-icon { width: 20px; height: 20px; flex-shrink: 0; color: var(--accent); }
.empty-feature b { font-size: 13px; display: block; }
.empty-feature span { font-size: 11px; color: var(--text-secondary); }

.design-subnav { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: var(--surface-solid); border: 1px solid var(--border-hover); border-radius: 12px; margin: 12px 0 18px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06); }
.subnav-right { display: flex; gap: 8px; }

/* 主体布局 */
.design-body { display: flex; gap: 16px; }
.design-content { flex: 1; min-width: 0; }
.design-sidebar { width: 220px; flex-shrink: 0; }
.side-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.side-card h4 { font-size: 13px; font-weight: 600; margin-bottom: 10px; }
.status-row { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; }
.status-row b { font-weight: 600; }
.status-good { color: var(--success); }
.status-warn { color: var(--warning); }
.status-progress { height: 6px; background: var(--surface-solid); border-radius: 3px; overflow: hidden; margin: 8px 0 4px; }
.status-progress-bar { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.status-hint { font-size: 11px; color: var(--text-secondary); }

/* 加载 */
.design-loading { display: flex; align-items: center; gap: 8px; padding: 40px; justify-content: center; color: var(--text-secondary); }
.spinner { width: 24px; height: 24px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 空面板 */
.pane-empty { padding: 40px; text-align: center; color: var(--text-secondary); font-size: 13px; }

/* 粗纲卷卡片 */
.volume-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.volume-card { background: var(--surface-solid); border: 1px solid var(--border-hover); border-radius: 10px; padding: 14px; cursor: pointer; transition: all 0.15s; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06); }
.volume-card:hover { border-color: var(--accent); transform: translateY(-1px); box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08); }
.vol-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.vol-title { font-size: 15px; font-weight: 600; }
.vol-range { font-size: 11px; color: var(--text-secondary); }
.vol-subtitle { font-size: 13px; color: var(--accent); margin-bottom: 6px; }
.vol-summary { font-size: 12px; color: var(--text-secondary); line-height: 1.5; margin: 0 0 8px; }
.vol-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.tag { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--surface-hover); color: var(--text-secondary); }

/* 细纲段卡片 */
.segment-grid { display: flex; flex-direction: column; gap: 12px; }
.segment-card { background: var(--surface-solid); border: 1px solid var(--border-hover); border-radius: 10px; padding: 14px; cursor: pointer; transition: all 0.15s; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06); }
.segment-card:hover { border-color: var(--accent); box-shadow: 0 3px 8px rgba(0, 0, 0, 0.07); }
.seg-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.seg-title { font-size: 14px; font-weight: 600; }
.seg-status { font-size: 10px; padding: 2px 8px; border-radius: 3px; }
.seg-status.planned { color: var(--text-secondary); background: var(--surface-hover); }
.seg-fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 8px; }
.seg-field b { font-size: 11px; color: var(--text-secondary); display: block; margin-bottom: 2px; }
.seg-field p { font-size: 12px; margin: 0; line-height: 1.4; }
.seg-web-fields { border-top: 1px solid var(--border); padding-top: 8px; }
.seg-field-hook b { color: var(--accent); }
.seg-field-pleasure b { color: var(--danger); }
.seg-field-foreshadow b { color: var(--amber); }
.seg-field-expect b { color: var(--success); }
.seg-scenes { margin: 8px 0 0; padding-left: 16px; font-size: 12px; color: var(--text-secondary); }

/* 世界观 */
.world-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 12px; }
.world-card h4 { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.world-summary { font-size: 13px; line-height: 1.6; color: var(--text); margin: 0; }
.world-powers { list-style: none; padding: 0; margin: 0; }
.world-powers li { font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
.world-powers li:last-child { border-bottom: none; }

/* 角色 */
.char-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.char-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; cursor: pointer; transition: all 0.15s; }
.char-card:hover { border-color: var(--accent); }
.char-card h4 { font-size: 15px; font-weight: 600; margin-bottom: 2px; }
.char-role { font-size: 11px; color: var(--accent); margin-bottom: 6px; }
.char-card p { font-size: 12px; color: var(--text-secondary); line-height: 1.5; margin: 0; }

/* 势力 */
.faction-graph-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 12px; }
.faction-graph-card h4 { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.faction-list-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.faction-list-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.faction-list-header h4 { font-size: 14px; font-weight: 600; }
.faction-list { display: flex; flex-direction: column; gap: 6px; }
.faction-item { display: flex; align-items: center; gap: 8px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; transition: all 0.15s; }
.faction-item:hover { border-color: var(--accent); }
.faction-item-body { flex: 1; }
.faction-item-body b { font-size: 13px; display: block; }
.faction-item-body p { font-size: 12px; color: var(--text-secondary); margin: 2px 0 0; }
.faction-edit-icon { font-size: 12px; color: var(--text-muted); }

/* ── 编辑抽屉样式已移至 DesignEditModal 组件 ── */

/* ── 按钮 — 全局 style.css 接管 ── */
.text-muted { color: var(--text-secondary); font-size: 11px; }

@media (max-width: 1024px) {
  .design-body { flex-direction: column; }
  .design-sidebar { width: 100%; }
}
@media (max-width: 768px) {
  .seg-fields { grid-template-columns: 1fr; }
  .empty-features { grid-template-columns: 1fr; }
}
</style>
