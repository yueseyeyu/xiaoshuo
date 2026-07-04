<script setup lang="ts">
/**
 * LibraryView — 书库页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - 题材标签筛选 + 搜索
 * - 题材热度排行条
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

// 题材热度统计（基于搜索/筛选后的书）
const genreRank = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const base = q
    ? allBooks.value.filter((b) =>
        (b.title && b.title.toLowerCase().includes(q)) ||
        (b.author && b.author.toLowerCase().includes(q)) ||
        (b.genre && b.genre.toLowerCase().includes(q))
      )
    : allBooks.value

  const map: Record<string, number> = {}
  base.forEach((b) => {
    map[b.genre] = (map[b.genre] || 0) + 1
  })
  const total = base.length
  return Object.entries(map)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([genre, count]) => ({ genre, count, pct: total > 0 ? (count / total) * 100 : 0 }))
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

function batchDisassemble() {
  if (selectedBookIds.value.size === 0) {
    uiStore.showToast('请先选择要拆书的书籍')
    return
  }
  uiStore.showToast(`已创建 ${selectedBookIds.value.size} 个拆书任务`, 'success')
  clearSelection()
  router.push({ name: 'disassembly' })
}

// 导入书籍
const fileInput = ref<HTMLInputElement | null>(null)

function importBook() {
  fileInput.value?.click()
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (_evt) => {
    const sizeKb = Math.round(file.size / 1024)
    const estimatedWords = Math.max(1, Math.round(file.size / 1.8))
    const rawName = file.name.replace(/\.txt$/i, '')

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

    // 添加到本地数据
    if (data.value) {
      data.value.books.unshift({
        title, author, wordCount: estimatedWords, size_kb: sizeKb,
        genre, file: file.name, status: 'imported',
      })
    }
    currentGenre.value = '全部'
    searchQuery.value = ''
    uiStore.showToast(`已导入《${title}》(${fmtNumber(estimatedWords)} 字)`, 'success')
  }
  reader.onerror = () => uiStore.showToast('文件读取失败', 'error')
  reader.readAsText(file, 'utf-8')
  input.value = ''
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
  <div class="library-page" :class="{ 'detail-open': detailOpen }">
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
      <div class="kpi-card kpi-indigo">
        <div class="kpi-value">{{ kpiTotal }}</div>
        <div class="kpi-label">总书籍</div>
      </div>
      <div class="kpi-card kpi-amber">
        <div class="kpi-value">{{ fmtNumber(kpiChapters) }}</div>
        <div class="kpi-label">已拆章节</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{{ kpiPending }}</div>
        <div class="kpi-label">待处理</div>
      </div>
      <div class="kpi-card kpi-violet">
        <div class="kpi-value">{{ kpiGenres }}</div>
        <div class="kpi-label">题材数</div>
      </div>
    </div>

    <!-- 主体布局 -->
    <div class="library-layout">
      <div class="library-main">
        <!-- 题材热度排行 -->
        <div class="genre-rank-bar" v-if="genreRank.length">
          <div class="genre-rank-title">题材热度</div>
          <div class="genre-rank-list">
            <button
              v-for="item in genreRank"
              :key="item.genre"
              class="genre-rank-item"
              :class="{ active: currentGenre === item.genre }"
              :title="`${item.genre} 占 ${item.pct.toFixed(1)}% · 点击筛选`"
              @click="filterGenre(item.genre)"
            >
              <span class="genre-rank-name">{{ item.genre }}</span>
              <div class="genre-rank-bar-track">
                <div class="genre-rank-fill" :style="{ width: Math.max(2, item.pct) + '%' }" />
              </div>
              <span class="genre-rank-count">{{ item.count }}</span>
            </button>
          </div>
        </div>

        <!-- 书籍列表 -->
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
  padding: 16px 24px;
  height: 100%;
  overflow-y: auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 18px;
  font-weight: 600;
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
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.genre-tab:hover {
  border-color: var(--border-hover);
  color: var(--text);
}
.genre-tab.active {
  background: var(--accent);
  color: #0a0a0a;
  border-color: var(--accent);
  font-weight: 600;
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
.kpi-card {
  /* padding/background/border/radius 由全局 style.css 接管 */
}
.kpi-card:hover {
  /* hover 由全局 style.css 接管 */
}
.kpi-value { font-size: 22px; font-weight: 700; }
.kpi-label { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.kpi-indigo .kpi-value { color: var(--indigo); }
.kpi-violet .kpi-value { color: var(--violet); }
.kpi-amber .kpi-value { color: var(--amber); }

/* ── 布局 ── */
.library-layout {
  display: flex;
  gap: 16px;
}
.library-main {
  flex: 1;
  min-width: 0;
}

/* ── 题材热度 ── */
.genre-rank-bar {
  margin-bottom: 16px;
}
.genre-rank-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.genre-rank-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.genre-rank-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
  transition: all 0.15s;
}
.genre-rank-item:hover {
  border-color: var(--border-hover);
}
.genre-rank-item.active {
  border-color: var(--accent);
  background: rgba(56, 189, 248, 0.08);
}
.genre-rank-name {
  font-size: 12px;
  color: var(--text);
}
.genre-rank-bar-track {
  width: 60px;
  height: 4px;
  background: var(--surface-solid);
  border-radius: 2px;
  overflow: hidden;
}
.genre-rank-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
}
.genre-rank-count {
  font-size: 11px;
  color: var(--text-secondary);
}

/* ── 书籍列表 ── */
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
