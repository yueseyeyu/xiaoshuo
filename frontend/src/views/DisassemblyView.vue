<script setup lang="ts">
/**
 * DisassemblyView — 拆书页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - 标签页切换：拆书分析 | 小说解构
 * - 拆书分析：任务管理 + 书目列表 + 八步法 + 三步法 + 章节表 + 分布图 + 节奏曲线 + 多书对比
 * - 小说解构：可解构书目列表 + 五段式解构结果
 *
 * 子组件：
 * - BookDetailPanel: 拆书详情面板（八步法/章节表/分布图/对比）
 * - TaskCreateModal: 新建拆书任务模态框
 * - DeconstructModal: 小说解构结果模态框
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useUiStore } from '@/stores/ui'
import { useProjectStore } from '@/stores/project'
import { useVisibilityPause } from '@/composables/useVisibilityPause'
import {
  DisassemblyAPI,
  type DisassemblyBook,
  type AnalysisTask,
} from '@/api/disassembly'
import { CreativeAPI } from '@/api/creative'
import { LibraryAPI, type Book } from '@/api/library'
import TabBar from '@/components/common/TabBar.vue'
import KpiCard from '@/components/common/KpiCard.vue'
import BookDetailPanel from '@/components/disassembly/BookDetailPanel.vue'
import TaskCreateModal from '@/components/disassembly/TaskCreateModal.vue'
import DeconstructModal from '@/components/disassembly/DeconstructModal.vue'

const uiStore = useUiStore()
const projectStore = useProjectStore()

// ── 标签页 ──
const activeTab = ref<'disassembly' | 'deconstruction'>('disassembly')

// ── 拆书分析状态 ──
const libBooks = ref<Book[]>([])
const disassemblyBooks = ref<DisassemblyBook[]>([])
const loading = ref(true)
const filterStatus = ref('all')
const filterGenre = ref('all')
const selectedStem = ref<string | null>(null)
const detailData = ref<DisassemblyBook | null>(null)
const detailLoading = ref(false)

// 对比模式
const compareBooks = ref<Array<{ name: string; title: string; data?: DisassemblyBook }>>([])
const compareMode = ref(false)

// ── 任务管理状态 ──
const tasks = ref<AnalysisTask[]>([])
const taskFilter = ref('all')
const showTaskModal = ref(false)
const taskPolling = ref(false)

async function pollTasksOnce() {
  const hasActive = tasks.value.some(
    (t) => t.status === 'pending' || t.status === 'queued' || t.status === 'running'
  )
  if (!hasActive) {
    stopTaskPolling()
    return
  }
  await loadTasks()
}

const { start: startTaskPollingInner, stop: stopTaskPollingInner } = useVisibilityPause(pollTasksOnce, 2000)

// ── 解构查看器状态 ──
const deconstructBooks = ref<Array<{ title: string; file_path: string; size_kb: number; genre: string }>>([])
const deconstructLoading = ref(false)
const showDeconstructModal = ref(false)
const deconstructModalRef = ref<InstanceType<typeof DeconstructModal> | null>(null)

// ── 题材列表 ──
const genres = computed(() => {
  const set = new Set<string>()
  libBooks.value.forEach((b) => { if (b.genre) set.add(b.genre) })
  return Array.from(set).sort()
})

// ── 统一书目列表 ──
interface UnifiedItem {
  stem: string
  title: string
  genre: string
  chapters: number
  words: number
  status: 'analyzed' | 'pending'
}

const unifiedList = computed<UnifiedItem[]>(() => {
  const disMap: Record<string, DisassemblyBook> = {}
  disassemblyBooks.value.forEach((b) => {
    if (b.key) disMap[b.key] = b
  })

  return libBooks.value.map((b) => {
    let stem = b.stem || ''
    if (!stem && b.file) {
      stem = b.file.replace(/^rhythm_/, '').replace(/\.csv$/, '')
    }
    if (!stem) stem = b.title || ''
    const disBook = disMap[stem]
    const isAnalyzed = b.status === 'analyzed' || !!disBook
    return {
      stem,
      title: b.title || stem,
      genre: b.genre || '未知',
      chapters: disBook?.summary?.chapters || 0,
      words: disBook?.summary?.total_words || b.wordCount || 0,
      status: isAnalyzed ? 'analyzed' as const : 'pending' as const,
    }
  })
})

const filteredList = computed(() => {
  return unifiedList.value.filter((item) => {
    if (filterStatus.value !== 'all' && item.status !== filterStatus.value) return false
    if (filterGenre.value !== 'all' && item.genre !== filterGenre.value) return false
    return true
  })
})

// KPI
const kpiBooks = computed(() => disassemblyBooks.value.length)
const kpiChapters = computed(() =>
  disassemblyBooks.value.reduce((sum, b) => sum + (b.summary?.chapters || 0), 0)
)
const kpiWords = computed(() =>
  disassemblyBooks.value.reduce((sum, b) => sum + (b.summary?.total_words || 0), 0)
)
const kpiAvg = computed(() => kpiChapters.value > 0 ? Math.round(kpiWords.value / kpiChapters.value) : 0)

// ── 任务管理 ──
const taskTypeLabels: Record<string, string> = {
  full: '完整分析',
  rhythm: '节奏分析',
  emotion: '情绪分析',
}

const filteredTasks = computed(() => {
  if (taskFilter.value === 'all') return tasks.value
  return tasks.value.filter((t) => t.status === taskFilter.value)
})

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    pending: '等待中',
    queued: '排队中',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
  }
  return map[s] || s
}

async function loadTasks() {
  const res = await DisassemblyAPI.getTasks()
  if (res.ok && res.data?.tasks) {
    tasks.value = res.data.tasks
  }
}

function openTaskModal() {
  showTaskModal.value = true
}

async function onTaskCreated() {
  await loadTasks()
  startTaskPolling()
}

function startTaskPolling() {
  if (taskPolling.value) return
  taskPolling.value = true
  startTaskPollingInner()
}

function stopTaskPolling() {
  stopTaskPollingInner()
  taskPolling.value = false
}

// ── 解构查看器 ──
async function loadDeconstructBooks() {
  deconstructLoading.value = true
  const genre = projectStore.projectGenre || '末世'
  const res = await CreativeAPI.getDeconstructableBooks(genre)
  if (res.ok && res.data?.books) {
    deconstructBooks.value = res.data.books
  }
  deconstructLoading.value = false
}

function fmtSize(kb: number): string {
  if (kb >= 1024) return (kb / 1024).toFixed(1) + 'MB'
  return kb + 'KB'
}

function openDeconstruct(book: { title: string; file_path: string }) {
  deconstructModalRef.value?.open(book)
}

// ── 通用方法 ──
function fmtNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

function setFilter(key: 'status' | 'genre', value: string) {
  if (key === 'status') filterStatus.value = value
  else filterGenre.value = value
}

async function openDetail(item: UnifiedItem) {
  selectedStem.value = item.stem
  detailData.value = null
  detailLoading.value = true

  if (item.status === 'pending') {
    detailLoading.value = false
    return
  }

  const res = await DisassemblyAPI.getBookDetail(item.stem)
  if (res.ok && res.data) {
    detailData.value = res.data
  } else {
    uiStore.showToast('加载详情失败', 'error')
  }
  detailLoading.value = false
}

function toggleCompare(item: { stem: string; title: string }) {
  const idx = compareBooks.value.findIndex((b) => b.name === item.stem)
  if (idx >= 0) {
    compareBooks.value.splice(idx, 1)
  } else {
    if (compareBooks.value.length >= 3) {
      uiStore.showToast('最多对比 3 本书')
      return
    }
    compareBooks.value.push({ name: item.stem, title: item.title })
  }
}

function clearCompare() {
  compareBooks.value = []
  compareMode.value = false
}

async function showCompareResult() {
  if (compareBooks.value.length < 2) {
    uiStore.showToast('请至少选择 2 本书进行对比')
    return
  }
  compareMode.value = true
  detailLoading.value = true
  for (const b of compareBooks.value) {
    const res = await DisassemblyAPI.getBookDetail(b.name)
    if (res.ok && res.data) {
      b.data = res.data
    }
  }
  detailLoading.value = false
}

// ── 生命周期 ──
onMounted(async () => {
  const [booksRes, disRes, tasksRes] = await Promise.all([
    LibraryAPI.getBooks(),
    DisassemblyAPI.getBooks(),
    DisassemblyAPI.getTasks(),
  ])
  if (booksRes.ok && booksRes.data?.books) {
    libBooks.value = booksRes.data.books
  }
  if (disRes.ok && disRes.data?.books) {
    disassemblyBooks.value = disRes.data.books
  }
  if (tasksRes.ok && tasksRes.data?.tasks) {
    tasks.value = tasksRes.data.tasks
    if (tasks.value.some((t) => t.status === 'pending' || t.status === 'queued' || t.status === 'running')) {
      startTaskPolling()
    }
  }
  loading.value = false
})

onUnmounted(() => {
  stopTaskPolling()
})
</script>

<template>
  <div class="disassembly-page">
    <div class="page-header">
      <h2>拆书</h2>
    </div>

    <!-- 标签页切换 -->
    <TabBar
      v-model="activeTab"
      :options="[
        { label: '拆书分析', value: 'disassembly' },
        { label: '小说解构', value: 'deconstruction' },
      ]"
      @update:model-value="(v) => v === 'deconstruction' && deconstructBooks.length === 0 && loadDeconstructBooks()"
    />

    <!-- ═══════════════ 拆书分析 Tab ═══════════════ -->
    <template v-if="activeTab === 'disassembly'">
      <!-- 任务管理面板 -->
      <div class="task-panel">
        <div class="task-panel-header">
          <div class="task-filter-tabs">
            <button class="filter-tab" :class="{ active: taskFilter === 'all' }" @click="taskFilter = 'all'">全部</button>
            <button class="filter-tab" :class="{ active: taskFilter === 'running' }" @click="taskFilter = 'running'">进行中</button>
            <button class="filter-tab" :class="{ active: taskFilter === 'completed' }" @click="taskFilter = 'completed'">已完成</button>
            <button class="filter-tab" :class="{ active: taskFilter === 'failed' }" @click="taskFilter = 'failed'">失败</button>
          </div>
          <button class="btn btn-primary btn-sm" @click="openTaskModal">+ 新建任务</button>
        </div>
        <div class="task-grid" v-if="filteredTasks.length > 0">
          <div v-for="t in filteredTasks" :key="t.id" class="task-card">
            <div class="task-card-header">
              <span class="task-type">{{ taskTypeLabels[t.type] || t.type }}</span>
              <span class="task-badge" :class="t.status">{{ statusLabel(t.status) }}</span>
            </div>
            <div class="task-meta">书籍：{{ t.books.slice(0, 2).join('、') }}{{ t.books.length > 2 ? ` 等${t.books.length}本` : '' }}</div>
            <div class="task-progress"><div :style="{ width: t.progress + '%' }"></div></div>
            <div class="task-msg">{{ t.message || '' }}</div>
          </div>
        </div>
        <div v-else class="task-empty">
          <div class="task-empty-text">暂无{{ taskFilter !== 'all' ? statusLabel(taskFilter) : '' }}任务</div>
        </div>
      </div>

      <!-- KPI -->
      <div class="kpi-row">
        <KpiCard
          icon="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"
          color="indigo"
          :value="kpiBooks"
          label="已拆书籍"
        />
        <KpiCard
          icon="M4 6h16 M4 10h16 M4 14h16"
          color="accent"
          :value="fmtNumber(kpiChapters)"
          label="总章数"
        />
        <KpiCard
          icon="M12 20h9 M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"
          color="amber"
          :value="fmtNumber(kpiWords)"
          label="总字数"
        />
        <KpiCard
          icon="M9 7h6 M9 11h6 M9 15h6 M3 5v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5"
          color="violet"
          :value="fmtNumber(kpiAvg)"
          label="平均章字数"
        />
      </div>

      <div class="disassembly-layout">
        <!-- 侧边栏：书目列表 -->
        <aside class="dis-sidebar">
          <div class="side-card" style="flex:1;display:flex;flex-direction:column;min-height:0;">
            <div class="side-card-title" style="display:flex;align-items:center;justify-content:space-between;">
              <span>书籍列表</span>
              <span class="text-muted" style="font-size:11px;">{{ filteredList.length }}/{{ unifiedList.length }} 本</span>
            </div>
            <!-- 筛选 -->
            <div class="dis-filters">
              <div class="dis-filter-group">
                <span class="dis-filter-label">状态</span>
                <button class="dis-filter-btn" :class="{ active: filterStatus === 'all' }" @click="setFilter('status', 'all')">全部</button>
                <button class="dis-filter-btn" :class="{ active: filterStatus === 'analyzed' }" @click="setFilter('status', 'analyzed')">已拆</button>
                <button class="dis-filter-btn" :class="{ active: filterStatus === 'pending' }" @click="setFilter('status', 'pending')">待拆</button>
              </div>
              <div class="dis-filter-group">
                <span class="dis-filter-label">题材</span>
                <button class="dis-filter-btn" :class="{ active: filterGenre === 'all' }" @click="setFilter('genre', 'all')">全部</button>
                <button v-for="g in genres" :key="g" class="dis-filter-btn" :class="{ active: filterGenre === g }" @click="setFilter('genre', g)">{{ g }}</button>
              </div>
            </div>
            <!-- 列表 -->
            <div class="dis-list" style="flex:1;overflow-y:auto;">
              <div v-if="loading" class="text-muted" style="padding:8px 0;">加载中...</div>
              <div v-else-if="filteredList.length === 0" class="text-muted" style="padding:16px 8px;text-align:center;">无匹配书籍</div>
              <div
                v-for="item in filteredList"
                :key="item.stem"
                class="dis-list-item"
                :class="{ active: selectedStem === item.stem }"
                @click="openDetail(item)"
              >
                <div class="dis-list-item-left">
                  <span class="dis-list-name">{{ item.title }}</span>
                  <span class="dis-list-info">
                    <span class="dis-list-genre">{{ item.genre }}</span>
                    <span v-if="item.status === 'analyzed'">{{ item.chapters }} 章</span>
                    <span v-else>{{ fmtNumber(item.words) }} 字</span>
                  </span>
                </div>
                <button v-if="item.status === 'analyzed'" class="dis-list-compare-btn" title="加入对比" @click.stop="toggleCompare(item)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22a8 8 0 0 0 8-8c0-3.866-4-10-8-18-4 8-8 14.134-8 18a8 8 0 0 0 8 8z"/></svg>
                </button>
                <span class="dis-list-badge" :class="item.status">{{ item.status === 'analyzed' ? '已拆' : '待拆' }}</span>
              </div>
            </div>
          </div>

          <!-- 对比栏 -->
          <div v-if="compareBooks.length > 0" class="compare-bar">
            <div class="compare-bar-info">
              <span class="compare-bar-label">对比栏（{{ compareBooks.length }}/3）</span>
              <span v-for="b in compareBooks" :key="b.name" class="compare-bar-item">
                {{ b.title }}
                <button class="compare-bar-remove" @click="toggleCompare({ stem: b.name, title: b.title })">×</button>
              </span>
            </div>
            <div class="compare-bar-actions">
              <button class="btn btn-primary btn-sm" :disabled="compareBooks.length < 2" @click="showCompareResult">开始对比</button>
              <button class="btn btn-secondary btn-sm" @click="clearCompare">清空</button>
            </div>
          </div>
        </aside>

        <!-- 主区域：详情（子组件） -->
        <div class="dis-main">
          <BookDetailPanel
            :detail-data="detailData"
            :selected-stem="selectedStem"
            :loading="detailLoading"
            :compare-books="compareBooks"
            :compare-mode="compareMode"
          />
        </div>
      </div>
    </template>

    <!-- ═══════════════ 小说解构 Tab ═══════════════ -->
    <template v-else>
      <div class="deconstruct-page">
        <div v-if="deconstructLoading" class="dis-loading">
          <div class="spinner" />
          <span>加载可解构书目...</span>
        </div>
        <div v-else-if="deconstructBooks.length === 0" class="dis-empty">
          <div style="font-size:14px;color:var(--text-secondary);">暂无可解构的小说文件</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">请将 .txt 小说放入 data/raw/novels/ 目录</div>
        </div>
        <div v-else class="deconstruct-book-list">
          <div
            v-for="b in deconstructBooks"
            :key="b.file_path"
            class="deconstruct-book-card"
            @click="openDeconstruct(b)"
          >
            <div class="deconstruct-book-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
              </svg>
            </div>
            <div class="deconstruct-book-info">
              <div class="deconstruct-book-title">{{ b.title }}</div>
              <div class="deconstruct-book-meta">{{ fmtSize(b.size_kb) }} · {{ b.genre }}</div>
            </div>
            <button class="btn btn-primary btn-sm">解构</button>
          </div>
        </div>
      </div>
    </template>

    <!-- ═══════════════ 子组件：模态框 ═══════════════ -->
    <TaskCreateModal v-model:show="showTaskModal" :books="libBooks" @created="onTaskCreated" />
    <DeconstructModal ref="deconstructModalRef" v-model:show="showDeconstructModal" />
  </div>
</template>

<style scoped>
.disassembly-page {
  padding: 20px 24px;
  height: 100%;
  overflow-y: auto;
  background: radial-gradient(circle at 50% 0%, rgba(var(--accent-rgb), 0.04), transparent 30%), var(--bg);
}
.page-header { margin-bottom: 20px; }

/* ── 任务管理面板 ── */
.task-panel {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.task-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.task-filter-tabs { display: flex; gap: 4px; }
.filter-tab {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.filter-tab:hover { border-color: var(--border-hover); }
.filter-tab.active {
  background: var(--accent);
  color: var(--bg);
  border-color: var(--accent);
}
.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}
.task-card {
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.task-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.task-type { font-size: 12px; font-weight: 600; }
.task-badge { font-size: 10px; padding: 1px 6px; border-radius: 3px; }
.task-badge.running { color: var(--info); background: rgba(56, 189, 248, 0.1); }
.task-badge.completed { color: var(--success); background: rgba(34, 197, 94, 0.1); }
.task-badge.failed { color: var(--danger); background: rgba(239, 68, 68, 0.1); }
.task-badge.queued, .task-badge.pending { color: var(--text-muted); background: var(--surface-hover); }
.task-meta { font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }
.task-progress { height: 4px; background: var(--surface-hover); border-radius: 2px; overflow: hidden; margin-bottom: 4px; }
.task-progress > div { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.3s; }
.task-msg { font-size: 11px; color: var(--text-muted); }
.task-empty { padding: 12px; text-align: center; }
.task-empty-text { font-size: 12px; color: var(--text-muted); }

/* ── KPI — 布局 ── */
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }

.disassembly-layout { display: flex; gap: 16px; min-height: 500px; }
.dis-sidebar { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; }
.dis-main { flex: 1; min-width: 0; }

.side-card { background: var(--surface-solid); border: 1px solid var(--border-hover); border-radius: 12px; padding: 14px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06); }
.side-card-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; }

