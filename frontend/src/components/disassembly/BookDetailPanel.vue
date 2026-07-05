<script setup lang="ts">
/**
 * BookDetailPanel — 拆书详情面板
 *
 * 从 DisassemblyView 提取，包含八步法导航、章节拆解表、分布图和多书对比。
 */
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUiStore } from '@/stores/ui'
import type { DisassemblyBook } from '@/api/disassembly'

const router = useRouter()
const uiStore = useUiStore()

const props = defineProps<{
  detailData: DisassemblyBook | null
  selectedStem: string | null
  loading: boolean
  compareBooks: Array<{ name: string; title: string; data?: DisassemblyBook }>
  compareMode: boolean
}>()

const emit = defineEmits<{
  applyToDesign: []
}>()

const activeStep = ref(1)

// ── 八步法定义 ──
const steps = [
  { num: 1, name: '拆主线', desc: '一句话概括核心事件链', icon: 'M3 3v18h18 M7 16l4-4 3 3 5-6' },
  { num: 2, name: '拆人设', desc: '主角性格、背景、成长弧光', icon: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z' },
  { num: 3, name: '拆爽点', desc: '爽点类型、频率、投放节奏', icon: 'M13 2L3 14h9l-1 8 10-12h-9l1-8z' },
  { num: 4, name: '拆节奏', desc: '快慢交替、冲突分布、高潮位置', icon: 'M22 12h-4l-3 9L9 3l-3 9H2' },
  { num: 5, name: '拆悬念', desc: '伏笔埋设、悬念回收、章末钩子', icon: 'M11 17.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z M11 17.5V22 M21 21l-4.35-4.35' },
  { num: 6, name: '拆对话', desc: '对话风格、信息密度、推动力', icon: 'M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z' },
  { num: 7, name: '拆场景', desc: '场景构建、环境渲染、氛围控制', icon: 'M9 20l-5.447-2.724A1 1 0 0 1 3 16.382V5.618a1 1 0 0 1 1.447-.894L9 7 M9 20l6-3 M9 20V7 M15 17l5.553-2.776A1 1 0 0 0 21 13.382V2.618a1 1 0 0 0-1.447-.894L15 4 M15 17V4 M9 7l6-3' },
  { num: 8, name: '拆伏笔', desc: '伏笔回收率、跨章伏笔、暗线', icon: 'M19 11H5a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2z M7 11V7a5 5 0 0 1 10 0v4' },
]

const paceColors: Record<string, string> = { fast: '#ef4444', medium: '#f59e0b', slow: '#38bdf8' }
const distColors = ['#38bdf8', '#f59e0b', '#22c55e', '#ef4444', '#a78bfa', '#f97316', '#14b8a6', '#ec4899']

const paceLabels: Record<string, string> = { fast: '快节奏', medium: '中节奏', slow: '慢节奏' }
const emotionLabels: Record<string, string> = {
  tense: '紧张', relaxed: '舒缓', rising: '上升', falling: '下降', calm: '平静',
  excited: '兴奋', sad: '悲伤', angry: '愤怒', fearful: '恐惧', happy: '愉悦',
  neutral: '中性', mixed: '复杂',
}
const pleasureLabels: Record<string, string> = { none: '无', minor: '小爽点', major: '大爽点', climax: '高潮' }
const conflictLabels: Record<string, string> = {
  man_vs_man: '人与人', man_vs_society: '人与社会', man_vs_nature: '人与自然',
  man_vs_self: '人与自我', man_vs_fate: '人与命运', man_vs_machine: '人与机器',
  internal: '内心冲突', external: '外部冲突',
}
function fmtLabel(map: Record<string, string>, key?: string): string {
  if (!key) return '-'
  return map[key] || key
}

function fmtNumber(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}

function applyToDesign() {
  if (!props.detailData || !props.selectedStem) return
  const summary = props.detailData.summary || {}
  const paceDist = summary.pace_dist || {}
  const totalPace = Object.values(paceDist).reduce((a, b) => a + b, 0)
  const fastRatio = totalPace > 0 ? Math.round((paceDist.fast || 0) / totalPace * 100) : 0
  const slowRatio = totalPace > 0 ? Math.round((paceDist.slow || 0) / totalPace * 100) : 0
  const advice = fastRatio > 50
    ? `该书节奏偏快（快节奏${fastRatio}%），建议大纲保持高频冲突和爽点投放，每2-3章一个小高潮。`
    : slowRatio > 40
      ? `该书偏慢热（慢节奏${slowRatio}%），前期重视铺垫和人设，第5章后开始加速爆发。`
      : `该书节奏均衡（快${fastRatio}%/慢${slowRatio}%），快慢交替张弛有度。`

  try {
    sessionStorage.setItem('disassembly_to_design', JSON.stringify({ advice, book: props.selectedStem }))
  } catch (e) { /* ignore */ }
  uiStore.showToast('正在将节奏模板应用到设计页...', 'info')
  router.push({ name: 'design' })
}

// 分布图数据
const distributions = computed(() => {
  if (!props.detailData?.summary) return []
  const s = props.detailData.summary
  return [
    { title: '情绪分布', data: s.emotion_dist },
    { title: '节奏分布', data: s.pace_dist },
    { title: '冲突分布', data: s.conflict_dist },
    { title: '爽点分布', data: s.pleasure_dist },
  ].filter(d => d.data && Object.keys(d.data).length > 0)
})
</script>

<template>
  <!-- 空状态 -->
  <div v-if="!selectedStem && !compareMode" class="dis-empty">
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.3;margin-bottom:12px;">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.08-3.08a6 6 0 0 1-7.06 7.06l-6.36 6.36a2.5 2.5 0 1 1-3.54-3.54l6.36-6.36a6 6 0 0 1 7.06-7.06l-2.08 2.08z" />
    </svg>
    <div style="font-size:14px;color:var(--text-secondary);">从左侧选择一本书查看拆书详情</div>
  </div>

  <!-- 加载中 -->
  <div v-else-if="loading" class="dis-loading">
    <div class="spinner" />
    <span>加载中...</span>
  </div>

  <!-- 待拆书 -->
  <div v-else-if="selectedStem && !detailData && !compareMode" class="dis-pending">
    <div style="font-size:15px;font-weight:600;margin-bottom:6px;">{{ selectedStem }}</div>
    <div style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">该书尚未进行拆书分析</div>
    <button class="btn btn-primary btn-sm" @click="router.push({ name: 'library' })">前往书库开始分析</button>
  </div>

  <!-- 详情内容 -->
  <template v-else-if="detailData && !compareMode">
    <!-- 详情头部 -->
    <div class="dis-detail-header">
      <div class="dis-detail-header-info">
        <h3>{{ selectedStem }}</h3>
        <div class="dis-detail-meta-row">
          <span class="dis-meta-chip"><b>题材</b> {{ detailData.genre || '末世' }}</span>
          <span class="dis-meta-chip"><b>章节</b> {{ detailData.summary?.chapters || detailData.total || 0 }}</span>
          <span class="dis-meta-chip"><b>字数</b> {{ fmtNumber(detailData.summary?.total_words || 0) }}</span>
          <span class="dis-meta-chip"><b>均章</b> {{ fmtNumber((detailData.summary?.chapters || 0) > 0 ? Math.round((detailData.summary?.total_words || 0) / (detailData.summary?.chapters || 1)) : 0) }}</span>
        </div>
      </div>
      <button class="btn btn-primary btn-sm" @click="applyToDesign">应用到设计页 →</button>
    </div>

    <div class="dis-detail-body">
      <!-- 八步法导航 -->
      <div class="dis-eight-step">
        <div class="dis-eight-step-title">拆书八步法 <span class="dis-eight-step-hint">从宏观到微观逐层解剖</span></div>
        <div class="dis-nav-row">
          <button
            v-for="s in steps"
            :key="s.num"
            class="dis-nav-btn"
            :class="{ active: activeStep === s.num }"
            @click="activeStep = s.num"
          >
            <svg class="dis-nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path :d="s.icon" /></svg>
            <span class="dis-nav-name">{{ s.name }}</span>
          </button>
        </div>
        <div class="dis-step-content">
          <div class="dis-step-detail">
            <div class="dis-step-detail-header">
              <span class="dis-step-detail-num">步{{ activeStep }}</span>
              <div>
                <div class="dis-step-detail-name">{{ steps[activeStep - 1].name }}</div>
                <div class="dis-step-detail-desc">{{ steps[activeStep - 1].desc }}</div>
              </div>
            </div>
            <div class="dis-step-detail-body">
              <template v-if="activeStep === 1">
                <div class="dis-step-table">
                  <div class="dis-step-row"><span class="dis-step-label">题材</span><span>{{ detailData.genre || '未标注' }}</span></div>
                  <div v-if="detailData.summary?.conflict_dist" class="dis-step-row">
                    <span class="dis-step-label">核心冲突</span>
                    <span>{{ fmtLabel(conflictLabels, Object.entries(detailData.summary.conflict_dist).sort((a, b) => b[1] - a[1])[0]?.[0]) || '-' }}</span>
                  </div>
                  <div v-if="detailData.summary?.pleasure_dist" class="dis-step-row">
                    <span class="dis-step-label">主爽点</span>
                    <span>{{ Object.keys(detailData.summary.pleasure_dist).filter(k => k !== 'none').map(k => fmtLabel(pleasureLabels, k)).join(' / ') || '-' }}</span>
                  </div>
                  <div v-if="detailData.summary?.emotion_dist" class="dis-step-row">
                    <span class="dis-step-label">情绪基调</span>
                    <span>{{ fmtLabel(emotionLabels, Object.entries(detailData.summary.emotion_dist).sort((a, b) => b[1] - a[1])[0]?.[0]) || '-' }}</span>
                  </div>
                </div>
              </template>
              <template v-else-if="activeStep === 4">
                <div v-if="detailData.chapters?.length" class="rhythm-viz-container">
                  <div
                    v-for="(c, i) in detailData.chapters.slice(0, 30)"
                    :key="i"
                    class="rhythm-bar"
                    :style="{ background: paceColors[c.pace || ''] || '#cbd5e1' }"
                    :title="`第${c.ch || i+1}章 · ${c.wc || 0}字 · 节奏:${fmtLabel(paceLabels, c.pace)} · 情绪:${fmtLabel(emotionLabels, c.emotion)}`"
                  />
                </div>
                <div class="rhythm-legend">
                  <span><span class="rhythm-dot" style="background:#ef4444" />快节奏</span>
                  <span><span class="rhythm-dot" style="background:#f59e0b" />中节奏</span>
                  <span><span class="rhythm-dot" style="background:#38bdf8" />慢节奏</span>
                </div>
              </template>
              <template v-else>
                <div class="dis-step-table">
                  <div v-if="detailData.summary" class="dis-step-row">
                    <span class="dis-step-label">总章节</span>
                    <span>{{ detailData.summary.chapters || detailData.total || 0 }}</span>
                  </div>
                  <div v-if="detailData.chapters?.length" class="dis-step-row">
                    <span class="dis-step-label">含冲突章节</span>
                    <span>{{ detailData.chapters.filter(c => c.conflict).length }} / {{ detailData.chapters.length }}</span>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 章节拆解表 -->
      <div v-if="detailData.chapters?.length" class="dis-detail-section">
        <div class="ch-table-header"><b>章节拆解表</b><span class="ch-table-hint">展示前 {{ Math.min(detailData.chapters.length, 15) }} 章</span></div>
        <div class="ch-table-wrap">
          <table class="ch-table">
            <thead><tr><th>章节</th><th>节奏</th><th>情绪</th><th>冲突</th><th>爽点</th><th>字数</th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in detailData.chapters.slice(0, 15)" :key="i">
                <td class="ch-col-num">第{{ c.ch || i + 1 }}章</td>
                <td class="ch-col-pace"><span class="pace-dot" :style="{ background: paceColors[c.pace || ''] || '#cbd5e1' }" />{{ fmtLabel(paceLabels, c.pace) }}</td>
                <td class="ch-col-emotion">{{ fmtLabel(emotionLabels, c.emotion) }}</td>
                <td class="ch-col-conflict">
                  <span v-if="c.conflict" class="ch-tag ch-tag-conflict">冲突</span>
                  <span v-else class="ch-tag ch-tag-muted">-</span>
                </td>
                <td class="ch-col-pleasure">
                  <span v-if="c.pleasure_type && c.pleasure_type !== 'none'" class="ch-tag ch-tag-pleasure">{{ fmtLabel(pleasureLabels, c.pleasure_type) }}</span>
                  <span v-else class="ch-tag ch-tag-muted">-</span>
                </td>
                <td class="ch-col-wc">{{ fmtNumber(c.wc || 0) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 分布图 -->
      <div v-for="(dist, idx) in distributions" :key="idx" class="dis-detail-section">
        <b>{{ dist.title }}</b>
        <div class="dis-detail-bars">
          <div v-for="([k, v], i) in Object.entries(dist.data!).sort((a, b) => b[1] - a[1])" :key="k" class="dis-detail-bar">
            <div class="dis-detail-bar-label">
              <span>{{
                dist.title === '节奏分布' ? fmtLabel(paceLabels, k)
                : dist.title === '情绪分布' ? fmtLabel(emotionLabels, k)
                : dist.title === '爽点分布' ? fmtLabel(pleasureLabels, k)
                : dist.title === '冲突分布' ? fmtLabel(conflictLabels, k)
                : k
              }}</span>
              <span>{{ ((v / Object.values(dist.data!).reduce((a, b) => a + b, 0)) * 100).toFixed(1) }}% ({{ v }})</span>
            </div>
            <div class="dis-detail-bar-track">
              <div class="dis-detail-bar-fill" :style="{ width: (v / Object.values(dist.data!).reduce((a, b) => a + b, 0) * 100) + '%', background: distColors[i % distColors.length] }" />
            </div>
          </div>
        </div>
      </div>
    </div>
  </template>

  <!-- 对比结果 -->
  <template v-else-if="compareMode && compareBooks.length >= 2">
    <div class="dis-detail-header">
      <div class="dis-detail-header-info">
        <h3>多书对比</h3>
        <div class="dis-detail-meta-row">
          <span v-for="b in compareBooks" :key="b.name" class="dis-meta-chip">{{ b.title }}</span>
        </div>
      </div>
    </div>
    <div class="dis-detail-body">
      <div class="dis-detail-section">
        <b>节奏分布对比</b>
        <div class="compare-rows">
          <div v-for="b in compareBooks" :key="b.name" class="compare-row">
            <div class="compare-row-label">{{ b.title }}</div>
            <div class="compare-bar-stack">
              <div
                v-for="[pace, color] in [['fast', '#ef4444'], ['medium', '#f59e0b'], ['slow', '#38bdf8']]"
                :key="pace"
                class="compare-bar-seg"
                :style="{
                  width: (Object.values(b.data?.summary?.pace_dist || {}).reduce((a, c) => a + c, 0) > 0
                    ? ((b.data?.summary?.pace_dist?.[pace] || 0) / Object.values(b.data?.summary?.pace_dist || {}).reduce((a, c) => a + c, 0) * 100)
                    : 0) + '%',
                  background: color
                }"
              />
            </div>
          </div>
        </div>
      </div>
      <div class="dis-detail-section">
        <b>基础数据对比</b>
        <div class="compare-meta-grid">
          <div v-for="b in compareBooks" :key="b.name" class="compare-meta-col">
            <div class="compare-meta-title">{{ b.title }}</div>
            <div class="compare-meta-item"><span>题材</span><b>{{ b.data?.genre || '-' }}</b></div>
            <div class="compare-meta-item"><span>章节</span><b>{{ b.data?.summary?.chapters || 0 }}</b></div>
            <div class="compare-meta-item"><span>总字数</span><b>{{ fmtNumber(b.data?.summary?.total_words || 0) }}</b></div>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.dis-empty, .dis-loading, .dis-pending { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 400px; }
.spinner { width: 24px; height: 24px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }

.dis-detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding: 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
.dis-detail-header h3 { font-size: 16px; font-weight: 600; }
.dis-detail-meta-row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.dis-meta-chip { font-size: 12px; padding: 2px 8px; border-radius: 4px; background: var(--surface-hover); color: var(--text-secondary); }
.dis-meta-chip b { color: var(--text); margin-right: 2px; }

.dis-detail-body { display: flex; flex-direction: column; gap: 16px; }
.dis-detail-section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.dis-detail-section b { font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px; }

/* 八步法 */
.dis-eight-step { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.dis-eight-step-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.dis-eight-step-hint { font-size: 12px; color: var(--text-secondary); font-weight: 400; }
.dis-nav-row { display: flex; gap: 4px; margin: 12px 0; flex-wrap: wrap; }
.dis-nav-btn { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: transparent; cursor: pointer; transition: all 0.15s; min-width: 70px; }
.dis-nav-btn:hover { border-color: var(--border-hover); }
.dis-nav-btn.active { border-color: var(--accent); background: rgba(56, 189, 248, 0.08); }
.dis-nav-icon { flex-shrink: 0; color: var(--text-secondary); }
.dis-nav-name { font-size: 11px; color: var(--text-secondary); }
.dis-nav-btn.active .dis-nav-name { color: var(--accent); }

.dis-step-detail { padding: 12px; background: var(--surface-solid); border-radius: 8px; border: 1px solid var(--border); }
.dis-step-detail-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.dis-step-detail-num { background: var(--accent); color: var(--bg); font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.dis-step-detail-name { font-size: 14px; font-weight: 600; }
.dis-step-detail-desc { font-size: 12px; color: var(--text-secondary); }

.dis-step-table { display: flex; flex-direction: column; gap: 6px; }
.dis-step-row { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid var(--border); }
.dis-step-row:last-child { border-bottom: none; }
.dis-step-label { color: var(--text-secondary); }

/* 章节表 */
.ch-table-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.ch-table-hint { font-size: 11px; color: var(--text-secondary); }
.ch-table-wrap { overflow-x: auto; }
.ch-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ch-table th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text-secondary); font-weight: 500; }
.ch-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.ch-col-pace { display: flex; align-items: center; gap: 4px; }
.pace-dot { width: 8px; height: 8px; border-radius: 50%; }
.ch-tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; }
.ch-tag-conflict { color: var(--danger); background: rgba(239, 68, 68, 0.1); }
.ch-tag-pleasure { color: var(--amber); background: rgba(245, 158, 11, 0.1); }
.ch-tag-muted { color: var(--text-muted); }

/* 分布条形图 */
.dis-detail-bars { display: flex; flex-direction: column; gap: 6px; }
.dis-detail-bar { display: flex; flex-direction: column; gap: 2px; }
.dis-detail-bar-label { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); }
.dis-detail-bar-track { height: 6px; background: var(--surface-solid); border-radius: 3px; overflow: hidden; }
.dis-detail-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s ease; }

/* 节奏可视化 */
.rhythm-viz-container { display: flex; gap: 1px; height: 32px; margin: 8px 0; }
.rhythm-bar { flex: 1; min-width: 2px; border-radius: 2px 2px 0 0; cursor: pointer; transition: opacity 0.15s; }
.rhythm-bar:hover { opacity: 0.8; }
.rhythm-legend { display: flex; gap: 12px; font-size: 11px; color: var(--text-secondary); }
.rhythm-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }

/* 对比结果 */
.compare-rows { display: flex; flex-direction: column; gap: 8px; }
.compare-row { display: flex; align-items: center; gap: 8px; }
.compare-row-label { width: 120px; font-size: 12px; flex-shrink: 0; }
.compare-bar-stack { flex: 1; height: 16px; border-radius: 8px; overflow: hidden; display: flex; background: var(--surface-solid); }
.compare-bar-seg { height: 100%; transition: width 0.3s ease; }
.compare-meta-grid { display: flex; gap: 16px; }
.compare-meta-col { flex: 1; }
.compare-meta-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.compare-meta-item { display: flex; justify-content: space-between; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
.compare-meta-item span { color: var(--text-secondary); }

/* ── 按钮 — 全局 style.css 接管 ── */
</style>
