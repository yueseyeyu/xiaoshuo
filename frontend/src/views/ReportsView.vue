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
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { DashboardAPI, type ReportOverview } from '@/api/dashboard'
import ReportDetailDrawer from '@/components/reports/ReportDetailDrawer.vue'
import ReportCard, { type ReportCardData } from '@/components/reports/ReportCard.vue'
import { type AdviceItem } from '@/components/reports/AdviceList.vue'
import { ReportsAPI, type GuidanceItem, type TechniqueItem, type DiagnosisResult } from '@/api/reports'
import TabBar from '@/components/common/TabBar.vue'
import KpiCard from '@/components/common/KpiCard.vue'
import AppSelect from '@/components/common/AppSelect.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const projectStore = useProjectStore()
const uiStore = useUiStore()

// ── 类型 ──
// AdviceItem 和 ReportCardData 类型从组件导入

// ── 状态 ──
const overview = ref<ReportOverview | null>(null)
const genres = ref<string[]>([])
const selectedGenre = ref('全部')
const loading = ref(true)

const genreOptions = computed(() => [
  { value: '全部', label: '全部题材' },
  ...genres.value.map((g) => ({ value: g, label: g })),
])
const activeFilter = ref('all')
const detailOpen = ref(false)
const detailCard = ref<ReportCardData | null>(null)

// ── 指导/技法/诊断 ──
const guidanceLoading = ref(false)
const guidanceItems = ref<GuidanceItem[]>([])
const techniqueItems = ref<TechniqueItem[]>([])
const diagnosisResult = ref<DiagnosisResult | null>(null)
const diagnosisLoading = ref(false)
const activeReportTab = ref<'guidance' | 'techniques' | 'diagnosis'>('guidance')

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

const headerStats = computed(() => {
  if (!overview.value) return []
  const ov = overview.value
  const stats = ov.stats ?? { books: 0, chapters: 0, words: 0 }
  const ra = ov.rhythm_audit ?? { total_books: 0, passed: 0 }
  const passRate = ra.total_books > 0 ? Math.round((ra.passed / ra.total_books) * 100) : 0
  return [
    { label: '已拆书', value: stats.books || 0, suffix: '本' },
    { label: '总章节', value: fmtNumber(stats.chapters || 0), suffix: '' },
    { label: '总字数', value: fmtNumber(stats.words || 0), suffix: '' },
    { label: '节奏审计', value: passRate, suffix: '%' },
  ]
})

const filterChips = [
  { key: 'all', label: '全部' },
  { key: 'overview', label: '总览' },
  { key: 'quality', label: '质量' },
  { key: 'score', label: '评分' },
  { key: 'rhythm', label: '节奏' },
  { key: 'pleasure', label: '爽点' },
  { key: 'tech', label: '技法' },
]

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
  const paceDist = dist.pace || {}
  const total = Object.values(paceDist).reduce((a, b) => a + b, 0)
  if (total === 0) return '暂无节奏分布数据'
  const lines = ['【节奏分布】']
  Object.entries(paceDist)
    .sort((a, b) => b[1] - a[1])
    .forEach(([k, v]) => {
      lines.push(`  ${paceLabels[k] || k}: ${v} 章 (${Math.round((v / total) * 100)}%)`)
    })
  return lines.join('\n')
}

function buildPleasureDetail(ov: ReportOverview): string {
  const dist = ov.distributions || {}
  const pleasureDist = dist.pleasure || {}
  const total = Object.values(pleasureDist).reduce((a, b) => a + b, 0)
  if (total === 0) return '暂无爽点分布数据'
  const lines = ['【爽点分布】']
  Object.entries(pleasureDist)
    .sort((a, b) => b[1] - a[1])
    .forEach(([k, v]) => {
      lines.push(`  ${pleasureLabels[k] || k}: ${v} 章 (${Math.round((v / total) * 100)}%)`)
    })
  return lines.join('\n')
}

