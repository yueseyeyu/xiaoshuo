<script setup lang="ts">
/**
 * BookListTable — 书库书籍列表表格
 * 接收书籍数据，管理排序/多选/批量操作
 */
import { ref, computed } from 'vue'
import type { Book } from '@/api/library'

export type SortKey = 'title' | 'author' | 'genre' | 'wordCount' | 'chapters' | 'status'

const ITEM_HEIGHT = 48
const VISIBLE_COUNT = 12
const BUFFER = 4

const props = defineProps<{
  books: Book[]
  allBooks: Book[]
  selectedIds: Set<number>
  sortKey: SortKey
  sortDir: 'asc' | 'desc'
  allSelected: boolean
  loading: boolean
  searchQuery: string
}>()

const emit = defineEmits<{
  (e: 'select-book', book: Book): void
  (e: 'toggle-selection', book: Book): void
  (e: 'toggle-select-all'): void
  (e: 'sort-change', key: SortKey): void
  (e: 'clear-selection'): void
  (e: 'batch-disassemble'): void
}>()

// ── 虚拟滚动 ──
const bodyRef = ref<HTMLDivElement | null>(null)
const scrollTop = ref(0)

const virtualState = computed(() => {
  const total = props.books.length
  const start = Math.max(0, Math.floor(scrollTop.value / ITEM_HEIGHT) - BUFFER)
  const end = Math.min(total, start + VISIBLE_COUNT + BUFFER * 2)
  const offsetY = start * ITEM_HEIGHT
  const totalHeight = total * ITEM_HEIGHT
  const visible = props.books.slice(start, end)
  return { start, end, offsetY, totalHeight, visible }
})

function onScroll() {
  scrollTop.value = bodyRef.value?.scrollTop ?? 0
}

function bookKey(b: Book): string {
  const idx = props.allBooks.indexOf(b)
  return idx >= 0 ? `book-${idx}` : `${b.title}-${b.author}-${b.genre}`
}

// ── 工具函数 ──
function fmtNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

function getBookStatus(b: Book): { label: string; cls: string } {
  if (b.status === 'analyzed') return { label: '已拆书', cls: 'success' }
  if (b.status === 'analyzing') return { label: '分析中', cls: 'running' }
  if (b.status === 'failed') return { label: '失败', cls: 'danger' }
  return { label: '待分析', cls: 'pending' }
}

function coverStyle(_title: string, genre: string): string {
  const palette: Record<string, string> = {
    '末世': 'linear-gradient(135deg, #ef4444, #b91c1c)',
    '仙侠': 'linear-gradient(135deg, #22c55e, #15803d)',
    '科幻': 'linear-gradient(135deg, #3b82f6, #1d4ed8)',
    '都市': 'linear-gradient(135deg, #f59e0b, #b45309)',
    '悬疑': 'linear-gradient(135deg, #6366f1, #4338ca)',
    '无限流': 'linear-gradient(135deg, #8b5cf6, #6d28d9)',
    '历史': 'linear-gradient(135deg, #a16207, #713f12)',
    '奇幻': 'linear-gradient(135deg, #06b6d4, #0e7490)',
    '洪荒': 'linear-gradient(135deg, #84cc16, #4d7c0f)',
    '同人': 'linear-gradient(135deg, #ec4899, #be185d)',
  }
  return palette[genre] || 'linear-gradient(135deg, #64748b, #334155)'
}

function sortArrow(key: SortKey): string {
  if (props.sortKey !== key) return ''
  return props.sortDir === 'asc' ? ' \u2191' : ' \u2193'
}

const sortColumns = [
  { key: 'title', label: '书名' },
  { key: 'author', label: '作者' },
  { key: 'genre', label: '题材' },
] as const
</script>