.dis-filters { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
.dis-filter-group { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.dis-filter-label { font-size: 11px; color: var(--text-secondary); margin-right: 4px; font-weight: 500; }
.dis-filter-btn { padding: 3px 10px; border: 1px solid var(--border-hover); border-radius: 12px; background: var(--surface); color: var(--text-secondary); font-size: 11px; cursor: pointer; transition: all 0.15s; }
.dis-filter-btn:hover { border-color: var(--accent); color: var(--text); background: var(--surface-hover); }
.dis-filter-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }

.dis-list { display: flex; flex-direction: column; gap: 6px; }
.dis-list-item { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: all 0.15s; background: var(--surface); border: 1px solid var(--border-hover); }
.dis-list-item:hover { background: var(--surface-hover); border-color: var(--accent); }
.dis-list-item.active { background: rgba(var(--accent-rgb), 0.1); border: 1px solid var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.dis-list-item-left { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.dis-list-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
.dis-list-info { display: flex; gap: 8px; font-size: 11px; color: var(--text-secondary); }
.dis-list-genre { color: var(--accent); font-weight: 500; }
.dis-list-compare-btn { background: none; border: 1px solid var(--border-hover); border-radius: 4px; padding: 2px 6px; cursor: pointer; font-size: 12px; color: var(--text-secondary); }
.dis-list-compare-btn:hover { border-color: var(--accent); color: var(--accent); }
.dis-list-badge { font-size: 10px; padding: 2px 7px; border-radius: 10px; flex-shrink: 0; font-weight: 600; }
.dis-list-badge.analyzed { color: var(--success); background: rgba(34, 197, 94, 0.12); }
.dis-list-badge.pending { color: var(--text-secondary); background: var(--surface-hover); }

/* 对比栏 */
.compare-bar { background: var(--surface-solid); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 8px; }
.compare-bar-info { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.compare-bar-label { font-size: 12px; color: var(--text-secondary); }
.compare-bar-item { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: var(--surface-hover); display: flex; align-items: center; gap: 4px; }
.compare-bar-remove { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 14px; }
.compare-bar-actions { display: flex; gap: 6px; }

/* 解构列表 */
.deconstruct-page { min-height: 400px; }
.deconstruct-book-list { display: flex; flex-direction: column; gap: 8px; }
.deconstruct-book-card {
  display: flex; align-items: center; gap: 12px; padding: 12px 14px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  cursor: pointer; transition: all 0.15s;
}
.deconstruct-book-card:hover { border-color: var(--accent); }
.deconstruct-book-icon { color: var(--text-secondary); flex-shrink: 0; }
.deconstruct-book-info { flex: 1; min-width: 0; }
.deconstruct-book-title { font-size: 13px; font-weight: 600; }
.deconstruct-book-meta { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

/* loading/empty */
.dis-loading, .dis-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 400px; }
.spinner { width: 24px; height: 24px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }

.text-muted { color: var(--text-secondary); }
/* ── 按钮 — 全局 style.css 接管 ── */

@media (max-width: 1200px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } .disassembly-layout { flex-direction: column; } .dis-sidebar { width: 100%; } }
@media (max-width: 768px) { .kpi-row { grid-template-columns: 1fr; } }
</style>
