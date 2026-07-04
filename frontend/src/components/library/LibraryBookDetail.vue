<script setup lang="ts">
/**
 * LibraryBookDetail — 书库书籍详情面板
 * 从 LibraryView 拆分，展示封面/元数据/标签/操作按钮
 */
import type { Book } from '@/api/library'

defineProps<{
  book: Book | null
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'startAnalysis'): void
}>()

function fmtNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

function fmtSize(kb: number): string {
  if (kb >= 1024) return (kb / 1024).toFixed(1) + ' MB'
  return kb + ' KB'
}

function coverText(title: string): string {
  if (!title) return '?'
  const clean = title.replace(/《|》/g, '')
  return clean.length <= 2 ? clean : clean.slice(0, 2)
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
</script>

<template>
  <div class="detail-content" v-if="book">
    <button class="detail-close icon-btn" @click="emit('close')">×</button>
    <div class="detail-cover" :style="{ background: coverStyle(book.title, book.genre) }">
      <span class="cover-abbr">{{ coverText(book.title) }}</span>
    </div>
    <h3 class="detail-title">{{ book.title }}</h3>
    <div class="detail-meta">
      <div>作者：{{ book.author || '' }}</div>
      <div>题材：{{ book.genre || '' }}</div>
      <div>字数：{{ fmtNumber(book.wordCount || 0) }} 字</div>
      <div>大小：{{ fmtSize(book.size_kb || 0) }}</div>
    </div>
    <div class="detail-tags">
      <span
        v-for="(tag, i) in (book.tags?.length ? book.tags : [book.genre]).filter(Boolean)"
        :key="tag"
        class="book-tag"
        :class="{ 'book-tag-primary': i === 0 }"
      >{{ tag }}</span>
    </div>
    <div class="detail-actions">
      <button class="btn btn-primary" @click="emit('startAnalysis')">
        {{ book.status === 'analyzed' ? '重新分析' : '开始分析' }}
      </button>
    </div>
  </div>
  <div v-else class="detail-empty">选择一本书查看详情</div>
</template>

<style scoped>
.detail-content {
  padding: 20px;
  position: relative;
}
.detail-close {
  position: absolute;
  top: 12px;
  right: 12px;
}
.detail-cover {
  width: 80px;
  height: 100px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}
.cover-abbr {
  font-size: 24px;
  font-weight: 700;
  color: white;
  text-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
.detail-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
}
.detail-meta {
  font-size: 13px;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}
.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 16px;
}
.detail-actions {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.detail-empty {
  display: none;
}

.book-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--surface-hover);
  color: var(--text-secondary);
  margin-right: 4px;
}
.book-tag-primary {
  background: var(--accent);
  color: #0a0a0a;
}

.icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-btn:hover { background: var(--surface-hover); }
</style>