<script setup lang="ts">
/**
 * LogsView — 日志页面 (从 prototype 迁移)
 *
 * 功能：
 * - 筛选：类别(访问/操作)、日期、级别、搜索
 * - 统计：总记录数、查询耗时
 * - 表格：时间/方法/路径/状态/耗时/详情
 * - 分页：上一页/下一页
 * - 详情弹窗：完整日志信息
 */
import { ref, computed, onMounted } from 'vue'
import { LogsAPI } from '@/api/logs'

interface LogEntry {
  timestamp?: string
  method?: string
  path?: string
  action?: string
  status?: number
  duration_ms?: number
  client_ip?: string
  params?: Record<string, unknown>
  req_body?: unknown
  detail?: Record<string, unknown>
}

const PAGE_SIZE = 50

// ── 状态 ──
const category = ref('access')
const dateFilter = ref('')
const levelFilter = ref('')
const searchQuery = ref('')
const currentPage = ref(0)
const totalCount = ref(0)
const queryTime = ref(0)
const entries = ref<LogEntry[]>([])
const loading = ref(false)
const dates = ref<string[]>([])

// 详情弹窗
const detailOpen = ref(false)
const detailEntry = ref<LogEntry | null>(null)

// ── 计算属性 ──
const totalPages = computed(() => Math.ceil(totalCount.value / PAGE_SIZE))

// ── 方法 ──
async function loadDates() {
  const res = await LogsAPI.getDates()
  if (res.ok && res.data) {
    dates.value = res.data[category.value] || []
  }
}

async function refreshLogs() {
  loading.value = true
  const params = new URLSearchParams({
    category: category.value,
    offset: String(currentPage.value * PAGE_SIZE),
    limit: String(PAGE_SIZE),
  })
  if (dateFilter.value) params.set('date', dateFilter.value)
  if (levelFilter.value) params.set('level', levelFilter.value)
  if (searchQuery.value.trim()) params.set('search', searchQuery.value.trim())

  const t0 = performance.now()
  const res = await LogsAPI.getLogs(params)
  queryTime.value = Math.round(performance.now() - t0)

  if (res.ok && res.data) {
    entries.value = res.data.entries || []
    totalCount.value = res.data.total || 0
  } else {
    entries.value = []
    totalCount.value = 0
  }
  loading.value = false
}

function onCategoryChange() {
  currentPage.value = 0
  dateFilter.value = ''
  loadDates()
  refreshLogs()
}

function onFilterChange() {
  currentPage.value = 0
  refreshLogs()
}

function prevPage() {
  if (currentPage.value > 0) {
    currentPage.value--
    refreshLogs()
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value - 1) {
    currentPage.value++
    refreshLogs()
  }
}

function openDetail(entry: LogEntry) {
  detailEntry.value = entry
  detailOpen.value = true
}

function statusClass(status?: number) {
  if (!status) return ''
  if (status >= 400) return 'status-err'
  if (status >= 300) return 'status-warn'
  return 'status-ok'
}

function methodClass(method?: string) {
  return method === 'POST' ? 'method-post' : 'method-get'
}

function formatJson(obj: unknown): string {
  try { return JSON.stringify(obj, null, 2) } catch { return String(obj) }
}

// ── 生命周期 ──
onMounted(() => {
  loadDates()
  refreshLogs()
})
</script>