function buildTechniqueDetail(tc: Array<{ title?: string; category?: string }>): string {
  if (tc.length === 0) return '暂无技法卡片数据'
  const byCat: Record<string, number> = {}
  tc.forEach((c) => { const cat = c.category || '其他'; byCat[cat] = (byCat[cat] || 0) + 1 })
  const lines = ['【技法卡片分类统计】']
  Object.entries(byCat)
    .sort((a, b) => b[1] - a[1])
    .forEach(([cat, count]) => {
      lines.push(`  ${cat}: ${count} 张`)
    })
  lines.push('', `共计 ${tc.length} 张技法卡片`)
  return lines.join('\n')
}

function openDetail(card: ReportCardData) {
  detailCard.value = card
  detailOpen.value = true
}

function applyTechnique(name: string) {
  uiStore.showToast(`已将「${name}」加入大纲素材`, 'success')
}

function exportReport() {
  if (!overview.value) {
    uiStore.showToast('暂无报告数据可导出', 'error')
    return
  }
  const ov = overview.value
  const projectName = projectStore.currentProject?.meta?.title || '项目'
  const now = new Date().toLocaleString('zh-CN')

  let md = `# ${projectName} 数据分析报告\n\n`
  md += `> 导出时间：${now}  \n`
  md += `> 样本：${ov.stats?.books ?? 0} 本书 / ${ov.stats?.chapters ?? 0} 章 / ${ov.stats?.words?.toLocaleString() ?? 0} 字\n\n`

  md += `## 核心指标\n\n`
  headerStats.value.forEach((s: { label: string; value: string | number }) => {
    md += `- **${s.label}**：${s.value}\n`
  })
  md += '\n'

  md += `## 详细报告\n\n`
  reportCards.value.forEach((card) => {
    md += `### ${card.title}\n\n`
    md += `${card.insight}\n\n`
    if (card.tags?.length) {
      md += `**标签**：${card.tags.join(' / ')}\n\n`
    }
    if (card.advice?.length) {
      md += `**建议**：\n\n`
      card.advice.forEach((a) => {
        md += `- ${typeof a === 'string' ? a : a.text}\n`
      })
      md += '\n'
    }
    if (card.detail) {
      md += `**详情**：\n\n${card.detail}\n\n`
    }
  })

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${projectName}_报告_${new Date().toISOString().slice(0, 10)}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  uiStore.showToast('报告已导出为 Markdown', 'success')
}

async function refreshReports() {
  loading.value = true
  await loadOverview()
  loading.value = false
}

async function loadOverview() {
  const [overviewRes, booksRes] = await Promise.all([
    DashboardAPI.getReportOverview(selectedGenre.value),
    DashboardAPI.getBooks(),
  ])
  if (overviewRes.ok && overviewRes.data) {
    overview.value = overviewRes.data
  }
  if (booksRes.ok && booksRes.data) {
    genres.value = booksRes.data.genres || []
  }
}

function onGenreChange() {
  guidanceItems.value = []
  techniqueItems.value = []
  diagnosisResult.value = null
  loadOverview()
  if (activeReportTab.value === 'guidance') loadGuidance()
  else if (activeReportTab.value === 'techniques') loadTechniques()
  else if (activeReportTab.value === 'diagnosis') loadDiagnosis()
}

function onTabChange(tab: 'guidance' | 'techniques' | 'diagnosis') {
  activeReportTab.value = tab
  if (tab === 'guidance') loadGuidance()
  else if (tab === 'techniques') loadTechniques()
  else if (tab === 'diagnosis') loadDiagnosis()
}

onMounted(async () => {
  selectedGenre.value = resolveGenre()
  await loadOverview()
  loading.value = false
  await loadGuidance()
})
</script>

