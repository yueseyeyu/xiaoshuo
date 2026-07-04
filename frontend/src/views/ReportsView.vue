<script setup lang="ts">
/**
 * ReportsView — 报告页面 (从 prototype 全面迁移)
 *
 * 功能：
 * - 题材筛选 + 报告概览数据
 * - 6 类报告卡片（总览/质量/评分/节奏/爽点/技法）
 * - CSS 迷你条形图
 * - 创作建议引擎
 * - 技法卡片展开 + 应用到大纲
 * - 报告详情抽屉 + 导出
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { DashboardAPI, type ReportOverview } from '@/api/dashboard'
import ReportDetailDrawer from '@/components/reports/ReportDetailDrawer.vue'
import ReportCard, { type ReportCardData } from '@/components/reports/ReportCard.vue'
import { type AdviceItem } from '@/components/reports/AdviceList.vue'
import { ReportsAPI, type GuidanceItem, type TechniqueItem, type DiagnosisResult } from '@/api/reports'

const router = useRouter()
const projectStore = useProjectStore()
const uiStore = useUiStore()

// ── 类型 ──
// AdviceItem 和 ReportCardData 类型从组件导入

// ── 状态 ──
const overview = ref<ReportOverview | null>(null)
const genres = ref<string[]>([])
const selectedGenre = ref('全部')
const loading = ref(true)
const activeFilter = ref('all')
const detailOpen = ref(false)
const detailCard = ref<ReportCardData | null>(null)

// ── 指导/技法/诊断 ──
const guidanceLoading = ref(false)
const guidanceItems = ref<GuidanceItem[]>([])
const techniqueItems = ref<TechniqueItem[]>([])
const diagnosisResult = ref<DiagnosisResult | null>(null)
const diagnosisLoading = ref(false)
const activeReportTab = ref<'overview' | 'guidance' | 'techniques' | 'diagnosis'>('overview')

async function loadGuidance() {
  if (guidanceItems.value.length) return
  guidanceLoading.value = true
  const res = await ReportsAPI.getGuidance(selectedGenre.value)
  if (res.ok && res.data) guidanceItems.value = res.data.guidance || []
  guidanceLoading.value = false
}

async function loadTechniques() {
  if (techniqueItems.value.length) return
  const res = await ReportsAPI.getTechniques(selectedGenre.value)
  if (res.ok && res.data) techniqueItems.value = res.data.techniques || []
}

async function loadDiagnosis() {
  if (diagnosisResult.value) return
  diagnosisLoading.value = true
  const res = await ReportsAPI.getDiagnosis('demo', 1, selectedGenre.value)
  if (res.ok && res.data) diagnosisResult.value = res.data
  diagnosisLoading.value = false
}

// ── 标签 ──
const paceLabels: Record<string, string> = { fast: '快节奏', medium: '中节奏', slow: '慢节奏', unknown: '未知' }
const pleasureLabels: Record<string, string> = { none: '无爽点', minor: '小爽点', major: '大爽点', climax: '高潮章' }
const barColors: Record<string, string> = {
  fast: '#22C55E', medium: '#F59E0B', slow: '#EF4444',
  major: '#F97316', minor: '#FBBF24', none: '#6B7280', climax: '#DC2626',
}

const filterTabs = [
  { key: 'all', label: '全部' },
  { key: 'overview', label: '总览' },
  { key: 'quality', label: '质量' },
  { key: 'rhythm', label: '节奏' },
  { key: 'pleasure', label: '爽点' },
  { key: 'tech', label: '技法' },
]

// ── 方法 ──
function fmtNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

function resolveGenre(): string {
  if (projectStore.hasProject && projectStore.projectGenre !== '未设置') {
    return projectStore.projectGenre
  }
  return '全部'
}

// 创作建议引擎
function generateAdvice(type: string, ov: ReportOverview): AdviceItem[] {
  const genre = ov.genre || selectedGenre.value || '当前题材'
  const dist = ov.distributions ?? {}
  const stats = ov.stats ?? { books: 0, chapters: 0, words: 0 }
  const advice: AdviceItem[] = []

  switch (type) {
    case 'overview': {
      const ra = ov.rhythm_audit ?? { total_books: 0, passed: 0, warnings: 0, failed: 0 }
      if (ra.total_books > 0) {
        const passRate = Math.round((ra.passed / ra.total_books) * 100)
        if (passRate < 60) {
          advice.push({ icon: 'warning', text: `节奏审计通过率仅 ${passRate}%，建议优先研究未通过作品的节奏问题，避免同类错误` })
        } else {
          advice.push({ icon: 'check', text: `节奏审计通过率 ${passRate}%，大部分作品节奏合格，可作为可靠参考` })
        }
      }
      if (stats.books > 0) {
        const avgChapters = Math.round(stats.chapters / stats.books)
        advice.push({ icon: 'info', text: `${genre}平均每本 ${avgChapters} 章、${Math.round(stats.words / stats.books / 10000)} 万字，建议你的大纲控制在类似体量` })
      }
      break
    }
    case 'quality': {
      const qm = ov.quality_manifest ?? { approved: 0, quarantined: 0, failed: 0 }
      const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0)
      if (qmTotal > 0) {
        const qmRate = Math.round(((qm.approved || 0) / qmTotal) * 100)
        if (qmRate < 50) {
          advice.push({ icon: 'warning', text: `通过率仅 ${qmRate}%，部分拆书数据质量存疑，参考时注意交叉验证` })
        } else {
          advice.push({ icon: 'check', text: `数据质量良好（通过率 ${qmRate}%），可放心参考` })
        }
      }
      break
    }
    case 'score': {
      const sa = ov.score_audit ?? { total_books: 0, status: '', outlier_count: 0, summary: {} as Record<string, unknown> }
      if ((sa.outlier_count || 0) > 0) {
        advice.push({ icon: 'warning', text: `发现 ${sa.outlier_count} 个评分异常值，建议检查这些作品的评分标准是否偏移` })
      } else if (sa.status === 'PASS') {
        advice.push({ icon: 'check', text: '评分体系一致，各维度评分可靠' })
      }
      break
    }
    case 'rhythm': {
      const paceDist = dist.pace || {}
      const paceTotal = Object.values(paceDist).reduce((a, b) => a + b, 0)
      if (paceTotal > 0) {
        const fastPct = Math.round(((paceDist.fast || 0) / paceTotal) * 100)
        const slowPct = Math.round(((paceDist.slow || 0) / paceTotal) * 100)
        if (fastPct > 60) {
          advice.push({ icon: 'bolt', text: `${genre}快节奏占比 ${fastPct}%，建议前 3 章保持快节奏，开篇 2000 字内出现第一次冲突，避免铺垫过长` })
        } else if (slowPct > 40) {
          advice.push({ icon: 'info', text: `${genre}慢节奏占比 ${slowPct}%，但开篇仍建议加速，可将慢节奏安排在 20 章后的过渡段` })
        } else {
          advice.push({ icon: 'info', text: `${genre}节奏均衡（快${fastPct}%/慢${slowPct}%），建议"快-慢-快"波浪式推进，每 10 章一个节奏循环` })
        }
      }
      break
    }
    case 'pleasure': {
      const pleasureDist = dist.pleasure || {}
      const pleasureTotal = Object.values(pleasureDist).reduce((a, b) => a + b, 0)
      if (pleasureTotal > 0) {
        const nonePct = Math.round(((pleasureDist.none || 0) / pleasureTotal) * 100)
        const majorPct = Math.round(((pleasureDist.major || 0) / pleasureTotal) * 100)
        if (nonePct > 30) {
          advice.push({ icon: 'warning', text: `无爽点章节占比 ${nonePct}%，爆款平均每 3 章至少一个清晰爽点，连续 5 章无爽点会导致读者流失` })
        }
        if (majorPct < 10) {
          advice.push({ icon: 'bolt', text: `大爽点占比仅 ${majorPct}%，建议每卷至少安排 2-3 个大爽点（如装逼打脸、实力碾压、真相揭露）` })
        } else {
          advice.push({ icon: 'check', text: `大爽点分布合理（${majorPct}%），注意错落有致，避免爽点疲劳` })
        }
      }
      break
    }
    case 'tech': {
      const tc = ov.technique_cards || []
      if (tc.length > 0) {
        const byCat: Record<string, number> = {}
        tc.forEach((c) => { const cat = c.category || 'other'; byCat[cat] = (byCat[cat] || 0) + 1 })
        const topCat = Object.entries(byCat).sort((a, b) => b[1] - a[1])[0]
        advice.push({ icon: 'bolt', text: `${genre}高频技法分类：「${topCat[0]}」（${topCat[1]} 张），建议优先学习并应用到你的大纲中` })
        advice.push({ icon: 'info', text: '点击下方技法卡片可查看具体内容，并一键「应用到大纲」' })
      }
      break
    }
  }
  return advice
}

function buildMiniBars(data: Record<string, number>, labels: Record<string, string>): Array<{ label: string; pct: number; color: string }> {
  const total = Object.values(data).reduce((a, b) => a + b, 0)
  return Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => ({
      label: labels[k] || k,
      pct: total > 0 ? Math.round((v / total) * 100) : 0,
      color: barColors[k] || 'var(--accent)',
    }))
}

// 构建报告卡片
const reportCards = computed<ReportCardData[]>(() => {
  if (!overview.value) return []
  const ov = overview.value
  const cards: ReportCardData[] = []
  const stats = ov.stats ?? { books: 0, chapters: 0, words: 0 }
  const ra = ov.rhythm_audit ?? { total_books: 0, passed: 0, warnings: 0, failed: 0 }

  // 1. 拆书总览
  cards.push({
    type: 'overview',
    dotClass: 'green',
    title: '拆书总览',
    insight: `${stats.books || 0} 本小说 · ${fmtNumber(stats.chapters || 0)} 章 · ${fmtNumber(stats.words || 0)} 字`,
    meta: `节奏审计: ${ra.passed || 0}/${ra.total_books || 0} 通过`,
    tags: ['统计', '概览'],
    advice: generateAdvice('overview', ov),
    detail: buildOverviewDetail(ov),
  })

  // 2. 分析质量
  const qm = ov.quality_manifest ?? { approved: 0, quarantined: 0, failed: 0 }
  const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0)
  const qmPassRate = qmTotal > 0 ? Math.round(((qm.approved || 0) / qmTotal) * 100) : 0
  cards.push({
    type: 'quality',
    dotClass: qmPassRate >= 80 ? 'green' : (qmPassRate >= 50 ? 'amber' : 'red'),
    title: '分析质量概览',
    insight: `${qm.approved || 0} 本通过质量检查 · 通过率 ${qmPassRate}%`,
    meta: `${qmTotal} 本总计`,
    tags: ['质量', '概览'],
    advice: generateAdvice('quality', ov),
    detail: buildQualityDetail(ov),
  })

  // 3. 评分一致性
  const sa = ov.score_audit ?? { total_books: 0, status: '', outlier_count: 0, summary: {} as Record<string, unknown> }
  cards.push({
    type: 'score',
    dotClass: sa.status === 'PASS' ? 'green' : 'red',
    title: '评分一致性检查',
    insight: `检查状态: ${sa.status === 'PASS' ? '通过' : '异常'} · ${sa.total_books || 0} 本已评分`,
    meta: `${sa.outlier_count || 0} 个异常值`,
    tags: ['评分', '一致性'],
    advice: generateAdvice('score', ov),
    detail: buildScoreDetail(ov),
  })

  // 4. 节奏分布
  const dist = ov.distributions || {}
  const paceDist = dist.pace || {}
  const paceTotal = Object.values(paceDist).reduce((a, b) => a + b, 0)
  cards.push({
    type: 'rhythm',
    dotClass: 'purple',
    title: '节奏分布分析',
    insight: `快节奏 ${paceTotal > 0 ? Math.round(((paceDist.fast || 0) / paceTotal) * 100) : 0}% · 中节奏 ${paceTotal > 0 ? Math.round(((paceDist.medium || 0) / paceTotal) * 100) : 0}% · 慢节奏 ${paceTotal > 0 ? Math.round(((paceDist.slow || 0) / paceTotal) * 100) : 0}%`,
    meta: `${stats.chapters || 0} 章样本`,
    tags: ['节奏', '分布'],
    advice: generateAdvice('rhythm', ov),
    detail: buildDistributionDetail(ov),
    chart: buildMiniBars(paceDist, paceLabels),
  })

  // 5. 爽点分布
  const pleasureDist = dist.pleasure || {}
  const pleasureTotal = Object.values(pleasureDist).reduce((a, b) => a + b, 0)
  cards.push({
    type: 'pleasure',
    dotClass: 'amber',
    title: '爽点分布分析',
    insight: `无爽点 ${pleasureTotal > 0 ? Math.round(((pleasureDist.none || 0) / pleasureTotal) * 100) : 0}% · 小爽点 ${pleasureTotal > 0 ? Math.round(((pleasureDist.minor || 0) / pleasureTotal) * 100) : 0}% · 大爽点 ${pleasureTotal > 0 ? Math.round(((pleasureDist.major || 0) / pleasureTotal) * 100) : 0}%`,
    meta: `${pleasureTotal} 章样本`,
    tags: ['爽点', '分布'],
    advice: generateAdvice('pleasure', ov),
    detail: buildPleasureDetail(ov),
    chart: buildMiniBars(pleasureDist, pleasureLabels),
  })

  // 6. 技法卡片
  const tc = ov.technique_cards || []
  const tcByCat: Record<string, typeof tc> = {}
  tc.forEach((c) => {
    const cat = c.category || '其他'
    if (!tcByCat[cat]) tcByCat[cat] = []
    tcByCat[cat].push(c)
  })
  cards.push({
    type: 'tech',
    dotClass: 'blue',
    title: '技法卡片库',
    insight: `${tc.length} 张技法卡片 · ${Object.keys(tcByCat).length} 个分类: ${Object.keys(tcByCat).join('、')}`,
    meta: `${tc.length} 张卡片`,
    tags: ['技法', '卡片'],
    advice: generateAdvice('tech', ov),
    detail: buildTechniqueDetail(tc),
    techByCat: tcByCat,
  })

  return cards
})

const filteredCards = computed(() => {
  if (activeFilter.value === 'all') return reportCards.value
  return reportCards.value.filter((c) => c.type === activeFilter.value)
})

function buildOverviewDetail(ov: ReportOverview): string {
  const stats = ov.stats ?? { books: 0, chapters: 0, words: 0 }
  const ra = ov.rhythm_audit ?? { total_books: 0, passed: 0, warnings: 0, failed: 0 }
  const qm = ov.quality_manifest ?? { approved: 0, quarantined: 0, failed: 0 }
  const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0)
  return [
    '【拆书总量】',
    `  小说: ${stats.books || 0} 本`,
    `  章节: ${fmtNumber(stats.chapters || 0)} 章`,
    `  总字数: ${fmtNumber(stats.words || 0)} 字`,
    '',
    '【节奏审计】',
    `  总计: ${ra.total_books || 0} 本`,
    `  通过: ${ra.passed || 0} 本`,
    `  警告: ${ra.warnings || 0} 本`,
    `  失败: ${ra.failed || 0} 本`,
    '',
    '【分析质量概览】',
    `  通过: ${qm.approved || 0} / ${qmTotal} 本`,
    `  通过率: ${qmTotal > 0 ? Math.round(((qm.approved || 0) / qmTotal) * 100) : 0}%`,
  ].join('\n')
}

function buildQualityDetail(ov: ReportOverview): string {
  const qm = ov.quality_manifest ?? { approved: 0, quarantined: 0, failed: 0 }
  const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0)
  return [
    '【分析质量概览】',
    `  通过: ${qm.approved || 0} / ${qmTotal} 本`,
    `  通过率: ${qmTotal > 0 ? Math.round(((qm.approved || 0) / qmTotal) * 100) : 0}%`,
    '',
    '说明: 通过质量检查的作品数据更可靠，',
    '适合作为创作参考。未通过的作品仍保留在书库中，',
    '但不参与跨书合成分析。',
  ].join('\n')
}

function buildScoreDetail(ov: ReportOverview): string {
  const sa = ov.score_audit ?? { total_books: 0, status: '', outlier_count: 0, summary: {} as Record<string, unknown> }
  const lines = [
    '【评分一致性检查】',
    `  检查状态: ${sa.status === 'PASS' ? '通过' : '异常'}`,
    `  已评分: ${sa.total_books || 0} 本`,
    `  异常值: ${sa.outlier_count || 0} 个`,
  ]
  const summary = sa.summary || {}
  if (Object.keys(summary).length > 0) {
    lines.push('', '【摘要】')
    Object.entries(summary).forEach(([k, v]) => {
      lines.push(`  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
    })
  }
  return lines.join('\n')
}

function buildDistributionDetail(ov: ReportOverview): string {
  const dist = ov.distributions || {}
  const lines: string[] = []
  const pace = dist.pace || {}
  const paceTotal = Object.values(pace).reduce((a, b) => a + b, 0)
  lines.push(`【节奏分布】 (总计 ${paceTotal} 章)`)
  Object.entries(pace).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => {
    lines.push(`  ${k}: ${v} (${paceTotal > 0 ? ((v / paceTotal) * 100).toFixed(1) : '0.0'}%)`)
  })
  lines.push('')
  const emotion = dist.emotion || {}
  const emoTotal = Object.values(emotion).reduce((a, b) => a + b, 0)
  lines.push(`【情绪分布】 (总计 ${emoTotal} 章)`)
  Object.entries(emotion).sort((a, b) => b[1] - a[1]).slice(0, 10).forEach(([k, v]) => {
    lines.push(`  ${k}: ${v} (${emoTotal > 0 ? ((v / emoTotal) * 100).toFixed(1) : '0.0'}%)`)
  })
  return lines.join('\n')
}

function buildPleasureDetail(ov: ReportOverview): string {
  const dist = ov.distributions || {}
  const pleasure = dist.pleasure || {}
  const total = Object.values(pleasure).reduce((a, b) => a + b, 0)
  const lines = [`【爽点分布】 (总计 ${total} 章)`]
  Object.entries(pleasure).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => {
    lines.push(`  ${k}: ${v} (${total > 0 ? ((v / total) * 100).toFixed(1) : '0.0'}%)`)
  })
  lines.push('', '说明: "none" 表示本章无明确爽点，"minor" 为小爽点，', '"major" 为大爽点，"climax" 为高潮章。')
  return lines.join('\n')
}

function buildTechniqueDetail(cards: Array<{ title: string; content: string; category?: string; id?: string }>): string {
  if (!cards || cards.length === 0) return '暂无技法卡片数据'
  const byCat: Record<string, typeof cards> = {}
  cards.forEach((c) => {
    const cat = c.category || 'other'
    if (!byCat[cat]) byCat[cat] = []
    byCat[cat].push(c)
  })
  const lines: string[] = []
  Object.entries(byCat).forEach(([cat, items]) => {
    lines.push(`【${cat}】(${items.length} 张)`)
    items.forEach((c) => {
      lines.push(`  ${c.title || c.id || '?'}`)
      lines.push(`    ${c.content || ''}`)
    })
    lines.push('')
  })
  return lines.join('\n')
}

// ── 交互 ──
function openDetail(card: ReportCardData) {
  detailCard.value = card
  detailOpen.value = true
}

function closeDetail() {
  detailOpen.value = false
}

function applyTechniqueToOutline(title: string) {
  try {
    sessionStorage.setItem('pending_technique', JSON.stringify({ title, ts: Date.now() }))
  } catch (e) { /* ignore */ }
  uiStore.showToast(`技法「${title}」已准备，正在跳转到设计页...`, 'info')
  router.push({ name: 'design' })
}

