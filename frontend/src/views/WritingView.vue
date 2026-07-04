<script setup lang="ts">
/**
 * WritingView — 写作页面
 *
 * 三栏布局：章节目录 (ChapterToc) | 编辑器 | 参考面板 (WritingSidebar)
 * 工具栏：章节上下文、上下章导航、字数统计、保存状态
 * 快捷键：Ctrl+S 保存，Ctrl+[ 上一章，Ctrl+] 下一章
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { ProjectAPI } from '@/api/project'
import { DashboardAPI, type SceneResult } from '@/api/dashboard'
import { CreativeAPI } from '@/api/creative'
import type { Character, SkeletonChapter, Volume } from '@/types'
import ChapterToc from '@/components/writing/ChapterToc.vue'
import WritingSidebar from '@/components/writing/WritingSidebar.vue'

const projectStore = useProjectStore()
const uiStore = useUiStore()

// ── 状态 ──
const currentChapter = ref(1)
const chapterTitle = ref('')
const chapterContent = ref('')
const saveStatus = ref<'saved' | 'unsaved'>('saved')

// ── 场景搜索 ──
const searchQuery = ref('')
const searchResults = ref<SceneResult[]>([])
const searchLoading = ref(false)
const showSearchPanel = ref(false)

async function doSearch() {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  showSearchPanel.value = true
  const res = await DashboardAPI.search(searchQuery.value, projectStore.projectGenre || '末世', 10)
  if (res.ok && res.data) {
    searchResults.value = res.data.results || []
  }
  searchLoading.value = false
}

// ── 合规扫描 ──
const complianceResult = ref<{ ok: boolean; risk_level: string; total_count: number; ai_rate: number; ai_rate_level: string } | null>(null)
const complianceLoading = ref(false)

async function doComplianceScan() {
  if (!chapterContent.value.trim()) return
  complianceLoading.value = true
  const res = await CreativeAPI.complianceScan(chapterContent.value)
  if (res.ok && res.data) {
    complianceResult.value = res.data
  }
  complianceLoading.value = false
}
const loading = ref(false)

const projectChapters = ref<Array<{ num: number; title: string; word_count?: number }>>([])
const skeletonVolumes = ref<Volume[]>([])
const skeletonChapters = ref<SkeletonChapter[]>([])
const projectCharacters = ref<Character[]>([])

// ── 计算属性 ──
const hasProject = computed(() => projectStore.hasProject)
const currentProject = computed(() => projectStore.currentProject)
const totalChapters = computed(() => currentProject.value?.meta.total_chapters ?? 300)

const wordCount = computed(() => (chapterContent.value || '').replace(/\s/g, '').length)
const targetWords = 2000
const wordPct = computed(() => Math.min(100, Math.round((wordCount.value / targetWords) * 100)))

const paraCount = computed(() => {
  const paras = (chapterContent.value || '').split(/\n\s*\n/).filter(Boolean)
  const last = paras[paras.length - 1] || ''
  return last.replace(/\s/g, '').length
})

const eta = computed(() => {
  const remain = Math.max(0, targetWords - wordCount.value)
  const minutes = Math.ceil(remain / 30)
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`
})

const todayCount = computed(() => {
  try {
    const key = 'writing_today_' + new Date().toDateString()
    return parseInt(localStorage.getItem(key) || '0', 10)
  } catch { return 0 }
})

const volSize = 60
const currentVolIndex = computed(() => Math.floor((currentChapter.value - 1) / volSize))
const currentVolTitle = computed(() => {
  const v = skeletonVolumes.value[currentVolIndex.value]
  return v ? `${v.title} · ${v.subtitle || ''}` : `第${currentVolIndex.value + 1}卷`
})

const recentChapters = computed(() => {
  return [currentChapter.value, currentChapter.value - 1, currentChapter.value - 7]
    .filter(c => c > 0)
    .map(c => ({ num: c, title: getChapterTitle(c) }))
})

const volumeList = computed(() => {
  const total = totalChapters.value
  if (total === 0) return []
  const numVols = Math.ceil(total / volSize)
  const result: Array<{ idx: number; start: number; end: number; title: string; chapters: number[] }> = []
  for (let i = 0; i < numVols; i++) {
    const start = i * volSize + 1
    const end = Math.min((i + 1) * volSize, total)
    const chapters: number[] = []
    for (let c = start; c <= end; c++) chapters.push(c)
    result.push({ idx: i, start, end, title: `第${i + 1}卷`, chapters })
  }
  return result
})

// ── 方法 ──
function getChapterTitle(num: number): string {
  const ch = projectChapters.value.find(c => c.num === num)
  return ch?.title || `第 ${num} 章`
}

async function loadChapter(num: number) {
  if (!currentProject.value?.id) return
  await saveChapter()
  currentChapter.value = num
  loading.value = true
  try {
    const res = await ProjectAPI.getChapter(currentProject.value.id, num)
    if (res.ok && res.data) {
      chapterTitle.value = res.data.title || getChapterTitle(num)
      chapterContent.value = res.data.content || ''
    } else {
      chapterTitle.value = getChapterTitle(num)
      chapterContent.value = ''
    }
  } catch {
    chapterTitle.value = getChapterTitle(num)
    chapterContent.value = ''
  }
  loading.value = false
  saveStatus.value = 'saved'
}

function prevChapter() { if (currentChapter.value > 1) loadChapter(currentChapter.value - 1) }
function nextChapter() { if (currentChapter.value < totalChapters.value) loadChapter(currentChapter.value + 1) }
function jumpToChapter(num: number) { loadChapter(num) }

async function saveChapter() {
  if (!currentProject.value?.id) return
  const title = chapterTitle.value || getChapterTitle(currentChapter.value)
  const content = chapterContent.value || ''
  const wc = content.replace(/\s/g, '').length
  try {
    await ProjectAPI.updateChapter(currentProject.value.id, currentChapter.value, {
      title, content, word_count: wc,
    })
    const todayKey = 'writing_today_' + new Date().toDateString()
    const lastKey = `writing_last_saved_${currentProject.value.id}_${currentChapter.value}`
    const prevLast = parseInt(localStorage.getItem(lastKey) || '0', 10)
    const diff = wc - prevLast
    if (diff > 0) {
      const prevToday = parseInt(localStorage.getItem(todayKey) || '0', 10)
      localStorage.setItem(todayKey, String(prevToday + diff))
    }
    localStorage.setItem(lastKey, String(wc))
    saveStatus.value = 'saved'
  } catch {
    uiStore.showToast('保存失败', 'error')
  }
}

async function saveDraft() {
  await saveChapter()
  uiStore.showToast('已保存到项目')
}

function onContentInput() { saveStatus.value = 'unsaved' }

// ── 键盘快捷键 ──
function onKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && e.key.toLowerCase() === 's') { e.preventDefault(); saveDraft() }
  if (e.ctrlKey && e.key === '[') { e.preventDefault(); prevChapter() }
  if (e.ctrlKey && e.key === ']') { e.preventDefault(); nextChapter() }
}

// ── 生命周期 ──
async function loadAllData() {
  if (!currentProject.value?.id) return
  loading.value = true
  try {
    const [chapsRes, skelRes, charRes] = await Promise.all([
      ProjectAPI.getChapters(currentProject.value.id),
      ProjectAPI.getSkeleton(currentProject.value.id),
      ProjectAPI.getCharacters(currentProject.value.id),
    ])
    if (chapsRes.ok && chapsRes.data) projectChapters.value = chapsRes.data
    if (skelRes.ok && skelRes.data) {
      skeletonVolumes.value = skelRes.data.volumes || []
      skeletonChapters.value = skelRes.data.chapters || []
    }
    if (charRes.ok && charRes.data) projectCharacters.value = charRes.data
    await loadChapter(1)
  } catch {
    uiStore.showToast('加载写作数据失败', 'error')
  }
  loading.value = false
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  if (hasProject.value && currentProject.value?.id) await loadAllData()
})

onUnmounted(() => { window.removeEventListener('keydown', onKeydown) })

watch(() => currentProject.value?.id, async (newId) => {
  if (newId) {
    await loadAllData()
  } else {
    projectChapters.value = []
    skeletonVolumes.value = []
    skeletonChapters.value = []
    projectCharacters.value = []
    chapterContent.value = ''
    chapterTitle.value = ''
  }
})
</script>

<template>
  <div class="writing-page">
    <!-- 无项目空状态 -->
    <div v-if="!hasProject" class="writing-empty">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.3;margin-bottom:16px;">
        <path d="M12 19l7-7 3 3-7 7-3-3z" /><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" /><path d="M2 2l7.586 7.586" />
      </svg>
      <h3>尚未选择创作作品</h3>
      <p>写作页与你正在创作的作品绑定。<br>先去工作台创建一个项目，或查看示例项目体验。</p>
      <button class="btn btn-primary" @click="$router.push('/dashboard')">去工作台</button>
    </div>

    <template v-else>
      <!-- 工具栏 -->
      <div class="writing-toolbar">
        <div class="toolbar-left">
          <div class="chapter-context">
            <span class="ctx-book">{{ currentProject?.meta.title || '未命名' }}</span>
            <span class="ctx-sep">·</span>
            <span class="ctx-vol">{{ currentVolTitle }}</span>
            <span class="ctx-sep">·</span>
            <span class="ctx-chap">第{{ currentChapter }} 章 / {{ totalChapters }} 章</span>
          </div>
          <div class="chapter-nav">
            <button class="btn btn-icon btn-sm" title="上一章 (Ctrl+[)" :disabled="currentChapter <= 1" @click="prevChapter">←</button>
            <div class="chap-progress-group">
              <span class="chap-progress-text">本章 {{ wordCount }} / {{ targetWords }} 字 · {{ wordPct }}%</span>
              <div class="progress-mini"><div class="progress-mini-bar" :style="{ width: wordPct + '%' }" /></div>
            </div>
            <button class="btn btn-icon btn-sm" title="下一章 (Ctrl+])" :disabled="currentChapter >= totalChapters" @click="nextChapter">→</button>
          </div>
        </div>
        <div class="toolbar-right">
          <div class="search-box">
            <input
              v-model="searchQuery"
              class="search-input"
              placeholder="搜索场景..."
              @keyup.enter="doSearch"
            />
            <button class="btn btn-ghost btn-sm" :disabled="searchLoading" @click="doSearch">
              {{ searchLoading ? '搜索中...' : '搜索' }}
            </button>
          </div>
          <span class="word-count">{{ wordCount }} / {{ targetWords }} 字</span>
          <span class="save-status" :class="{ unsaved: saveStatus === 'unsaved' }">
            <span class="save-dot" />{{ saveStatus === 'unsaved' ? '未保存' : '已保存' }}
          </span>
          <button class="btn btn-secondary btn-sm" :disabled="complianceLoading" @click="doComplianceScan">
            {{ complianceLoading ? '扫描中...' : '合规扫描' }}
          </button>
          <button class="btn btn-primary btn-sm" @click="saveDraft">保存草稿</button>
        </div>
      </div>

      <!-- 三栏布局 -->
      <div class="writing-layout">
        <!-- 左侧：章节目录 -->
        <ChapterToc
          :current-chapter="currentChapter"
          :total-chapters="totalChapters"
          :volume-list="volumeList"
          :recent-chapters="recentChapters"
          :get-chapter-title="getChapterTitle"
          @jump-to-chapter="jumpToChapter"
        />

        <!-- 中间：编辑器 -->
        <div class="editor-pane">
          <div class="editor-header">
            <div class="editor-breadcrumbs">
              <span>第{{ currentVolIndex + 1 }}卷</span>
              <span class="breadcrumb-sep">/</span>
              <span>第{{ currentChapter }} 章</span>
            </div>
            <input v-model="chapterTitle" class="editor-title" placeholder="章节标题" @input="onContentInput" />
          </div>
          <textarea
            v-model="chapterContent"
            class="editor-textarea"
            placeholder="开始写作..."
            @input="onContentInput"
          />
          <div class="editor-footer">
            <div class="footer-left">
              <span>本段 {{ paraCount }} 字</span>
            </div>
            <div class="footer-center">
              <span>预计 {{ eta }}</span>
              <span class="footer-sep">·</span>
              <span>今日 {{ todayCount.toLocaleString() }} 字</span>
            </div>
            <div class="footer-right">
              <span>目标 {{ targetWords }} 字</span>
            </div>
          </div>
        </div>

        <!-- 右侧：参考面板 -->
        <WritingSidebar
          :chapter-content="chapterContent"
          :current-chapter="currentChapter"
          :total-chapters="totalChapters"
          :project-characters="projectCharacters"
          :skeleton-chapters="skeletonChapters"
          :skeleton-volumes="skeletonVolumes"
          :current-project="currentProject"
        />
      </div>
    </template>

    <!-- 合规扫描结果 -->
    <div v-if="complianceResult" class="compliance-panel" :class="complianceResult.ok ? 'pass' : 'fail'">
      <div class="compliance-header">
        <span>合规扫描: {{ complianceResult.risk_level === 'low' ? '低风险' : complianceResult.risk_level === 'medium' ? '中风险' : '高风险' }}</span>
        <span>AI率: {{ complianceResult.ai_rate }}% ({{ complianceResult.ai_rate_level }})</span>
        <button class="btn btn-ghost btn-sm" @click="complianceResult = null">×</button>
      </div>
      <div class="compliance-body">
        <span>命中 {{ complianceResult.total_count }} 处指纹词</span>
      </div>
    </div>

    <!-- 场景搜索结果 -->
    <div v-if="showSearchPanel" class="search-panel">
      <div class="search-panel-header">
        <span>场景搜索: "{{ searchQuery }}" ({{ searchResults.length }} 条)</span>
        <button class="btn btn-ghost btn-sm" @click="showSearchPanel = false">×</button>
      </div>
      <div v-if="searchResults.length === 0" class="text-muted" style="padding:12px">无结果</div>
      <div v-else class="search-result-list">
        <div v-for="r in searchResults" :key="r.rank" class="search-result-item">
          <div class="search-result-header">
            <span class="search-result-book">{{ r.book_name }} 第{{ r.chapter }}章</span>
            <span class="search-result-meta">{{ r.emotion }} · {{ r.pace }} · 冲突{{ r.conflict_level }}</span>
          </div>
          <div class="search-result-preview">{{ r.text_preview }}</div>
          <div class="search-result-technique">{{ r.technique_summary }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.writing-page { height: 100%; display: flex; flex-direction: column; overflow: hidden; }

/* 空状态 */
.writing-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; text-align: center; }
.writing-empty h3 { font-size: 20px; font-weight: 600; margin-bottom: 8px; }
.writing-empty p { font-size: 14px; color: var(--text-secondary); margin-bottom: 20px; line-height: 1.6; }

