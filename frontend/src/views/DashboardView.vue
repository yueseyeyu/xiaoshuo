<script setup lang="ts">
/**
 * DashboardView — 工作台页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - Hero 区：项目信息 + 写作进度统计 / 空状态引导
 * - KPI 行：书库统计 + 技法卡片 + 分析状态
 * - 管线进度：实时轮询拆书管线状态（→ PipelineProgress 组件）
 * - 系统健康：GPU/VRAM/RAM/CPU 指标条（→ SystemHealthCard 组件）
 * - 快捷入口 + 创建项目模态框（→ CreateProjectModal 组件）
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { useVisibilityPause } from '@/composables/useVisibilityPause'
import { DashboardAPI, type ProgressData, type HardwareData, type ConfigData } from '@/api/dashboard'
import CreateProjectModal from '@/components/dashboard/CreateProjectModal.vue'
import PipelineProgress from '@/components/dashboard/PipelineProgress.vue'
import SystemHealthCard from '@/components/dashboard/SystemHealthCard.vue'
import KpiCard from '@/components/common/KpiCard.vue'

const router = useRouter()
const projectStore = useProjectStore()
const uiStore = useUiStore()

// ── 响应式状态 ──
const kpiBooks = ref(0)
const kpiGenres = ref(0)
const kpiCards = ref(0)
const kpiStatus = ref('空闲')

const progressData = ref<ProgressData | null>(null)
const hardware = ref<HardwareData | null>(null)
const config = ref<ConfigData | null>(null)

const showCreateModal = ref(false)

// ── 计算属性 ──
const hasProject = computed(() => projectStore.hasProject)
const currentProject = computed(() => projectStore.currentProject)
const isDemo = computed(() => currentProject.value?.is_demo ?? false)
const llmHealthy = computed(() => progressData.value?.llm_healthy ?? false)

const writingProgress = computed(() => {
  if (!currentProject.value) return 0
  const total = currentProject.value.meta.total_chapters
  const written = currentProject.value.meta.written_chapters
  return total ? Math.round((written / total) * 100) : 0
})

const nextChapter = computed(() => {
  if (!currentProject.value) return 1
  return (currentProject.value.meta.written_chapters || 0) + 1
})

function loadSetting(key: string, fallback: string): string {
  try {
    return localStorage.getItem('setting_' + key) ?? fallback
  } catch { return fallback }
}

const dailyGoal = computed(() => {
  const v = parseInt(loadSetting('targetWords', '2000'), 10)
  return Number.isFinite(v) && v > 0 ? v : 2000
})

// ── 数据加载 ──
async function loadKPIs() {
  const [booksRes, reportRes] = await Promise.all([
    DashboardAPI.getBooks(),
    DashboardAPI.getReportOverview(),
  ])
  if (booksRes.ok && booksRes.data) {
    kpiBooks.value = booksRes.data.count
    kpiGenres.value = (booksRes.data.genres || []).length
  }
  if (reportRes.ok && reportRes.data) {
    kpiCards.value = (reportRes.data.technique_cards || []).length
    const ra = reportRes.data.rhythm_audit
    kpiStatus.value = ra && ra.passed > 0 ? `${ra.passed}/${ra.total_books} 通过` : '空闲'
  }
}

async function loadProgress() {
  const res = await DashboardAPI.getProgress()
  if (res.ok && res.data) {
    progressData.value = res.data
  }
}

async function loadHardware() {
  const res = await DashboardAPI.getHardware()
  if (res.ok && res.data) {
    hardware.value = res.data
  }
}

async function loadConfig() {
  const res = await DashboardAPI.getConfig()
  if (res.ok && res.data) {
    config.value = res.data
  }
}

// ── 轮询 ──
const { start: startProgressPolling, stop: stopProgressPolling } = useVisibilityPause(loadProgress, 3000)
const { start: startHardwarePolling, stop: stopHardwarePolling } = useVisibilityPause(loadHardware, 5000)

function startPolling() {
  startProgressPolling()
  startHardwarePolling()
}

function stopPolling() {
  stopProgressPolling()
  stopHardwarePolling()
}

// ── 操作 ──
async function loadDemo() {
  uiStore.showToast('正在加载示例项目...', 'info')
  const ok = await projectStore.loadDemoProject()
  if (ok) {
    uiStore.showToast('已加载示例项目', 'success')
  } else {
    uiStore.showToast('加载示例项目失败', 'error')
  }
}

async function exitDemo() {
  await projectStore.exitDemoProject()
  uiStore.showToast('已退出示例项目', 'info')
}

async function stopAnalysis() {
  const res = await DashboardAPI.stopAnalysis()
  if (res.ok && res.data) {
    uiStore.showToast(res.data.message || '已停止', 'success')
    await loadProgress()
  }
}

function navigate(name: string) {
  router.push({ name })
}

// ── 生命周期 ──
onMounted(async () => {
  await projectStore.loadProjects()
  if (!projectStore.hasProject) {
    const demo = projectStore.projects.find((p) => p.is_demo)
    if (demo) {
      await projectStore.loadProject(demo.id)
    }
  }
  await Promise.all([loadKPIs(), loadProgress(), loadHardware(), loadConfig()])
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="dashboard-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-header-main">
        <h2>工作台</h2>
        <span class="page-header-badge">
          {{ hasProject ? currentProject?.meta.genre || '未设置题材' : '未开始创作' }}
        </span>
      </div>
      <span v-if="hasProject" class="page-header-meta">
        {{ currentProject?.meta.written_chapters || 0 }} / {{ currentProject?.meta.total_chapters || 0 }} 章
      </span>
    </div>

    <div class="dashboard-workstation" :class="{ 'no-project': !hasProject }">
      <!-- ═══ 主区域 ═══ -->
      <div class="dashboard-main">
        <!-- ── 当前项目 Hero（视觉重心）── -->
        <div v-if="hasProject" class="project-hero hero-station">
          <div class="hero-main-row">
            <div class="hero-info">
              <span class="hero-genre">{{ currentProject?.meta.genre || '未设置题材' }}</span>
              <h1 class="hero-title">{{ currentProject?.meta.title || '未命名作品' }}</h1>
              <div class="hero-author">{{ currentProject?.meta.author || '未设置作者' }}</div>
              <div class="hero-book-meta">
                <span>{{ currentProject?.meta.volumes_count || 0 }} 卷</span>
                <span class="dot">·</span>
                <span>{{ (currentProject?.meta.total_chapters || 0) }} 章</span>
              </div>
            </div>

            <div class="hero-center-stats">
              <div class="hero-stat">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                <div>
                  <span class="hero-stat-value">{{ currentProject?.meta.written_chapters || 0 }}</span>
                  <span class="hero-stat-label">已写章节</span>
                </div>
              </div>
              <div class="hero-stat">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                <div>
                  <span class="hero-stat-value">{{ kpiCards }}</span>
                  <span class="hero-stat-label">可用技法</span>
                </div>
              </div>
              <div class="hero-stat">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                <div>
                  <span class="hero-stat-value">{{ kpiStatus }}</span>
                  <span class="hero-stat-label">分析状态</span>
                </div>
              </div>
            </div>

            <div class="hero-progress-cta">
              <div class="progress-ring" :style="{ '--progress': writingProgress / 100 }">
                <svg viewBox="0 0 100 100">
                  <circle class="track" cx="50" cy="50" r="42" />
                  <circle class="fill" cx="50" cy="50" r="42" />
                </svg>
                <div class="progress-text">
                  <b>{{ writingProgress }}%</b>
                  <span>总进度</span>
                </div>
              </div>
              <div class="hero-today-focus">
                <div class="hero-today-label">今日写作</div>
                <div class="hero-today-chapter">第 {{ nextChapter }} 章</div>
                <div class="hero-today-goal">目标 {{ dailyGoal.toLocaleString() }} 字</div>
                <button class="btn btn-primary hero-main-action" @click="navigate('writing')">继续写作</button>
              </div>
            </div>
          </div>

          <div class="hero-secondary-row">
            <button class="hero-link" @click="navigate('design')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
              <span>查看大纲</span>
            </button>
            <button class="hero-link" @click="navigate('reports')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>
              <span>数据报告</span>
            </button>
            <button v-if="isDemo" class="hero-link" @click="exitDemo">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              <span>退出示例</span>
            </button>
          </div>
        </div>

        <!-- ── 空状态 ── -->
        <div v-else class="empty-state">
          <div class="empty-state-icon">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
              <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
            </svg>
          </div>
          <h1 class="empty-state-title">开始你的第一部作品</h1>
          <p class="empty-state-desc">拆书、节奏分析、技法提取与写作辅助，全部围绕你的创作流程设计</p>

          <!-- 工作流引导 -->
          <div class="workflow-guide">
            <div class="workflow-guide-title">创作工作流</div>
            <div class="workflow-guide-subtitle">从零到上线，让第一本书在番茄小说发布</div>
            <div class="workflow-steps">
              <div class="workflow-step-card" @click="showCreateModal = true">
                <div class="workflow-step-num">1</div>
                <div class="workflow-step-text"><b>创建作品</b><span>设定题材、卷数、总章数</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('library')">
                <div class="workflow-step-num">2</div>
                <div class="workflow-step-text"><b>导入参考书</b><span>从书库挑选代表作</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('disassembly')">
                <div class="workflow-step-num">3</div>
                <div class="workflow-step-text"><b>拆书+解构</b><span>提取节奏、技法</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('design')">
                <div class="workflow-step-num">4</div>
                <div class="workflow-step-text"><b>设计大纲</b><span>粗纲、细纲、角色</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('writing')">
                <div class="workflow-step-num">5</div>
                <div class="workflow-step-text"><b>开始写作</b><span>目标门控辅助</span></div>
              </div>
            </div>
          </div>

          <div class="empty-state-actions">
            <button class="btn btn-primary" @click="showCreateModal = true">创建新作品</button>
            <button class="btn btn-secondary" @click="navigate('library')">导入参考书籍</button>
          </div>
          <button class="btn btn-ghost btn-sm" @click="loadDemo">查看示例项目</button>
        </div>

        <!-- ── 内容网格 ── -->
        <div v-if="hasProject" class="content-bento">
          <!-- KPI 卡片 -->
          <KpiCard
            icon="M4 19.5A2.5 2.5 0 0 1 6.5 17H20 M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
            color="indigo"
            :value="kpiBooks"
            label="已入库书籍"
          />
          <KpiCard
            icon="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"
            color="violet"
            :value="kpiGenres"
            label="题材类型"
          />
          <KpiCard
            icon="M12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
            color="amber"
            :value="kpiCards"
            label="技法卡片"
          />
          <KpiCard
            icon="M22 12h-4l-3 9L9 3l-3 9H2"
            color="accent"
            :value="kpiStatus"
            label="分析状态"
          />
        </div>

        <!-- ── 管线进度（子组件）── -->
        <div class="pipeline-section">
          <div class="section-heading">
            <span class="section-title">管线进度</span>
            <span class="section-subtitle">实时拆书与分析任务</span>
          </div>
          <PipelineProgress :progress-data="progressData" @stop="stopAnalysis" />
          <div v-if="!progressData?.running" class="pipeline-quick-actions">
            <button class="pipeline-quick-btn" @click="navigate('library')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
              导入新书
            </button>
            <button class="pipeline-quick-btn" @click="navigate('writing')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              继续写作
            </button>
          </div>
        </div>
      </div>

      <!-- ═══ 侧边栏 ═══ -->
      <aside class="dashboard-sidebar">
        <!-- 系统健康（子组件） -->
        <SystemHealthCard :hardware="hardware" :config="config" :llm-healthy="llmHealthy" />

        <!-- 创作状态摘要 -->
        <div class="side-card project-status">
          <div class="side-card-title">创作状态</div>
          <div class="status-row">
            <span class="status-dot" :class="{ active: llmHealthy }"></span>
            <span class="status-text">{{ llmHealthy ? '本地模型在线' : '本地模型离线' }}</span>
          </div>
          <div class="status-progress-track">
            <div class="status-progress-bar" :style="{ width: writingProgress + '%' }"></div>
          </div>
          <div class="status-progress-meta">
            <span>总进度</span>
            <b>{{ writingProgress }}%</b>
          </div>
          <div class="status-hint">{{ currentProject?.meta.title || '未命名作品' }} · 第 {{ nextChapter }} 章待写</div>
        </div>

        <!-- 快捷入口 -->
        <div class="side-card quick-links">
          <div class="side-card-title">快捷入口</div>
          <div class="quick-links-grid">
            <button class="quick-link-tile" @click="navigate('library')">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
              <span>书库</span>
            </button>
            <button class="quick-link-tile" @click="navigate('disassembly')">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>
              <span>拆书</span>
            </button>
            <button class="quick-link-tile" @click="navigate('reports')">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>
              <span>报告</span>
            </button>
            <button class="quick-link-tile" @click="navigate('writing')">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>写作</span>
            </button>
            <button class="quick-link-tile" @click="navigate('world')">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10H12V2z"/></svg>
              <span>世界</span>
            </button>
            <button class="quick-link-tile" @click="navigate('settings')">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82V9a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              <span>设置</span>
            </button>
          </div>
        </div>
      </aside>
    </div>

    <!-- ═══ 创建项目模态框（子组件） ═══ -->
    <CreateProjectModal v-model:show="showCreateModal" />
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 16px 24px;
  height: 100%;
  overflow-y: auto;
}

/* ── 页头 ── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-header-main {
  display: flex;
  align-items: center;
  gap: 12px;
}
.page-header-badge {
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(var(--accent-rgb), 0.1);
  border: 1px solid rgba(var(--accent-rgb), 0.15);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
}
.page-header-meta {
  color: var(--text-secondary);
  font-size: 13px;
}

/* ── 工作台布局 ── */
.dashboard-workstation {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 20px;
}