function exportReport() {
  if (!detailCard.value) return
  const r = detailCard.value
  const text = `${r.title}\n\n核心洞察：\n${r.insight || ''}` +
    (r.advice.length > 0 ? '\n\n创作建议：\n' + r.advice.map((a) => `- ${a.text}`).join('\n') : '') +
    `\n\n详细分析：\n${r.detail || ''}`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `报告_${r.title}.txt`
  a.click()
  URL.revokeObjectURL(a.href)
  uiStore.showToast('报告已导出', 'success')
}

async function loadOverview() {
  loading.value = true
  const apiGenre = selectedGenre.value === '全部' ? '' : selectedGenre.value
  const res = await DashboardAPI.getReportOverview(apiGenre || undefined)
  if (res.ok && res.data) {
    overview.value = res.data
  } else {
    overview.value = null
    uiStore.showToast('报告数据加载失败', 'error')
  }
  loading.value = false
}

async function switchGenre() {
  uiStore.showToast(`正在加载 ${selectedGenre.value} 报告数据...`, 'info')
  await loadOverview()
}

async function refresh() {
  uiStore.showToast('正在刷新报告数据...', 'info')
  await loadOverview()
}

// ── 生命周期 ──
onMounted(async () => {
  selectedGenre.value = resolveGenre()
  // 加载题材列表
  const booksRes = await DashboardAPI.getBooks()
if (booksRes.ok && booksRes.data?.genres) {
    genres.value = booksRes.data.genres
  }
  await loadOverview()
})
</script>