/* 工具栏 */
.writing-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.toolbar-left { display: flex; align-items: center; gap: 16px; }
.toolbar-right { display: flex; align-items: center; gap: 10px; }
.chapter-context { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-secondary); }
.ctx-book { font-weight: 600; color: var(--text); }
.ctx-sep { opacity: 0.5; }
.chapter-nav { display: flex; align-items: center; gap: 6px; }
.chap-progress-group { display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 160px; }
.chap-progress-text { font-size: 11px; color: var(--text-secondary); }
.progress-mini { width: 100px; height: 3px; background: var(--surface-solid); border-radius: 2px; overflow: hidden; }
.progress-mini-bar { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.2s; }
.word-count { font-size: 12px; color: var(--text-secondary); }
.save-status { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-secondary); }
.save-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); }
.save-status.unsaved .save-dot { background: var(--warning); }

/* 三栏布局 */
.writing-layout { display: flex; flex: 1; overflow: hidden; }

/* 编辑器 */
.editor-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.editor-header { padding: 10px 16px; border-bottom: 1px solid var(--border); }
.editor-breadcrumbs { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }
.breadcrumb-sep { opacity: 0.5; }
.editor-title { width: 100%; border: none; background: transparent; color: var(--text); font-size: 18px; font-weight: 600; outline: none; }
.editor-title::placeholder { color: var(--text-muted); }
.editor-textarea { flex: 1; border: none; background: transparent; color: var(--text); font-size: 15px; line-height: 1.8; padding: 16px; resize: none; outline: none; font-family: inherit; }
.editor-textarea::placeholder { color: var(--text-muted); }
.editor-footer { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text-secondary); }
.footer-center { display: flex; align-items: center; gap: 4px; }
.footer-sep { opacity: 0.5; }