/* ── 项目 Hero ── */
.project-hero.hero-station {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px 26px;
  margin-bottom: 20px;
  background:
    radial-gradient(1200px 400px at 80% -20%, rgba(var(--accent-rgb), 0.08), transparent),
    linear-gradient(145deg, var(--surface) 0%, rgba(var(--accent-rgb), 0.04) 100%);
  border: 1px solid rgba(var(--accent-rgb), 0.14);
  box-shadow:
    0 20px 48px rgba(0, 0, 0, 0.12),
    inset 0 1px 0 rgba(var(--text-rgb), 0.08);
}

.hero-main-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 24px;
}

.hero-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 240px;
  flex: 0 1 auto;
}

.hero-genre {
  align-self: flex-start;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(var(--accent-rgb), 0.12);
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
}

.hero-title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
  margin: 0;
  letter-spacing: -0.02em;
}

.hero-author {
  font-size: 13px;
  color: var(--text-secondary);
}

.hero-book-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.hero-book-meta .dot { color: var(--text-muted); }

.hero-center-stats {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.hero-stat {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(var(--text-rgb), 0.04);
  border: 1px solid rgba(var(--text-rgb), 0.1);
  backdrop-filter: blur(4px);
}

.hero-stat svg {
  color: var(--accent);
  flex-shrink: 0;
}

.hero-stat-value {
  display: block;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}

.hero-stat-label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
}

