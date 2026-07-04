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
import { DashboardAPI, type ProgressData, type HardwareData, type ConfigData, type IndexStats } from '@/api/dashboard'
import CreateProjectModal from '@/components/dashboard/CreateProjectModal.vue'
import PipelineProgress from '@/components/dashboard/PipelineProgress.vue'
import SystemHealthCard from '@/components/dashboard/SystemHealthCard.vue'

const router = useRouter()
const projectStore = useProjectStore()
const uiStore = useUiStore()

// ── 响应式状态 ──
const kpiBooks = ref(0)
const kpiGenres = ref(0)
const kpiCards = ref(0)
const kpiStatus = ref('空闲')
const indexStats = ref<IndexStats | null>(null)

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

// ── 问候语 ──
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  if (h < 22) return '晚上好'
  return '夜深了'
})

// ── 数据加载 ──
async function loadKPIs() {
  const [booksRes, reportRes, statsRes] = await Promise.all([
    DashboardAPI.getBooks(),
    DashboardAPI.getReportOverview(),
    DashboardAPI.getStats(),
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
  if (statsRes.ok && statsRes.data) {
    indexStats.value = statsRes.data
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
let progressTimer: ReturnType<typeof setInterval> | null = null
let hardwareTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  stopPolling()
  progressTimer = setInterval(async () => {
    await loadProgress()
  }, 3000)
  hardwareTimer = setInterval(async () => {
    await loadHardware()
  }, 5000)
}

function stopPolling() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  if (hardwareTimer) { clearInterval(hardwareTimer); hardwareTimer = null }
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
      <h2>工作台{{ hasProject ? '· ' + (currentProject?.meta.title || '未命名作品') : '' }}</h2>
      <span class="text-muted">
        {{ hasProject
          ? `${currentProject?.meta.genre || '未设置'} · ${currentProject?.meta.written_chapters || 0}/${currentProject?.meta.total_chapters || 0} 章`
          : '当前无进行中的项目' }}
      </span>
    </div>

    <div class="dashboard-workstation" :class="{ 'no-project': !hasProject }">
      <!-- ═══ 主区域 ═══ -->
      <div class="dashboard-main">
        <!-- ── Hero 区（有项目）── -->
        <div v-if="hasProject" class="hero-station">
          <div class="hero-left">
            <div class="hero-greeting">{{ greeting }}，{{ currentProject?.meta.author || '作者' }}</div>
            <h1 class="hero-title">{{ currentProject?.meta.title || '未命名作品' }}</h1>
            <div class="hero-meta">
              <span>{{ currentProject?.meta.volumes_count || 0 }}</span> 卷 ·
              <span>{{ currentProject?.meta.total_chapters || 0 }}</span> 章 ·
              当前处理题材：<span class="hero-genre">{{ currentProject?.meta.genre || '未设置' }}</span>
            </div>
            <div class="hero-actions">
              <button class="btn btn-primary" @click="navigate('writing')">继续写作</button>
              <button class="btn btn-secondary" @click="navigate('design')">查看大纲</button>
              <button v-if="isDemo" class="btn btn-ghost btn-sm" @click="exitDemo">退出示例项目</button>
            </div>
          </div>
          <div class="hero-right">
            <div class="hero-stat kpi-indigo">
              <span class="hero-stat-value">{{ currentProject?.meta.written_chapters || 0 }}</span>
              <span class="hero-stat-label">已写章节</span>
            </div>
            <div class="hero-stat kpi-dynamic">
              <span class="hero-stat-value">{{ writingProgress }}%</span>
              <span class="hero-stat-label">总进度</span>
            </div>
            <div class="hero-stat kpi-amber">
              <span class="hero-stat-value">{{ kpiCards }}</span>
              <span class="hero-stat-label">技法卡</span>
            </div>
            <div v-if="indexStats" class="hero-stat kpi-indigo">
              <span class="hero-stat-value">{{ indexStats.total_scenes }}</span>
              <span class="hero-stat-label">场景索引</span>
            </div>
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
            <div class="workflow-guide-title">创作工作流（MVP 路径）</div>
            <div class="workflow-guide-subtitle">从零到上线，30 天让第一本书在番茄小说发布</div>
            <div class="workflow-steps">
              <div class="workflow-step-card" @click="showCreateModal = true">
                <div class="workflow-step-num">1</div>
                <div class="workflow-step-text"><b>创建作品</b><span>设定题材、卷数、总章数</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('library')">
                <div class="workflow-step-num">2</div>
                <div class="workflow-step-text"><b>导入参考书</b><span>从书库挑选 3-5 本代表作</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('disassembly')">
                <div class="workflow-step-num">3</div>
                <div class="workflow-step-text"><b>拆书+解构</b><span>提取节奏、技法、可借鉴元素</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('design')">
                <div class="workflow-step-num">4</div>
                <div class="workflow-step-text"><b>设计大纲</b><span>粗纲、细纲、角色、世界观</span></div>
              </div>
              <span class="workflow-step-arrow">→</span>
              <div class="workflow-step-card" @click="navigate('writing')">
                <div class="workflow-step-num">5</div>
                <div class="workflow-step-text"><b>开始写作</b><span>目标门控+心智模型辅助</span></div>
              </div>
            </div>
          </div>

          <div class="empty-state-actions">
            <button class="btn btn-primary" @click="showCreateModal = true">创建新作品</button>
            <button class="btn btn-secondary" @click="navigate('library')">导入参考书籍</button>
          </div>
          <button class="btn btn-ghost btn-sm" @click="loadDemo">查看示例项目</button>
        </div>

        <!-- ── KPI 行 ── -->
        <div class="kpi-row">
          <div class="kpi-card kpi-indigo">
            <div class="kpi-value">{{ kpiBooks }}</div>
            <div class="kpi-label">已入库</div>
          </div>
          <div class="kpi-card kpi-violet">
            <div class="kpi-value">{{ kpiGenres }}</div>
            <div class="kpi-label">题材类型</div>
          </div>
          <div class="kpi-card kpi-amber">
            <div class="kpi-value">{{ kpiCards }}</div>
            <div class="kpi-label">技法卡片</div>
          </div>
          <div class="kpi-card kpi-dynamic">
            <div class="kpi-value">{{ kpiStatus }}</div>
            <div class="kpi-label">分析状态</div>
          </div>
        </div>

        <!-- ── 管线进度（子组件） ── -->
        <PipelineProgress :progress-data="progressData" @stop="stopAnalysis" />
      </div>

      <!-- ═══ 侧边栏 ═══ -->
      <aside class="dashboard-sidebar">
        <!-- 系统健康（子组件） -->
        <SystemHealthCard :hardware="hardware" :config="config" :llm-healthy="llmHealthy" />

        <!-- 写作进度 -->
        <div v-if="hasProject" class="side-card">
          <div class="side-card-title">写作进度</div>
          <div class="writing-progress-card">
            <div class="progress-ring-lg">{{ writingProgress }}%</div>
            <div class="progress-info">
              <b>第{{ (currentProject?.meta.written_chapters || 0) + 1 }}章</b>
              <span>{{ currentProject?.meta.written_chapters || 0 }}/{{ currentProject?.meta.total_chapters || 0 }} 章</span>
            </div>
          </div>
        </div>

        <!-- 快捷入口 -->
        <div class="side-card">
          <div class="side-card-title">快捷入口</div>
          <div class="quick-links-list">
            <button class="quick-link-row" @click="navigate('library')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h7v2H4zm0 5h7v2H4zm0 5h7v2H4zm9-10h7v2h-7zm0 5h7v2h-7zm0 5h7v2h-7z"/></svg>
              书库
            </button>
            <button class="quick-link-row" @click="navigate('disassembly')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.08-3.08a6 6 0 0 1-7.06 7.06l-6.36 6.36a2.5 2.5 0 1 1-3.54-3.54l6.36-6.36a6 6 0 0 1 7.06-7.06l-2.08 2.08z"/></svg>
              拆书
            </button>
            <button class="quick-link-row" @click="navigate('reports')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 17v-2H4.5A2.5 2.5 0 0 1 2 12.5v-9A2.5 2.5 0 0 1 4.5 1h9A2.5 2.5 0 0 1 16 3.5V9h-2V3.5a.5.5 0 0 0-.5-.5h-9a.5.5 0 0 0-.5.5v9a.5.5 0 0 0 .5.5H9zm9.5 7h-9a2.5 2.5 0 0 1-2.5-2.5v-9a2.5 2.5 0 0 1 2.5-2.5h9a2.5 2.5 0 0 1 2.5 2.5v9a2.5 2.5 0 0 1-2.5 2.5z"/></svg>
              报告
            </button>
            <button class="quick-link-row" @click="navigate('writing')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              写作
            </button>
            <button class="quick-link-row" @click="navigate('world')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2a8 8 0 0 1 8 8h-3a5 5 0 0 0-5-5V4zm0 16a8 8 0 0 1-8-8h3a5 5 0 0 0 5 5v3z"/></svg>
              世界推演
            </button>
            <button class="quick-link-row" @click="navigate('settings')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 2a5 5 0 1 1 0-10 5 5 0 0 1 0 10z"/></svg>
              设置
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
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 18px;
  font-weight: 600;
}
.text-muted {
  color: var(--text-secondary);
  font-size: 13px;
}

/* ── 工作台布局 ── */
.dashboard-workstation {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 16px;
}
.dashboard-workstation.no-project {
  grid-template-columns: 1fr 320px;
}

/* ── Hero 区 ── */
.hero-station {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  overflow: hidden;
}
.hero-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hero-greeting {
  font-size: 13px;
  color: var(--text-secondary);
}
.hero-title {
  font-size: 24px;
  font-weight: 700;
}
.hero-meta {
  font-size: 13px;
  color: var(--text-secondary);
}
.hero-genre {
  color: var(--accent);
}
.hero-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.hero-right {
  display: flex;
  gap: 12px;
}
.hero-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 20px;
  border-radius: 10px;
  background: var(--hero-stat-bg);
  border: 1px solid var(--border);
  min-width: 80px;
}
.hero-stat-value {
  font-size: 24px;
  font-weight: 700;
}
.hero-stat-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.kpi-indigo .hero-stat-value { color: var(--indigo); }
.kpi-amber .hero-stat-value { color: var(--amber); }
.kpi-dynamic .hero-stat-value { color: var(--accent); }

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 24px;
  text-align: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 16px;
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

/* ── KPI 行 ── */
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
.kpi-value {
  font-size: 22px;
  font-weight: 700;
}
.kpi-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.kpi-indigo .kpi-value { color: var(--indigo); }
.kpi-violet .kpi-value { color: var(--violet); }
.kpi-amber .kpi-value { color: var(--amber); }
.kpi-dynamic .kpi-value { color: var(--accent); }

/* ── 侧边栏 ── */
.dashboard-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.side-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
}
.side-card-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text);
}

/* 写作进度 */
.writing-progress-card {
  display: flex;
  align-items: center;
  gap: 16px;
}
.progress-ring-lg {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: var(--accent);
  flex-shrink: 0;
}
.progress-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}
.progress-info b {
  font-size: 14px;
}
.progress-info span {
  color: var(--text-secondary);
}

/* 快捷入口 */
.quick-links-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.quick-link-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.quick-link-row:hover {
  background: var(--surface-hover);
  color: var(--text);
}

/* ── 按钮 — 全局 style.css 接管，scoped 不再覆盖 ── */

/* ── 响应式 ── */
@media (max-width: 1200px) {
  .dashboard-workstation {
    grid-template-columns: 1fr;
  }
  .kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 768px) {
  .kpi-row {
    grid-template-columns: 1fr;
  }
  .hero-station {
    flex-direction: column;
    gap: 16px;
  }
  .workflow-steps {
    flex-direction: column;
  }
  .workflow-step-arrow {
    transform: rotate(90deg);
  }
}
</style>