<template>
  <div class="library-content list-view">
    <template v-if="loading">
      <div class="empty-state">加载中...</div>
    </template>
    <template v-else-if="books.length === 0">
      <div class="empty-state">
        {{ searchQuery ? `未找到含「${searchQuery}」的书籍` : '暂无该题材书籍' }}
      </div>
    </template>
    <template v-else>
      <!-- 表头 -->
      <div class="book-list-header">
        <div class="book-list-col col-check">
          <label class="book-list-checkbox" @click.stop="emit('toggle-select-all')">
            <input type="checkbox" :checked="allSelected" />
            <span></span>
          </label>
        </div>
        <button
          v-for="col in sortColumns"
          :key="col.key"
          class="book-list-col"
          :class="[`col-${col.key}`, { active: sortKey === col.key }]"
          @click="emit('sort-change', col.key)"
        >{{ col.label }}{{ sortArrow(col.key) }}</button>
        <div class="book-list-col col-tags">标签</div>
        <button
          class="book-list-col col-wordCount"
          :class="{ active: sortKey === 'wordCount' }"
          @click="emit('sort-change', 'wordCount')"
        >字数{{ sortArrow('wordCount') }}</button>
        <button
          class="book-list-col col-chapters"
          :class="{ active: sortKey === 'chapters' }"
          @click="emit('sort-change', 'chapters')"
        >章节{{ sortArrow('chapters') }}</button>
        <button
          class="book-list-col col-status"
          :class="{ active: sortKey === 'status' }"
          @click="emit('sort-change', 'status')"
        >状态{{ sortArrow('status') }}</button>
      </div>

      <!-- 书籍行（虚拟滚动） -->
      <div ref="bodyRef" class="book-list-body" @scroll="onScroll">
        <div class="virtual-spacer" :style="{ height: virtualState.offsetY + 'px' }" />
        <div
          v-for="b in virtualState.visible"
          :key="bookKey(b)"
          class="book-list-row"
          :class="{ selected: selectedIds.has(allBooks.indexOf(b)) }"
          @click="emit('select-book', b)"
        >
          <div class="book-list-col col-check" @click.stop>
            <label class="book-list-checkbox" @click.stop="emit('toggle-selection', b)">
              <input type="checkbox" :checked="selectedIds.has(allBooks.indexOf(b))" />
              <span></span>
            </label>
          </div>
          <div class="book-list-col col-title">
            <span class="book-list-title">{{ b.title }}</span>
          </div>
          <div class="book-list-col col-author">{{ b.author || '' }}</div>
          <div class="book-list-col col-genre">
            <span class="book-list-dot" :style="{ background: coverStyle(b.title, b.genre) }" />
            <span class="book-list-genre">{{ b.genre || '' }}</span>
          </div>
          <div class="book-list-col col-tags">
            <span
              v-for="(tag, i) in (b.tags?.length ? b.tags : [b.genre]).slice(0, 4)"
              :key="tag"
              class="book-tag"
              :class="{ 'book-tag-primary': i === 0 }"
            >{{ tag }}</span>
          </div>
          <div class="book-list-col col-wordCount">{{ fmtNumber(b.wordCount || 0) }}</div>
          <div class="book-list-col col-chapters">
            <template v-if="(b.disassembly?.chapters || b.totalChapters || 0) > 0">
              {{ fmtNumber(b.disassembly?.chapters || b.totalChapters || 0) }}
            </template>
            <span v-else class="text-muted">-</span>
          </div>
          <div class="book-list-col col-status">
            <span class="book-list-status" :class="getBookStatus(b).cls">{{ getBookStatus(b).label }}</span>
          </div>
        </div>
        <div
          class="virtual-spacer"
          :style="{ height: Math.max(0, virtualState.totalHeight - virtualState.offsetY - virtualState.visible.length * ITEM_HEIGHT) + 'px' }"
        />
      </div>

      <!-- 批量操作栏 -->
      <div v-if="selectedIds.size > 0" class="book-list-batch-bar">
        <span class="batch-count">已选 {{ selectedIds.size }} 本</span>
        <div class="batch-actions">
          <button class="btn btn-secondary btn-sm" @click="emit('clear-selection')">取消选择</button>
          <button class="btn btn-primary btn-sm" @click="emit('batch-disassemble')">批量拆书</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 列表视图 */
.book-list-header {
  display: grid;
  grid-template-columns: 36px 1.5fr 0.8fr 0.8fr 1fr 0.6fr 0.5fr 0.6fr;
  gap: 0;
  padding: 0;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 8px 8px 0 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.book-list-col {
  display: flex; align-items: center; padding: 10px 8px;
  border: none; background: none; color: inherit; font-size: inherit; cursor: pointer;
}
.book-list-col.active { color: var(--accent); }
.col-check { justify-content: center; }
.book-list-checkbox {
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.book-list-checkbox input { display: none; }
.book-list-checkbox span {
  width: 16px; height: 16px; border: 1.5px solid var(--border); border-radius: 3px;
  background: var(--surface); transition: all 0.15s;
}
.book-list-checkbox input:checked + span {
  background: var(--accent); border-color: var(--accent);
}
.book-list-body {
  border: 1px solid var(--border); border-top: none; border-radius: 0 0 8px 8px;
  overflow-y: auto;
  height: 576px;
}
.virtual-spacer { flex-shrink: 0; }
.book-list-row {
  display: grid;
  grid-template-columns: 36px 1.5fr 0.8fr 0.8fr 1fr 0.6fr 0.5fr 0.6fr;
  gap: 0;
  padding: 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.1s;
  height: 48px;
  box-sizing: border-box;
}
.book-list-row:last-child { border-bottom: none; }
.book-list-row:hover { background: var(--surface-hover); }
.book-list-row.selected { background: rgba(56,189,248,0.06); }
.book-list-title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.book-list-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.book-list-genre { font-size: 12px; color: var(--text-secondary); }
.book-tag { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--surface-hover); color: var(--text-secondary); margin-right: 4px; }
.book-tag-primary { background: rgba(56,189,248,0.12); color: var(--accent); }
.book-list-status { font-size: 11px; padding: 2px 8px; border-radius: 3px; }
.book-list-status.success { color: var(--success); background: rgba(34,197,94,0.1); }
.book-list-status.running { color: var(--info); background: rgba(56,189,248,0.1); }
.book-list-status.danger { color: var(--danger); background: rgba(239,68,68,0.1); }
.book-list-status.pending { color: var(--text-secondary); background: var(--surface-hover); }
.book-list-batch-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; margin-top: 8px;
  background: rgba(56,189,248,0.06); border: 1px solid var(--accent); border-radius: 8px;
}
.batch-count { font-size: 13px; font-weight: 500; }
.batch-actions { display: flex; gap: 8px; }
.empty-state { padding: 40px; text-align: center; color: var(--text-secondary); }
.text-muted { color: var(--text-secondary); font-size: 11px; }
</style>