.hero-progress-cta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  min-width: 140px;
}

.progress-ring {
  position: relative;
  width: 96px;
  height: 96px;
  flex-shrink: 0;
}
.progress-ring svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.progress-ring circle {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
}
.progress-ring .track {
  stroke: rgba(var(--text-rgb),0.08);
}
.progress-ring .fill {
  stroke: var(--accent);
  stroke-dasharray: 264;
  stroke-dashoffset: calc(264 * (1 - var(--progress, 0)));
  transition: stroke-dashoffset 0.6s ease;
  filter: drop-shadow(0 0 6px rgba(var(--accent-rgb), 0.35));
}
.progress-text {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1.1;
}
.progress-text b {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
}
.progress-text span {
  font-size: 10px;
  color: var(--text-secondary);
}

.hero-today-focus {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  text-align: center;
}

.hero-today-label {
  font-size: 11px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.hero-today-chapter {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.1;
}

.hero-today-goal {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.hero-main-action {
  padding: 10px 22px;
  font-size: 14px;
  font-weight: 700;
  border-radius: 12px;
  box-shadow:
    0 8px 22px rgba(var(--accent-rgb), 0.32),
    inset 0 1px 0 rgba(var(--text-rgb), 0.25);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.hero-main-action:hover {
  transform: translateY(-1px);
  box-shadow:
    0 12px 28px rgba(var(--accent-rgb), 0.4),
    inset 0 1px 0 rgba(var(--text-rgb), 0.3);
}

.hero-main-action:active {
  transform: translateY(0);
}

.hero-secondary-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 12px;
  border-top: 1px solid rgba(var(--text-rgb), 0.06);
}

.hero-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.hero-link:hover {
  color: var(--text);
  background: rgba(var(--text-rgb), 0.05);
}

.hero-link svg {
  color: var(--text-muted);
  flex-shrink: 0;
  transition: color 0.15s ease;
}

.hero-link:hover svg {
  color: var(--accent);
}

/* ── 内容 Bento ── */
.content-bento {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  grid-template-rows: repeat(2, 120px);
  gap: 14px;
  margin-bottom: 20px;
}

.bento-card {
  background:
    linear-gradient(180deg, rgba(var(--text-rgb), 0.05) 0%, var(--surface) 100%);
  border: 1px solid rgba(var(--text-rgb), 0.12);
  border-radius: 16px;
  padding: 16px;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.bento-card:hover {
  border-color: rgba(var(--text-rgb), 0.16);
  background:
    linear-gradient(180deg, rgba(var(--text-rgb), 0.06) 0%, var(--surface-hover) 100%);
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14);
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 24px;
  text-align: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  margin-bottom: 20px;
}
.empty-state-icon {
  color: var(--text-muted);
  margin-bottom: 16px;
}
.empty-state-title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 8px;
}
.empty-state-desc {
  color: var(--text-secondary);
  font-size: 14px;
  margin-bottom: 24px;
}
.workflow-guide {
  width: 100%;
  margin-bottom: 24px;
}
.workflow-guide-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}
.workflow-guide-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}
.workflow-steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}
.workflow-step-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--surface-solid);
}
.workflow-step-card:hover {
  border-color: var(--accent);
  background: var(--surface-hover);
}
.workflow-step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent);
  color: white;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.workflow-step-text {
  display: flex;
  flex-direction: column;
  text-align: left;
  font-size: 13px;
}
.workflow-step-text span {
  font-size: 11px;
  color: var(--text-secondary);
}
.workflow-step-arrow {
  color: var(--text-muted);
  font-size: 18px;
}
.empty-state-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