/* ── 合规扫描面板 ── */
.compliance-panel { padding: 10px 16px; border-top: 1px solid var(--border); font-size: 12px; }
.compliance-panel.pass { background: rgba(34,197,94,0.06); }
.compliance-panel.fail { background: rgba(239,68,68,0.06); }
.compliance-header { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.compliance-header span:first-child { font-weight: 600; }
.compliance-body { color: var(--text-secondary); }

/* ── 场景搜索 ── */
.search-box { display: flex; align-items: center; gap: 4px; }
.search-input { width: 120px; padding: 3px 8px; background: var(--surface-solid); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-size: 12px; }
.search-input:focus { outline: none; border-color: var(--accent); }
.search-panel { position: fixed; bottom: 0; left: 0; right: 0; max-height: 280px; overflow-y: auto; background: var(--bg-elevated); border-top: 1px solid var(--border); z-index: 50; }
.search-panel-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; border-bottom: 1px solid var(--border); font-size: 13px; font-weight: 600; }
.search-result-list { padding: 8px 16px; display: flex; flex-direction: column; gap: 8px; }
.search-result-item { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.search-result-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
.search-result-book { font-size: 12px; font-weight: 600; color: var(--accent); }
.search-result-meta { font-size: 10px; color: var(--text-muted); }
.search-result-preview { font-size: 12px; color: var(--text-secondary); line-height: 1.5; margin-bottom: 4px; }
.search-result-technique { font-size: 10px; color: var(--text-muted); }

/* ── 按钮 — 全局 style.css 接管 ── */

@media (max-width: 1024px) { .editor-pane { font-size: 14px; } }
@media (max-width: 768px) { .editor-pane { flex: 1; } }
</style>