<template>
  <div class="reports-page">
    <!-- 页头 -->
    <div class="page-header">
      <h2>报告</h2>
      <div class="header-actions">
        <select v-model="selectedGenre" class="genre-select" @change="switchGenre">
          <option value="全部">全部题材</option>
          <option v-for="g in genres" :key="g" :value="g">{{ g }}</option>
        </select>
        <button class="btn btn-secondary btn-sm" @click="refresh">刷新</button>
      </div>
    </div>

    <!-- 筛选标签 -->
    <div class="report-filters">
      <button
        v-for="tab in filterTabs"
        :key="tab.key"
        class="report-filter"
        :class="{ active: activeFilter === tab.key }"
        @click="activeFilter = tab.key"
      >{{ tab.label }}</button>
      <span class="report-count">共 {{ filteredCards.length }} 份报告</span>
    </div>

    <!-- 报告卡片网格 -->
    <div v-if="loading" class="empty-state">加载中...</div>
    <div v-else-if="!overview" class="empty-state">报告数据加载失败，请确认后端服务已启动</div>
    <div v-else class="report-grid">
      <ReportCard
        v-for="r in filteredCards"
        :key="r.type"
        :card="r"
        @open-detail="openDetail"
        @apply-technique="applyTechniqueToOutline"
      />
    </div>

    <!-- 报告子页签 -->
    <div class="report-tabs">
      <button class="tab-btn" :class="{ active: activeReportTab === 'overview' }" @click="activeReportTab = 'overview'">概览</button>
      <button class="tab-btn" :class="{ active: activeReportTab === 'guidance' }" @click="activeReportTab = 'guidance'; loadGuidance()">创作指导</button>
      <button class="tab-btn" :class="{ active: activeReportTab === 'techniques' }" @click="activeReportTab = 'techniques'; loadTechniques()">技法库</button>
      <button class="tab-btn" :class="{ active: activeReportTab === 'diagnosis' }" @click="activeReportTab = 'diagnosis'; loadDiagnosis()">深度诊断</button>
    </div>

    <!-- 创作指导 -->
    <div v-if="activeReportTab === 'guidance'" class="guidance-panel">
      <div v-if="guidanceLoading" class="text-muted">加载中...</div>
      <div v-else-if="guidanceItems.length === 0" class="text-muted">暂无创作指导</div>
      <div v-else class="guidance-list">
        <div v-for="g in guidanceItems" :key="g.title" class="guidance-card">
          <div class="guidance-header">
            <span class="guidance-category">{{ g.category }}</span>
            <span class="guidance-priority" :class="g.priority">{{ g.priority }}</span>
          </div>
          <div class="guidance-title">{{ g.title }}</div>
          <div class="guidance-content">{{ g.content }}</div>
        </div>
      </div>
    </div>

    <!-- 技法库 -->
    <div v-if="activeReportTab === 'techniques'" class="technique-panel">
      <div v-if="techniqueItems.length === 0" class="text-muted">暂无技法数据</div>
      <div v-else class="technique-grid">
        <div v-for="t in techniqueItems" :key="t.name" class="technique-card">
          <div class="technique-name">{{ t.name }}</div>
          <div class="technique-cat">{{ t.category }}</div>
          <div class="technique-desc">{{ t.description }}</div>
          <div v-if="t.example" class="technique-example">示例: {{ t.example }}</div>
        </div>
      </div>
    </div>

    <!-- 深度诊断 -->
    <div v-if="activeReportTab === 'diagnosis'" class="diagnosis-panel">
      <div v-if="diagnosisLoading" class="text-muted">诊断中...</div>
      <div v-else-if="!diagnosisResult" class="text-muted">暂无诊断结果</div>
      <div v-else-if="diagnosisResult.error" class="diagnosis-notice">
        <span class="notice-icon">&#9888;</span>
        <span>诊断功能开发中，敬请期待</span>
      </div>
      <div v-else-if="!diagnosisResult.diagnosis.length" class="text-muted">暂无诊断结果</div>
      <div v-else class="diagnosis-list">
        <div v-for="(d, i) in diagnosisResult.diagnosis" :key="i" class="diagnosis-item" :class="d.severity">
          <span class="diagnosis-cat">{{ d.category }}</span>
          <span class="diagnosis-severity">{{ d.severity }}</span>
          <span class="diagnosis-desc">{{ d.description }}</span>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <ReportDetailDrawer
      :card="detailCard"
      :open="detailOpen"
      @close="closeDetail"
      @export="exportReport"
    />
  </div>