/* ── 管线进度区 ── */
.pipeline-section {
  background:
    linear-gradient(180deg, rgba(var(--text-rgb), 0.04) 0%, var(--surface) 100%);
  border: 1px solid rgba(var(--text-rgb), 0.1);
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

.section-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 14px;
}
.section-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
.section-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
}

.pipeline-quick-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}
.pipeline-quick-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid rgba(var(--text-rgb), 0.1);
  background: rgba(var(--text-rgb), 0.04);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.pipeline-quick-btn:hover {
  background: rgba(var(--text-rgb), 0.08);
  color: var(--text);
  border-color: rgba(var(--text-rgb), 0.16);
}

/* ── 侧边栏 ── */
.dashboard-sidebar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 16px;
  align-self: start;
  height: fit-content;
}
.side-card {
  background:
    linear-gradient(180deg, rgba(var(--text-rgb), 0.04) 0%, var(--surface) 100%);
  border: 1px solid rgba(var(--text-rgb), 0.1);
  border-radius: 16px;
  padding: 18px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}
.side-card-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text);
}

/* 创作状态摘要 */
.project-status {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-secondary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  box-shadow: 0 0 0 3px rgba(var(--text-rgb), 0.04);
}

.status-dot.active {
  background: var(--success, #34d399);
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.12);
}

