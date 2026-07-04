<script setup lang="ts">
/**
 * DeconstructModal — 小说解构结果模态框
 *
 * 从 DisassemblyView 提取，封装五段式解构结果的展示逻辑。
 */
import { ref } from 'vue'
import { useUiStore } from '@/stores/ui'
import { CreativeAPI } from '@/api/creative'

const uiStore = useUiStore()

const show = defineModel<boolean>('show', { required: true })
const title = ref('')
const loading = ref(false)

interface DeconstructData {
  genre_tags?: Record<string, unknown>
  structure?: Record<string, unknown>
  characters?: Record<string, unknown>
  borrowable?: Record<string, unknown>
  warnings?: Record<string, unknown>
}

const data = ref<DeconstructData | null>(null)

async function open(book: { title: string; file_path: string }) {
  title.value = book.title
  show.value = true
  loading.value = true
  data.value = null
  const res = await CreativeAPI.runDeconstruction({ file_path: book.file_path })
  if (res.ok && res.data) {
    data.value = res.data as DeconstructData
  } else {
    uiStore.showToast('解构失败: ' + (res.error || ''), 'error')
  }
  loading.value = false
}

function renderTagValue(val: unknown): string {
  if (!val) return ''
  if (Array.isArray(val)) return val.join('、')
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

function asArray(val: unknown): unknown[] {
  return Array.isArray(val) ? val : []
}

function renderListItem(item: unknown): string {
  if (typeof item === 'string') return item
  return JSON.stringify(item)
}

function renderWarningItem(item: unknown): string {
  if (typeof item === 'string') return item
  if (item && typeof item === 'object') {
    const obj = item as Record<string, unknown>
    return String(obj.point || obj.reason || obj.risk || JSON.stringify(item))
  }
  return JSON.stringify(item)
}

defineExpose({ open })
</script>

<template>
  <div v-if="show" class="modal-overlay" @click.self="show = false">
    <div class="modal-box modal-lg">
      <div class="modal-header">
        <h3>小说解构 - {{ title }}</h3>
        <button class="modal-close" @click="show = false">×</button>
      </div>
      <div class="modal-body">
        <div v-if="loading" class="dis-loading" style="height:200px;">
          <div class="spinner" />
          <span>正在解构，请稍候 (大文件可能需要 30-60 秒)...</span>
        </div>
        <div v-else-if="data" class="deconstruct-result">
          <!-- 1. 题材标签 -->
          <div class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">1</span>题材标签</div>
            <div class="deconstruct-grid-2">
              <template v-for="(val, key) in data.genre_tags" :key="key">
                <div v-if="val && renderTagValue(val)" class="deconstruct-tag-row">
                  <span class="deconstruct-tag-label">{{ key }}</span>
                  <span class="deconstruct-tag-value">{{ renderTagValue(val) }}</span>
                </div>
              </template>
            </div>
          </div>
          <!-- 2. 结构拆解 -->
          <div class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">2</span>结构拆解</div>
            <div class="deconstruct-grid-2">
              <template v-for="(val, key) in data.structure" :key="key">
                <div v-if="val && renderTagValue(val)" class="deconstruct-tag-row">
                  <span class="deconstruct-tag-label">{{ key }}</span>
                  <span class="deconstruct-tag-value">{{ renderTagValue(val) }}</span>
                </div>
              </template>
            </div>
          </div>
          <!-- 3. 人物拆解 -->
          <div class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">3</span>人物拆解</div>
            <template v-if="data.characters">
              <div v-for="(items, key) in data.characters" :key="key" class="deconstruct-subsection">
                <template v-if="asArray(items).length > 0">
                  <b>{{ key }}</b>
                  <div class="deconstruct-list">
                    <div v-for="(item, i) in asArray(items).slice(0, 10)" :key="i" class="deconstruct-list-item">
                      {{ renderListItem(item) }}
                    </div>
                  </div>
                </template>
              </div>
            </template>
          </div>
          <!-- 4. 可借鉴元素 -->
          <div class="deconstruct-section">
            <div class="deconstruct-section-title"><span class="deconstruct-icon">4</span>可借鉴元素</div>
            <div class="deconstruct-grid-2">
              <template v-for="(val, key) in data.borrowable" :key="key">
                <div v-if="val && renderTagValue(val)" class="deconstruct-tag-row">
                  <span class="deconstruct-tag-label">{{ key }}</span>
                  <span class="deconstruct-tag-value">{{ renderTagValue(val) }}</span>
                </div>
              </template>
            </div>
          </div>
          <!-- 5. 避雷清单 -->
          <div class="deconstruct-section deconstruct-warnings">
            <div class="deconstruct-section-title"><span class="deconstruct-icon warn">5</span>避雷清单</div>
            <template v-if="data.warnings">
              <div v-for="(items, key) in data.warnings" :key="key" class="deconstruct-subsection">
                <template v-if="asArray(items).length > 0">
                  <b>{{ key }}</b>
                  <div class="deconstruct-list">
                    <div v-for="(item, i) in asArray(items)" :key="i" class="deconstruct-list-item warn">
                      {{ renderWarningItem(item) }}
                    </div>
                  </div>
                </template>
              </div>
            </template>
          </div>
        </div>
        <div v-else class="text-muted" style="padding:16px;">解构失败，请确认文件存在且后端正常</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
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

.dis-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; }
.spinner { width: 24px; height: 24px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }

.deconstruct-result { display: flex; flex-direction: column; gap: 16px; }
.deconstruct-section { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.deconstruct-section.deconstruct-warnings { border-color: rgba(239, 68, 68, 0.3); }
.deconstruct-section-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.deconstruct-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%; background: var(--accent); color: #0a0a0a;
  font-size: 11px; font-weight: 700; flex-shrink: 0;
}
.deconstruct-icon.warn { background: var(--danger); color: white; }
.deconstruct-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.deconstruct-tag-row { display: flex; gap: 6px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
.deconstruct-tag-row:last-child { border-bottom: none; }
.deconstruct-tag-label { color: var(--text-secondary); min-width: 80px; flex-shrink: 0; }
.deconstruct-tag-value { color: var(--text); word-break: break-all; }
.deconstruct-subsection { margin-bottom: 8px; }
.deconstruct-subsection b { font-size: 12px; display: block; margin-bottom: 4px; }
.deconstruct-list { display: flex; flex-direction: column; gap: 4px; }
.deconstruct-list-item { font-size: 12px; padding: 4px 8px; background: var(--surface-hover); border-radius: 4px; }
.deconstruct-list-item.warn { color: var(--danger); background: rgba(239, 68, 68, 0.05); }
.text-muted { color: var(--text-secondary); }
</style>
