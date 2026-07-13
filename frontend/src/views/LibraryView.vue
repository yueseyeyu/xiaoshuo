<script setup lang="ts">
/**
 * LibraryView — 书库页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - 题材标签筛选 + 搜索
 * - 书籍列表（列表视图）+ 排序
 * - 批量选择 + 批量拆书
 * - 书籍详情面板
 * - 导入书籍（本地 txt）
 * - KPI 统计
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUiStore } from '@/stores/ui'
import { LibraryAPI, type Book, type LibraryData } from '@/api/library'
import { DisassemblyAPI } from '@/api/disassembly'
import KpiCard from '@/components/common/KpiCard.vue'
import LibraryBookDetail from '@/components/library/LibraryBookDetail.vue'
import BookListTable, { type SortKey } from '@/components/library/BookListTable.vue'

const router = useRouter()
const uiStore = useUiStore()

// ── 状态 ──
const data = ref<LibraryData | null>(null)
const loading = ref(true)
const currentGenre = ref('全部')
const searchQuery = ref('')
const selectedBookIds = ref<Set<number>>(new Set())
const selectedBookIndex = ref<number | null>(null)
const sortKey = ref<SortKey>('title')
const sortDir = ref<'asc' | 'desc'>('asc')
const detailOpen = ref(false)

// ── 计算属性 ──
const allBooks = computed(() => data.value?.books ?? [])
const genres = computed(() => data.value?.genres ?? [])

const filteredBooks = computed(() => {
  let result = currentGenre.value === '全部'
    ? [...allBooks.value]
    : allBooks.value.filter((b) => b.genre === currentGenre.value)

  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    result = result.filter((b) =>
      (b.title && b.title.toLowerCase().includes(q)) ||
      (b.author && b.author.toLowerCase().includes(q)) ||
      (b.genre && b.genre.toLowerCase().includes(q))
    )
  }

  // 排序
  const dir = sortDir.value === 'asc' ? 1 : -1
  result.sort((a, b) => {
    let va: string | number, vb: string | number
    switch (sortKey.value) {
      case 'title': va = a.title || ''; vb = b.title || ''; break
      case 'author': va = a.author || ''; vb = b.author || ''; break
      case 'genre': va = a.genre || ''; vb = b.genre || ''; break
      case 'wordCount': va = a.wordCount || 0; vb = b.wordCount || 0; break
      case 'chapters':
        va = (a.disassembly?.chapters) || a.totalChapters || 0
        vb = (b.disassembly?.chapters) || b.totalChapters || 0
        break
      case 'status': va = a.status || ''; vb = b.status || ''; break
      default: va = a.title || ''; vb = b.title || ''
    }
    if (typeof va === 'string') return dir * va.localeCompare(vb as string, 'zh-CN')
    return dir * (va as number - (vb as number))
  })

  return result
})

// 题材标签计数
const tabCounts = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const base = q
    ? allBooks.value.filter((b) =>
        (b.title && b.title.toLowerCase().includes(q)) ||
        (b.author && b.author.toLowerCase().includes(q)) ||
        (b.genre && b.genre.toLowerCase().includes(q))
      )
    : allBooks.value

  const map: Record<string, number> = {}
  base.forEach((b) => { map[b.genre] = (map[b.genre] || 0) + 1 })
  return [['全部', base.length] as [string, number], ...genres.value.map((g) => [g, map[g] || 0] as [string, number])]
})

// KPI 统计
const kpiTotal = computed(() => allBooks.value.length)
const kpiChapters = computed(() => {
  const totalWords = allBooks.value.reduce((sum, b) => sum + (b.wordCount || 0), 0)
  return Math.round(totalWords / 2000)
})
const kpiPending = computed(() =>
  allBooks.value.filter((b) => !b.status || b.status === 'imported' || b.status === 'pending').length
)
const kpiGenres = computed(() => genres.value.length)

const selectedBook = computed(() => {
  if (selectedBookIndex.value === null) return null
  return allBooks.value[selectedBookIndex.value] ?? null
})

const allSelected = computed(() => {
  const indices = filteredBooks.value.map((b) => allBooks.value.indexOf(b))
  return indices.length > 0 && indices.every((idx) => selectedBookIds.value.has(idx))
})

// ── 方法 ──
function fmtNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

function filterGenre(genre: string) {
  currentGenre.value = genre
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

function toggleBookSelection(idx: number, event?: Event) {
  event?.stopPropagation()
  if (selectedBookIds.value.has(idx)) {
    selectedBookIds.value.delete(idx)
  } else {
    selectedBookIds.value.add(idx)
  }
  // 触发响应式
  selectedBookIds.value = new Set(selectedBookIds.value)
}

function toggleSelectAll() {
  const indices = filteredBooks.value.map((b) => allBooks.value.indexOf(b))
  if (allSelected.value) {
    indices.forEach((idx) => selectedBookIds.value.delete(idx))
  } else {
    indices.forEach((idx) => selectedBookIds.value.add(idx))
  }
  selectedBookIds.value = new Set(selectedBookIds.value)
}

function clearSelection() {
  selectedBookIds.value.clear()
  selectedBookIds.value = new Set()
}

function selectBook(idx: number) {
  selectedBookIndex.value = idx
  detailOpen.value = true
}

function onSelectBook(book: Book) {
  selectBook(allBooks.value.indexOf(book))
}

function onToggleSelection(book: Book) {
  toggleBookSelection(allBooks.value.indexOf(book))
}

function closeDetail() {
  detailOpen.value = false
  selectedBookIndex.value = null
}

async function startAnalysisFromDetail() {
  if (!selectedBook.value) return
  const res = await LibraryAPI.startAnalysis(selectedBook.value.genre, selectedBook.value.title)
  if (res.ok && res.data) {
    uiStore.showToast(res.data.message || '已启动分析', 'success')
    router.push({ name: 'disassembly' })
  } else {
    uiStore.showToast('启动分析失败', 'error')
  }
}

async function batchDisassemble() {
  if (selectedBookIds.value.size === 0) {
    uiStore.showToast('请先选择要拆书的书籍')
    return
  }
  uiStore.showToast('正在创建拆书任务...', 'info')
  const books = Array.from(selectedBookIds.value).map(String)
  const res = await DisassemblyAPI.createTask({
    type: 'disassembly',
    name: `批量拆书 ${books.length} 本`,
    books,
  })
  if (res.ok && res.data?.task) {
    uiStore.showToast(`已创建 ${selectedBookIds.value.size} 个拆书任务`, 'success')
    clearSelection()
    router.push('/disassembly')
  } else {
    uiStore.showToast(res.error || '创建拆书任务失败', 'error')
  }
}

// 导入书籍
const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const dragCounter = ref(0)

function importBook() {
  fileInput.value?.click()
}

function parseBookMeta(fileName: string) {
  const rawName = fileName.replace(/\.txt$/i, '')
  let title = rawName
  let author = '本地导入'
  const authorMatch = rawName.match(/作者[：:]\s*(.+)$/)
  if (authorMatch) {
    title = rawName.split(/作者[：:]/)[0].trim()
    author = authorMatch[1].trim()
  } else if (rawName.includes('_')) {
    const parts = rawName.split('_')
    title = parts[0].trim()
    author = parts.slice(1).join('_').trim() || '本地导入'
  }

  const genreHints: Record<string, string> = {
    '末世': '末世', '末日': '末世', '丧尸': '末世',
    '无限': '无限流', '恐怖': '悬疑', '惊悚': '悬疑',
    '仙侠': '仙侠', '洪荒': '洪荒', '科幻': '科幻',
    '都市': '都市', '历史': '历史',
  }
  let genre = '都市'
  for (const [hint, g] of Object.entries(genreHints)) {
    if (title.includes(hint)) { genre = g; break }
  }
  return { title, author, genre }
}

function importSingleFile(file: File): Promise<{ ok: boolean; title: string; error?: string }> {
  return new Promise((resolve) => {
    if (!file.name.toLowerCase().endsWith('.txt')) {
      resolve({ ok: false, title: file.name, error: '仅支持 .txt 文件' })
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const sizeKb = Math.round(file.size / 1024)
      const estimatedWords = Math.max(1, Math.round(file.size / 1.8))
      const { title, author, genre } = parseBookMeta(file.name)
      if (data.value) {
        data.value.books.unshift({
          title, author, wordCount: estimatedWords, size_kb: sizeKb,
          genre, file: file.name, status: 'imported',
        })
      }
      resolve({ ok: true, title })
    }
    reader.onerror = () => resolve({ ok: false, title: file.name, error: '文件读取失败' })
    reader.readAsText(file, 'utf-8')
  })
}

async function processFiles(files: FileList | null) {
  if (!files || files.length === 0) return
  const txtFiles = Array.from(files).filter((f) => f.name.toLowerCase().endsWith('.txt'))
  if (txtFiles.length === 0) {
    uiStore.showToast('未检测到 .txt 文件', 'error')
    return
  }
  const results = await Promise.all(txtFiles.map(importSingleFile))
  const okCount = results.filter((r) => r.ok).length
  const failCount = results.length - okCount
  currentGenre.value = '全部'
  searchQuery.value = ''
  if (failCount === 0) {
    uiStore.showToast(`成功导入 ${okCount} 本书`, 'success')
  } else {
    uiStore.showToast(`导入 ${okCount} 本成功，${failCount} 本失败`, 'info')
  }
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  processFiles(input.files)
  input.value = ''
}

function onDragEnter(e: DragEvent) {
  e.preventDefault()
  dragCounter.value++
  if (e.dataTransfer?.types.includes('Files')) dragOver.value = true
}

function onDragLeave(e: DragEvent) {
  e.preventDefault()
  dragCounter.value--
  if (dragCounter.value === 0) dragOver.value = false
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragCounter.value = 0
  dragOver.value = false
  processFiles(e.dataTransfer?.files ?? null)
}

// ── 生命周期 ──
onMounted(async () => {
  const res = await LibraryAPI.getBooks()
  if (res.ok && res.data) {
    data.value = res.data
  } else {
    data.value = { books: [], genres: [], counts: [], count: 0, genre: '全部' }
    uiStore.showToast('加载书库失败', 'error')
  }
  loading.value = false
})
</script>

<template>
  <div
    class="library-page"
    :class="{ 'detail-open': detailOpen, 'drag-over': dragOver }"
    @dragenter="onDragEnter"
    @dragleave="onDragLeave"
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <!-- 拖拽上传遮罩 -->
    <div v-if="dragOver" class="drop-overlay">
      <div class="drop-card">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        <div class="drop-title">释放以上传 .txt 书籍</div>
        <div class="drop-hint">支持多文件同时导入</div>
      </div>
    </div>

    <!-- 页头 -->
    <div class="page-header">
      <h2>书库</h2>
      <div class="header-actions">
        <button class="btn btn-secondary" @click="importBook">导入书籍</button>
        <input ref="fileInput" type="file" accept=".txt" style="display:none" @change="handleFileSelect" />
      </div>
    </div>

    <!-- 题材筛选条 + 搜索 -->
    <div class="library-toolbar">
      <div class="genre-tabs">
        <button
          v-for="[genre, count] in tabCounts"
          :key="genre"
          class="genre-tab"
          :class="{ active: currentGenre === genre }"
          @click="filterGenre(genre)"
        >{{ genre }}({{ count }})</button>
      </div>
      <input
        v-model="searchQuery"
        type="text"
        class="library-search"
        placeholder="搜索书名、作者、题材..."
      />
    </div>

    <!-- KPI 行 -->
    <div class="kpi-row">
      <KpiCard
        icon="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"
        color="indigo"
        :value="kpiTotal"
        label="总书籍"
      />
      <KpiCard
        icon="M4 6h16 M4 10h16 M4 14h16"
        color="amber"
        :value="fmtNumber(kpiChapters)"
        label="已拆章节"
      />
      <KpiCard
        icon="M21 8v13H3V8 M12 13l9-5H3l9 5z"
        color="emerald"
        :value="kpiPending"
        label="待处理"
      />
      <KpiCard
        icon="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"
        color="violet"
        :value="kpiGenres"
        label="题材数"
      />
    </div>

    <!-- 主体布局 -->
    <div class="library-layout">
      <div class="library-main">
        <!-- 书籍列表 -->
        <div class="library-table-wrap">
          <BookListTable
            :books="filteredBooks"
            :all-books="allBooks"
            :selected-ids="selectedBookIds"
            :sort-key="sortKey"
            :sort-dir="sortDir"
            :all-selected="allSelected"
            :loading="loading"
            :search-query="searchQuery"
            @select-book="onSelectBook"
            @toggle-selection="onToggleSelection"
            @toggle-select-all="toggleSelectAll"
            @sort-change="toggleSort"
            @clear-selection="clearSelection"
            @batch-disassemble="batchDisassemble"
          />
        </div>
      </div>

      <!-- 详情面板 -->
      <aside class="detail-panel" :class="{ open: detailOpen }">
        <LibraryBookDetail
          :book="selectedBook"
          :open="detailOpen"
          @close="closeDetail"
          @start-analysis="startAnalysisFromDetail"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped>
.library-page {
  position: relative;
  padding: 16px 24px;
  height: 100%;
  overflow-y: auto;
}
.library-page.drag-over { overflow: hidden; }

.drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 50;
  background: var(--overlay-bg);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
}
.drop-card {
  background: var(--surface-solid);
  border: 2px dashed var(--accent);
  border-radius: 16px;
  padding: 48px 64px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--accent);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
.drop-title { font-size: 18px; font-weight: 700; color: var(--text); }
.drop-hint { font-size: 13px; color: var(--text-secondary); }

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}


/* ── 工具栏 ── */
.library-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.genre-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.genre-tab {
  padding: 5px 14px;
  border: 1px solid var(--border-hover);
  border-radius: 16px;
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.genre-tab:hover {
  border-color: var(--accent);
  color: var(--text);
  background: var(--surface-hover);
}
.genre-tab.active {
  background: var(--accent);
  color: var(--bg);
  border-color: var(--accent);
  font-weight: 700;
  box-shadow: 0 1px 4px rgba(var(--accent-rgb), 0.25);
}
.library-search {
  width: 240px;
  padding: 6px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
}
.library-search:focus {
  outline: none;
  border-color: var(--accent);
}

/* ── KPI ── */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

/* ── 布局 ── */
.library-layout {
  display: flex;
  gap: 16px;
}
.library-main {
  flex: 1;
  min-width: 0;
}

/* ── 书籍列表 ── */
.library-table-wrap {
  background: var(--surface-solid);
  border: 1px solid var(--border-hover);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.library-content.list-view {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--text-secondary);
}
/* ── 书籍列表表格样式已移至 BookListTable 组件 ── */

/* ── 详情面板 ── */
.detail-panel {
  width: 0;
  overflow: hidden;
  transition: width 0.2s ease;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.detail-panel.open {
  width: 320px;
  flex-shrink: 0;
}

/* ── 按钮 — 全局 style.css 接管 ── */
.text-muted { color: var(--text-muted); }

/* ── 响应式 ── */
@media (max-width: 1200px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .kpi-row { grid-template-columns: 1fr; }
  .library-layout { flex-direction: column; }
  .detail-panel.open { width: 100%; }
}
</style>