.status-progress-track {
  height: 6px;
  border-radius: 999px;
  background: rgba(var(--text-rgb), 0.08);
  overflow: hidden;
}

.status-progress-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), rgba(var(--accent-rgb), 0.7));
  transition: width 0.5s ease;
}

.status-progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary);
}

.status-progress-meta b {
  color: var(--text);
  font-weight: 700;
}

.status-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
  padding-top: 4px;
  border-top: 1px solid rgba(var(--text-rgb), 0.06);
}

.quick-links-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.quick-link-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 18px 4px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(var(--text-rgb), 0.03);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  text-align: center;
  transition: all 0.15s;
}
.quick-link-tile:hover {
  background: var(--surface-hover);
  border-color: var(--border-hover);
  color: var(--text);
}
.quick-link-tile svg {
  color: var(--text-muted);
}
.quick-link-tile:hover svg {
  color: var(--accent);
}

/* ── 响应式 ── */
@media (max-width: 1300px) {
  .hero-main-row {
    gap: 18px;
  }
  .hero-center-stats {
    gap: 8px;
  }
}

@media (max-width: 1200px) {
  .dashboard-workstation {
    grid-template-columns: 1fr;
  }
  .dashboard-sidebar {
    flex-direction: row;
  }
  .dashboard-sidebar > * {
    flex: 1;
  }
  .quick-links-grid {
    grid-template-columns: repeat(6, 1fr);
  }
}