<template>
  <div class="logs-page">
    <div class="page-header">
      <h2>日志</h2>
      <button class="btn btn-secondary btn-sm" @click="refreshLogs">刷新</button>
    </div>

    <!-- 筛选 -->
    <div class="logs-toolbar">
      <div class="filter-group">
        <select v-model="category" class="logs-select" @change="onCategoryChange">
          <option value="access">API 访问日志</option>
          <option value="operation">用户操作日志</option>
        </select>
        <select v-model="dateFilter" class="logs-select" @change="onFilterChange">
          <option value="">全部日期</option>
          <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="levelFilter" class="logs-select" @change="onFilterChange">
          <option value="">全部级别</option>
          <option value="ERROR">ERROR (4xx/5xx)</option>
          <option value="WARNING">WARNING (3xx)</option>
        </select>
      </div>
      <div class="search-group">
        <input
          v-model="searchQuery"
          type="text"
          class="logs-search"
          placeholder="搜索日志内容..."
          @keydown.enter="onFilterChange"
        />
        <button class="btn btn-primary btn-sm" @click="onFilterChange">搜索</button>
      </div>
    </div>

    <!-- 统计 -->
    <div class="logs-stats">
      <span>共<b>{{ totalCount }}</b> 条记录</span>
      <span class="divider">|</span>
      <span>耗时: <b>{{ queryTime }}</b>ms</span>
    </div>

    <!-- 表格 -->
    <div class="logs-table-wrap">
      <table class="logs-table">
        <thead>
          <tr>
            <th class="th-time">时间</th>
            <th class="th-method">方法</th>
            <th class="th-path">路径</th>
            <th class="th-status">状态</th>
            <th class="th-duration">耗时</th>
            <th class="th-detail">详情</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" class="logs-empty">加载中...</td></tr>
          <tr v-else-if="entries.length === 0"><td colspan="6" class="logs-empty">暂无日志记录</td></tr>
          <tr v-for="(e, i) in entries" :key="i">
            <td>{{ e.timestamp || '' }}</td>
            <td>
              <span class="method-badge" :class="methodClass(e.method)">
                {{ category === 'access' ? (e.method || '') : 'OP' }}
              </span>
            </td>
            <td class="td-path">{{ e.path || e.action || '' }}</td>
            <td :class="statusClass(e.status)">{{ e.status || (category === 'operation' ? '-' : 200) }}</td>
            <td>{{ e.duration_ms != null ? e.duration_ms + 'ms' : '-' }}</td>
            <td><button class="detail-btn" @click="openDetail(e)">详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div class="logs-pagination">
      <button class="btn btn-secondary btn-sm" :disabled="currentPage <= 0" @click="prevPage">上一页</button>
      <span>第 {{ currentPage + 1 }} / {{ Math.max(1, totalPages) }} 页</span>
      <button class="btn btn-secondary btn-sm" :disabled="currentPage >= totalPages - 1" @click="nextPage">下一页</button>
    </div>

    <!-- 详情弹窗 -->
    <Teleport to="body">
      <div v-if="detailOpen" class="log-detail-overlay" @click.self="detailOpen = false">
        <div class="log-detail-modal">
          <div class="log-detail-header">
            <h3>日志详情 — {{ detailEntry?.timestamp || '' }}</h3>
            <button class="icon-btn" @click="detailOpen = false">×</button>
          </div>
          <div class="log-detail-body">
            <div class="detail-section">
              <h4>基本信息</h4>
              <div class="detail-row"><span class="label">时间</span><span class="value">{{ detailEntry?.timestamp || '-' }}</span></div>
              <div class="detail-row"><span class="label">客户端</span><span class="value">{{ detailEntry?.client_ip || '-' }}</span></div>
              <div class="detail-row"><span class="label">方法</span><span class="value">{{ detailEntry?.method || '-' }}</span></div>
              <div class="detail-row"><span class="label">路径</span><span class="value">{{ detailEntry?.path || detailEntry?.action || '-' }}</span></div>
              <div class="detail-row"><span class="label">状态</span><span class="value">{{ detailEntry?.status != null ? detailEntry.status : '-' }}</span></div>
              <div class="detail-row"><span class="label">耗时</span><span class="value">{{ detailEntry?.duration_ms != null ? detailEntry.duration_ms + 'ms' : '-' }}</span></div>
            </div>
            <div v-if="detailEntry?.params && Object.keys(detailEntry.params).length > 0" class="detail-section">
              <h4>请求参数</h4>
              <pre class="detail-json">{{ formatJson(detailEntry.params) }}</pre>
            </div>
            <div v-if="detailEntry?.req_body" class="detail-section">
              <h4>请求体</h4>
              <pre class="detail-json">{{ formatJson(detailEntry.req_body) }}</pre>
            </div>
            <div v-if="detailEntry?.detail && Object.keys(detailEntry.detail).length > 0" class="detail-section">
              <h4>操作详情</h4>
              <pre class="detail-json">{{ formatJson(detailEntry.detail) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.logs-page { padding: 16px 24px; height: 100%; overflow-y: auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { font-size: 18px; font-weight: 600; }

.logs-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.filter-group { display: flex; gap: 8px; }
.search-group { display: flex; gap: 6px; }
.logs-select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font-size: 13px; }
.logs-search { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font-size: 13px; width: 200px; }

.logs-stats { font-size: 12px; color: var(--text-secondary); margin-bottom: 12px; }
.logs-stats b { color: var(--text); font-weight: 600; }
.divider { margin: 0 8px; opacity: 0.5; }

.logs-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }
.logs-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.logs-table th { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--text-secondary); font-weight: 500; white-space: nowrap; }
.logs-table td { padding: 6px 12px; border-bottom: 1px solid var(--border); }
.logs-table tr:hover td { background: var(--surface-hover); }
.logs-empty { text-align: center; color: var(--text-secondary); padding: 24px; }
.td-path { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.method-badge { font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
.method-get { background: rgba(56, 189, 248, 0.1); color: var(--accent); }
.method-post { background: rgba(34, 197, 94, 0.1); color: var(--success); }

.status-ok { color: var(--success); }
.status-warn { color: var(--warning); }
.status-err { color: var(--danger); font-weight: 600; }

.detail-btn { background: none; border: 1px solid var(--border); border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; color: var(--text-secondary); }
.detail-btn:hover { border-color: var(--accent); color: var(--accent); }

.logs-pagination { display: flex; align-items: center; gap: 12px; justify-content: center; margin-top: 16px; font-size: 12px; color: var(--text-secondary); }

/* 详情弹窗 */
.log-detail-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.log-detail-modal { background: var(--surface-solid); border: 1px solid var(--border); border-radius: 12px; width: 90%; max-width: 700px; max-height: 80vh; display: flex; flex-direction: column; }
.log-detail-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.log-detail-header h3 { font-size: 15px; font-weight: 600; }
.icon-btn { background: none; border: none; font-size: 20px; color: var(--text-secondary); cursor: pointer; }
.log-detail-body { padding: 16px; overflow-y: auto; flex: 1; }
.detail-section { margin-bottom: 16px; }
.detail-section h4 { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--accent); }
.detail-row { display: flex; gap: 12px; padding: 3px 0; font-size: 13px; }
.detail-row .label { width: 80px; color: var(--text-secondary); flex-shrink: 0; }
.detail-row .value { word-break: break-all; }
.detail-json { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 10px; font-size: 12px; font-family: 'Consolas', monospace; overflow-x: auto; margin: 0; }

/* ── 按钮 — 全局 style.css 接管 ── */
</style>
