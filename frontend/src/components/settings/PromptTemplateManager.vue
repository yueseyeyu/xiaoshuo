<script setup lang="ts">
/**
 * PromptTemplateManager — 提示词模板管理面板
 * 从 SettingsView 拆分，展示缓存统计、模板列表、详情弹窗
 */
import { ref, computed, onMounted } from 'vue'
import { useUiStore } from '@/stores/ui'
import { CreativeAPI } from '@/api/creative'

const uiStore = useUiStore()

interface PromptTemplate {
  task_type: string
  description: string
  system_prompt_length: number
  system_prompt_hash: string
  system_prompt_preview: string
}
interface CacheStat {
  calls: number
  estimated_cache_hit_rate: number
}
const promptTemplates = ref<PromptTemplate[]>([])
const promptCacheStats = ref<Record<string, CacheStat>>({})
const promptSavings = ref(0)
const promptLoading = ref(false)
const showPromptModal = ref(false)
const promptDetail = ref<{
  task_type: string
  description: string
  system_prompt: string
  user_template: string
  system_prompt_hash: string
} | null>(null)
const promptDetailLoading = ref(false)

const promptOverallRate = computed(() => {
  let totalCalls = 0
  let totalHits = 0
  Object.values(promptCacheStats.value).forEach((s) => {
    totalCalls += s.calls || 0
    totalHits += Math.round((s.calls || 0) * (s.estimated_cache_hit_rate || 0))
  })
  return totalCalls > 0 ? Math.round(totalHits / totalCalls * 100) : 0
})
const promptTotalCalls = computed(() => {
  return Object.values(promptCacheStats.value).reduce((sum, s) => sum + (s.calls || 0), 0)
})

function getCacheRate(taskType: string): number {
  const stat = promptCacheStats.value[taskType]
  return stat?.estimated_cache_hit_rate ? Math.round(stat.estimated_cache_hit_rate * 100) : 0
}

function getCalls(taskType: string): number {
  return promptCacheStats.value[taskType]?.calls || 0
}

async function loadPromptTemplates() {
  promptLoading.value = true
  const [tmplRes, savingsRes] = await Promise.all([
    CreativeAPI.getPromptTemplates(),
    CreativeAPI.getCostSavings(),
  ])
  if (tmplRes.ok && tmplRes.data) {
    promptTemplates.value = tmplRes.data.templates || []
    promptCacheStats.value = tmplRes.data.cache_stats || {}
  }
  if (savingsRes.ok && savingsRes.data) {
    promptSavings.value = savingsRes.data.estimated_savings || 0
  }
  promptLoading.value = false
}

async function openPromptDetail(taskType: string) {
  showPromptModal.value = true
  promptDetailLoading.value = true
  promptDetail.value = null
  const res = await CreativeAPI.getPromptTemplateDetail(taskType)
  if (res.ok && res.data) {
    promptDetail.value = res.data
  } else {
    uiStore.showToast('加载模板详情失败', 'error')
  }
  promptDetailLoading.value = false
}

onMounted(() => {
  loadPromptTemplates()
})
</script>