<template>
  <div class="reports-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-main">
        <div class="title-group">
          <h2>数据分析</h2>
          <p class="page-subtitle">基于拆书数据的创作洞察</p>
        </div>
      </div>
      <div class="header-actions">
        <AppSelect v-model="selectedGenre" :options="genreOptions" @change="onGenreChange" />
        <button class="btn btn-secondary" :disabled="loading" @click="refreshReports">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spinning: loading }">
            <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          刷新
        </button>
      </div>
    </div>

    <!-- 统计条 -->
    <div class="report-stats-strip">
      <KpiCard
        v-for="(s, i) in headerStats"
        :key="i"
        icon="M22 12h-4l-3 9L9 3l-3 9H2"
        color="accent"
        :value="s.value"
        :suffix="s.suffix"
        :label="s.label"
      />
    </div>

    <!-- 无数据状态 -->
    <EmptyState
      v-if="!loading && !overview"
      icon="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7A8.38 8.38 0 0 1 4 11.5a8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
      title="暂无报告数据"
      description="先导入书籍并运行拆书分析，报告页将展示创作洞察。"
      action-text="去拆书"
      compact
      @action="$router.push('/disassembly')"
    />

    <!-- 加载状态 -->
    <div v-if="loading" class="report-loading">
      <div class="spinner-ring"></div>
      <span>正在生成报告...</span>
    </div>

    <template v-else-if="overview">
      <!-- 工具栏 -->
      <div class="report-toolbar">
        <div class="filter-chips">
          <button
            v-for="chip in filterChips"
            :key="chip.key"
            class="filter-chip"
            :class="{ active: activeFilter === chip.key }"
            @click="activeFilter = chip.key"
          >
            {{ chip.label }}
          </button>
        </div>
        <div class="report-count">{{ filteredCards.length }} 份报告</div>
      </div>

      <!-- 报告卡片网格 -->
      <div class="report-grid">
        <ReportCard
          v-for="card in filteredCards"
          :key="card.type"
          :card="card"
          @open-detail="openDetail"
          @apply-technique="applyTechnique"
        />
      </div>

      <!-- 深度洞察 -->
      <div class="insights-section">
        <div class="insights-header">
          <div class="insights-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10H12V2z"/><path d="M12 12 2.1 9.9"/><path d="M12 12V2"/></svg>
            深度洞察
          </div>
          <TabBar
            v-model="activeReportTab"
            :options="[
              { label: '创作指导', value: 'guidance' },
              { label: '技法库', value: 'techniques' },
              { label: '章节诊断', value: 'diagnosis' },
            ]"
            @update:model-value="onTabChange"
          />
        </div>

        <div class="insights-body">
          <!-- 创作指导 -->
          <div v-if="activeReportTab === 'guidance'" class="tab-panel">
            <div v-if="guidanceLoading" class="tab-loading">正在加载创作指导...</div>
            <div v-else-if="guidanceItems.length === 0" class="tab-empty">
              暂无创作指导数据，请先拆书并生成报告。
            </div>
            <div v-else class="guidance-list">
              <div v-for="(item, idx) in guidanceItems" :key="idx" class="guidance-item">
                <div class="guidance-index">{{ idx + 1 }}</div>
                <div class="guidance-content">
                  <div class="guidance-title">{{ item.title }}</div>
                  <div class="guidance-text">{{ item.content }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 技法库 -->
          <div v-else-if="activeReportTab === 'techniques'" class="tab-panel">
            <div v-if="techniqueItems.length === 0" class="tab-empty">
              暂无技法数据，请先拆书并生成报告。
            </div>
            <div v-else class="technique-list">
              <div v-for="(item, idx) in techniqueItems.slice(0, 8)" :key="idx" class="technique-chip">
                <span class="technique-name">{{ item.name }}</span>
                <span class="technique-category">{{ item.category }}</span>
              </div>
            </div>
          </div>

          <!-- 章节诊断 -->
          <div v-else-if="activeReportTab === 'diagnosis'" class="tab-panel">
            <div v-if="diagnosisLoading" class="tab-loading">正在分析章节问题...</div>
            <div v-else-if="!diagnosisResult" class="tab-empty">
              暂无诊断数据。后端模型离线时无法生成诊断，仅展示占位结果。
            </div>
            <div v-else class="diagnosis-result">
              <div class="diagnosis-meta">
                <div class="diagnosis-meta-item">
                  <span class="meta-label">书目</span>
                  <span class="meta-value">{{ diagnosisResult.book }}</span>
                </div>
                <div class="diagnosis-meta-item">
                  <span class="meta-label">章节</span>
                  <span class="meta-value">{{ diagnosisResult.chapter }}</span>
                </div>
              </div>
              <div class="diagnosis-issues">
                <div class="diagnosis-subtitle">诊断建议</div>
                <ul>
                  <li v-for="(d, idx) in diagnosisResult.diagnosis || []" :key="idx">
                    <b>{{ d.category }}</b> · {{ d.description }}
                    <span v-if="d.suggestion">({{ d.suggestion }})</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 详情抽屉 -->
    <ReportDetailDrawer :open="detailOpen" :card="detailCard" @close="detailOpen = false" @export="exportReport" />
  </div>
</template>

<style scoped>
.reports-page {
  padding: 20px 28px;
  height: 100%;
  overflow-y: auto;
}

/* ── 页头 ── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.page-header-main { min-width: 0; }
.title-group { display: flex; flex-direction: column; gap: 2px; }
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

/* ── 统计条 ── */
.report-stats-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}