</template>

<style scoped>
.reports-page {
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
.page-header h2 { font-size: 18px; font-weight: 600; }
.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.genre-select {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
}

.report-filters {
  display: flex;
  gap: 4px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.report-filter {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.report-filter:hover { border-color: var(--border-hover); }
.report-filter.active {
  background: var(--accent);
  color: #0a0a0a;
  border-color: var(--accent);
  font-weight: 600;
}
.report-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-secondary);
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--text-secondary);
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 16px;
}

/* ── 卡片/条形图/技法/建议/元信息样式已移至 ReportCard/MiniBarChart/TechniqueMiniList/AdviceList 组件 ── */

/* ── 报告子页签 ── */
.report-tabs { display: flex; gap: 4px; margin-bottom: 16px; }
.guidance-panel, .technique-panel, .diagnosis-panel { margin-bottom: 20px; }
.diagnosis-notice { display: flex; align-items: center; gap: 8px; padding: 16px; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.25); border-radius: 8px; font-size: 13px; color: var(--text-secondary); }
.diagnosis-notice .notice-icon { font-size: 16px; color: var(--warning); flex-shrink: 0; }
.guidance-list { display: flex; flex-direction: column; gap: 12px; }
.guidance-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.guidance-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
.guidance-category { font-size: 11px; color: var(--accent); font-weight: 600; }
.guidance-priority { font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.guidance-priority.high { background: rgba(239,68,68,0.15); color: var(--danger); }
.guidance-priority.medium { background: rgba(245,158,11,0.15); color: var(--warning); }
.guidance-priority.low { background: rgba(34,197,94,0.15); color: var(--success); }
.guidance-title { font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.guidance-content { font-size: 13px; color: var(--text-secondary); line-height: 1.5; }
.technique-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.technique-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
.technique-name { font-size: 13px; font-weight: 600; }
.technique-cat { font-size: 10px; color: var(--accent); margin-bottom: 4px; }
.technique-desc { font-size: 12px; color: var(--text-secondary); }
.technique-example { font-size: 11px; color: var(--text-muted); margin-top: 4px; font-style: italic; }
.diagnosis-list { display: flex; flex-direction: column; gap: 8px; }
.diagnosis-item { display: flex; gap: 10px; padding: 8px 12px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); font-size: 12px; align-items: center; }
.diagnosis-item.critical { border-color: var(--danger); }
.diagnosis-item.warning { border-color: var(--warning); }
.diagnosis-cat { font-weight: 600; color: var(--accent); flex-shrink: 0; }
.diagnosis-severity { font-size: 10px; padding: 1px 6px; border-radius: 6px; flex-shrink: 0; }
.diagnosis-item.critical .diagnosis-severity { background: rgba(239,68,68,0.15); color: var(--danger); }
.diagnosis-item.warning .diagnosis-severity { background: rgba(245,158,11,0.15); color: var(--warning); }
.diagnosis-desc { color: var(--text-secondary); }

/* ── 按钮 — 全局 style.css 接管 ── */

@media (max-width: 768px) {
  .report-grid { grid-template-columns: 1fr; }
}
</style>