<template>
  <div class="settings-card settings-card-wide">
    <div class="settings-title">
      <span class="settings-dot" style="background: var(--brand-lavender)" />
      提示词模板管理
      <span class="settings-title-hint">缓存优化可视化</span>
    </div>
    <div v-if="promptLoading" class="text-muted" style="padding:12px 0;">加载中...</div>
    <template v-else>
      <!-- 统计概览 -->
      <div class="pm-overview">
        <div class="pm-stat-card">
          <div class="pm-stat-value">{{ promptTemplates.length }}</div>
          <div class="pm-stat-label">已注册模板</div>
        </div>
        <div class="pm-stat-card">
          <div class="pm-stat-value">{{ promptOverallRate }}%</div>
          <div class="pm-stat-label">缓存命中率</div>
        </div>
        <div class="pm-stat-card">
          <div class="pm-stat-value">{{ promptTotalCalls }}</div>
          <div class="pm-stat-label">总调用次数</div>
        </div>
        <div v-if="promptSavings > 0" class="pm-stat-card highlight">
          <div class="pm-stat-value">¥{{ promptSavings.toFixed(2) }}</div>
          <div class="pm-stat-label">预估节省</div>
        </div>
      </div>
      <!-- 模板列表 -->
      <div class="pm-template-list">
        <div
          v-for="t in promptTemplates"
          :key="t.task_type"
          class="pm-template-card"
          @click="openPromptDetail(t.task_type)"
        >
          <div class="pm-template-header">
            <div class="pm-template-type">{{ t.task_type }}</div>
            <div
              class="pm-template-rate"
              :class="{ good: getCacheRate(t.task_type) >= 80, ok: getCacheRate(t.task_type) >= 50 && getCacheRate(t.task_type) < 80, bad: getCacheRate(t.task_type) < 50 }"
            >{{ getCacheRate(t.task_type) }}%</div>
          </div>
          <div class="pm-template-desc">{{ t.description || '' }}</div>
          <div class="pm-template-meta">
            <span>{{ getCalls(t.task_type) }} 次调用</span>
            <span>System Prompt: {{ t.system_prompt_length || 0 }} 字符</span>
            <span class="pm-hash">{{ t.system_prompt_hash || '' }}</span>
          </div>
          <div class="pm-template-preview">{{ t.system_prompt_preview || '' }}</div>
        </div>
      </div>
      <div v-if="promptTemplates.length === 0" class="text-muted" style="padding:12px 0;text-align:center;">
        暂无已注册的提示词模板
      </div>
    </template>
  </div>

  <!-- 提示词模板详情 Modal -->
  <div v-if="showPromptModal" class="modal-overlay" @click.self="showPromptModal = false">
    <div class="modal-box modal-lg">
      <div class="modal-header">
        <h3>提示词模板: {{ promptDetail?.task_type || '...' }}</h3>
        <button class="modal-close" @click="showPromptModal = false">×</button>
      </div>
      <div class="modal-body">
        <div v-if="promptDetailLoading" class="text-muted" style="padding:16px;">加载中...</div>
        <div v-else-if="promptDetail" class="pm-detail">
          <div class="pm-detail-section">
            <div class="pm-detail-label">任务类型</div>
            <div class="pm-detail-value">{{ promptDetail.task_type }}</div>
          </div>
          <div v-if="promptDetail.description" class="pm-detail-section">
            <div class="pm-detail-label">描述</div>
            <div class="pm-detail-value">{{ promptDetail.description }}</div>
          </div>
          <div class="pm-detail-section">
            <div class="pm-detail-label">System Prompt (固定，用于缓存命中)</div>
            <pre class="pm-detail-code">{{ promptDetail.system_prompt || '' }}</pre>
          </div>
          <div class="pm-detail-section">
            <div class="pm-detail-label">User Template (变量注入)</div>
            <pre class="pm-detail-code">{{ promptDetail.user_template || '' }}</pre>
          </div>
          <div class="pm-detail-meta">
            <div>System Prompt Hash: <code>{{ promptDetail.system_prompt_hash || '' }}</code></div>
            <div>System Prompt 长度: {{ (promptDetail.system_prompt || '').length }} 字符</div>
          </div>
        </div>
        <div v-else class="text-muted" style="padding:16px;">加载失败</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}
.settings-card-wide {
  grid-column: span 2;
}
@media (max-width: 768px) {
  .settings-card-wide { grid-column: span 1; }
}
.settings-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.settings-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.settings-title-hint {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 400;
  margin-left: auto;
}
.text-muted { color: var(--text-secondary); }

.pm-overview {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}
.pm-stat-card {
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}
.pm-stat-card.highlight {
  border-color: var(--success);
  background: rgba(34, 197, 94, 0.05);
}
.pm-stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
}
.pm-stat-card.highlight .pm-stat-value { color: var(--success); }
.pm-stat-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.pm-template-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
}
.pm-template-card {
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.pm-template-card:hover { border-color: var(--accent); }
.pm-template-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.pm-template-type {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.pm-template-rate {
  font-size: 12px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 10px;
}
.pm-template-rate.good { color: var(--success); background: rgba(34, 197, 94, 0.1); }
.pm-template-rate.ok { color: var(--warning); background: rgba(245, 158, 11, 0.1); }
.pm-template-rate.bad { color: var(--danger); background: rgba(239, 68, 68, 0.1); }
.pm-template-desc { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.pm-template-meta {
  display: flex;
  gap: 8px;
  font-size: 10px;
  color: var(--text-muted);
  flex-wrap: wrap;
}
.pm-hash { font-family: monospace; opacity: 0.7; }
.pm-template-preview {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Modal ── */
.modal-overlay {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0, 0, 0, 0.5); display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal-box {
  background: var(--bg-elevated); border-radius: 12px; border: 1px solid var(--border);
  max-width: 500px; width: 90%; max-height: 80vh; display: flex; flex-direction: column;
}
.modal-lg { max-width: 800px; }
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.modal-header h3 { font-size: 15px; font-weight: 600; }
.modal-close { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--text-muted); }
.modal-body { flex: 1; overflow-y: auto; padding: 16px 18px; }

/* ── 提示词详情 ── */
.pm-detail { display: flex; flex-direction: column; gap: 14px; }
.pm-detail-section { }
.pm-detail-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; font-weight: 600; }
.pm-detail-value { font-size: 13px; color: var(--text); }
.pm-detail-code {
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
  font-family: 'Courier New', monospace;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
  margin: 0;
}
.pm-detail-meta {
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
  padding-top: 10px;
}
.pm-detail-meta code {
  font-family: monospace;
  font-size: 10px;
  background: var(--surface-hover);
  padding: 1px 4px;
  border-radius: 3px;
}
</style>