/* ── 工具栏 ── */
.report-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.filter-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-chip {
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.filter-chip:hover {
  border-color: var(--border-hover);
  color: var(--text);
}
.filter-chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--bg);
  font-weight: 500;
}
.report-count {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

/* ── 报告网格 ── */
.report-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 22px;
}

/* ── 加载状态 ── */
.report-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--text-secondary);
  font-size: 14px;
}
.spinner-ring {
  width: 36px;
  height: 36px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 深度洞察 ── */
.insights-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  overflow: hidden;
  margin-bottom: 28px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.insights-section::after {
  content: '';
  display: block;
  height: 6px;
  background: linear-gradient(90deg, var(--accent) 0%, transparent 100%);
  opacity: 0.35;
}
.insights-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-faint);
}
.insights-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.insights-title svg { color: var(--accent); }

.insights-body {
  padding: 18px;
  min-height: 220px;
}
.tab-panel {
  animation: fadeIn 0.2s ease;
  min-height: 220px;
  display: flex;
  flex-direction: column;
}
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

.tab-loading,
.tab-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex: 1;
  min-height: 220px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}
.tab-empty svg {
  width: 32px;
  height: 32px;
  opacity: 0.45;
}
.tab-empty small {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.guidance-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.guidance-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  transition: all 0.15s;
}
.guidance-item:hover {
  border-color: var(--border-hover);
  background: var(--surface-hover);
}
.guidance-index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg);
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.guidance-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 2px;
  color: var(--text);
}
.guidance-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.45;
}

.technique-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.technique-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  font-size: 12px;
  transition: all 0.15s;
}
.technique-chip:hover {
  border-color: var(--accent);
  background: var(--surface-hover);
}
.technique-category {
  font-size: 10px;
  font-weight: 500;
  color: var(--text-muted);
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-faint);
}

.diagnosis-result {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 16px;
  align-items: flex-start;
}
.diagnosis-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  min-width: 120px;
}
.diagnosis-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.meta-label {
  font-size: 11px;
  color: var(--text-muted);
}
.meta-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.diagnosis-subtitle {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text);
}
.diagnosis-issues ul {
  margin: 0;
  padding-left: 16px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.diagnosis-issues li { margin-bottom: 4px; }
.diagnosis-issues li b { color: var(--text); }

/* ── 刷新按钮动画 ── */
.spinning { animation: spin 1s linear infinite; }

/* ── 响应式 ── */
@media (max-width: 1200px) {
  .report-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 900px) {
  .report-stats-strip { grid-template-columns: repeat(2, 1fr); }
  .report-grid { grid-template-columns: 1fr; }
  .insights-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .diagnosis-result { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .reports-page { padding: 14px 16px; }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .header-actions { width: 100%; }
  .report-stats-strip { grid-template-columns: repeat(2, 1fr); }
  .report-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
