<script setup lang="ts">
/**
 * ChapterToc — 写作页左侧章节目录
 * 从 WritingView 提取，纯展示 + emit 跳转/折叠事件。
 */
import { ref } from 'vue'

defineProps<{
  currentChapter: number
  totalChapters: number
  volumeList: Array<{ idx: number; start: number; end: number; title: string; chapters: number[] }>
  recentChapters: Array<{ num: number; title: string }>
  getChapterTitle: (num: number) => string
}>()

const emit = defineEmits<{
  jumpToChapter: [num: number]
  toggleVolume: [idx: number]
}>()

const collapsedVolumes = ref<Set<number>>(new Set())

function toggleVolume(idx: number) {
  if (collapsedVolumes.value.has(idx)) collapsedVolumes.value.delete(idx)
  else collapsedVolumes.value.add(idx)
  emit('toggleVolume', idx)
}

function isCollapsed(idx: number) {
  return collapsedVolumes.value.has(idx)
}
</script>

<template>
  <aside class="writing-toc">
    <div class="toc-header">
      <h4>章节目录</h4>
      <span class="toc-count">{{ totalChapters }} 章</span>
    </div>
    <div class="toc-body">
      <!-- 最近修改 -->
      <div class="toc-section">
        <div class="toc-section-title">最近修改</div>
        <div
          v-for="rc in recentChapters"
          :key="rc.num"
          class="toc-recent-item"
          :class="{ current: rc.num === currentChapter }"
          @click="emit('jumpToChapter', rc.num)"
        >
          {{ rc.num }} {{ rc.title }}
        </div>
      </div>
      <!-- 按卷列表 -->
      <div class="toc-section">
        <div
          v-for="vol in volumeList"
          :key="vol.idx"
          class="toc-volume"
          :class="{ collapsed: isCollapsed(vol.idx) }"
        >
          <div class="toc-vol-title" @click="toggleVolume(vol.idx)">
            <span class="toc-chevron">{{ isCollapsed(vol.idx) ? '▸' : '▾' }}</span>
            {{ vol.title }} ({{ vol.start }}-{{ vol.end }}章)
          </div>
          <div v-show="!isCollapsed(vol.idx)" class="toc-vol-chapters">
            <div
              v-for="ch in vol.chapters"
              :key="ch"
              class="toc-chapter"
              :class="{ current: ch === currentChapter }"
              @click="emit('jumpToChapter', ch)"
            >{{ ch }} {{ getChapterTitle(ch) }}</div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.writing-toc { width: 240px; flex-shrink: 0; border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
.toc-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--border); }
.toc-header h4 { font-size: 13px; font-weight: 600; }
.toc-count { font-size: 11px; color: var(--text-secondary); }
.toc-body { flex: 1; overflow-y: auto; padding: 8px; }
.toc-section { margin-bottom: 12px; }
.toc-section-title { font-size: 11px; color: var(--text-secondary); padding: 4px 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.toc-recent-item { padding: 4px 8px; font-size: 12px; cursor: pointer; border-radius: 4px; transition: background 0.15s; }
.toc-recent-item:hover { background: var(--surface-hover); }
.toc-recent-item.current { background: rgba(56, 189, 248, 0.08); color: var(--accent); }
.toc-volume { margin-bottom: 4px; }
.toc-vol-title { display: flex; align-items: center; gap: 4px; padding: 6px 8px; font-size: 12px; font-weight: 600; cursor: pointer; border-radius: 4px; }
.toc-vol-title:hover { background: var(--surface-hover); }
.toc-chevron { font-size: 10px; width: 12px; }
.toc-vol-chapters { padding-left: 16px; }
.toc-chapter { padding: 3px 8px; font-size: 12px; cursor: pointer; border-radius: 4px; transition: background 0.15s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.toc-chapter:hover { background: var(--surface-hover); }
.toc-chapter.current { background: rgba(56, 189, 248, 0.08); color: var(--accent); }

@media (max-width: 1024px) { .writing-toc { width: 200px; } }
@media (max-width: 768px) { .writing-toc { display: none; } }
</style>