@media (max-width: 1024px) {
  .hero-main-row {
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 20px;
  }
  .hero-info {
    flex: 1 1 100%;
    min-width: 0;
  }
  .hero-center-stats {
    justify-content: flex-start;
    flex: 1;
  }
  .hero-progress-cta {
    flex-direction: row;
    align-items: center;
    margin-left: auto;
  }
  .hero-main-action {
    align-items: flex-start;
  }
  .hero-action-text {
    align-items: flex-start;
  }
}

@media (max-width: 900px) {
  .content-bento {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: auto;
  }
  .focus-card {
    grid-row: span 1;
    grid-column: span 2;
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
  }
  .focus-body {
    flex: 1;
  }
}

@media (max-width: 768px) {
  .dashboard-page {
    padding: 14px 16px;
  }
  .hero-main-row {
    flex-direction: column;
    align-items: stretch;
  }
  .hero-progress-cta {
    flex-direction: row;
    justify-content: space-between;
    margin-left: 0;
  }
  .hero-main-action {
    width: auto;
    align-items: center;
  }
  .hero-action-text {
    align-items: center;
  }
  .hero-secondary-row {
    width: 100%;
    justify-content: flex-start;
  }
  .dashboard-sidebar {
    flex-direction: column;
  }
  .quick-links-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .content-bento {
    grid-template-columns: 1fr;
  }
  .focus-card {
    grid-column: span 1;
    flex-direction: column;
    align-items: flex-start;
  }
  .workflow-steps {
    flex-direction: column;
  }
  .workflow-step-arrow {
    transform: rotate(90deg);
  }
}
</style>
