<script setup lang="ts">
/**
 * TaskCreateModal — 新建拆书任务模态框
 *
 * 从 DisassemblyView 提取，封装任务表单状态与提交逻辑。
 */
import { ref } from 'vue'
import { useUiStore } from '@/stores/ui'
import { useProjectStore } from '@/stores/project'
import { DisassemblyAPI } from '@/api/disassembly'
import type { Book } from '@/api/library'

const uiStore = useUiStore()
const projectStore = useProjectStore()

const show = defineModel<boolean>('show', { required: true })

const props = defineProps<{
  books: Book[]
}>()

const emit = defineEmits<{
  created: []
}>()

const taskTypeLabels: Record<string, string> = {
  full: '完整分析',
  rhythm: '节奏分析',
  emotion: '情绪分析',
}

const form = ref({
  type: 'full',
  selectedBooks: [] as number[],
})

async function submit() {
  const selected = form.value.selectedBooks
    .map((i) => props.books[i])
    .filter(Boolean)
  if (selected.length === 0) {
    uiStore.showToast('请至少选择一本书')
    return
  }
  const files = selected.map((b) => b.file || b.title).filter(Boolean)
  const titles = selected.map((b) => b.title)
  const res = await DisassemblyAPI.createTask({
    type: form.value.type,
    name: `${taskTypeLabels[form.value.type] || form.value.type} - ${titles[0] || ''}`,
    genre: projectStore.projectGenre,
    books: files,
  })
  if (res.ok) {
    uiStore.showToast('任务已创建', 'success')
    show.value = false
    form.value = { type: 'full', selectedBooks: [] }
    emit('created')
  } else {
    uiStore.showToast('创建任务失败: ' + (res.error || ''), 'error')
  }
}
</script>

<template>
  <div v-if="show" class="modal-overlay" @click.self="show = false">
    <div class="modal-box">
      <div class="modal-header">
        <h3>新建拆书任务</h3>
        <button class="modal-close" @click="show = false">×</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label>任务类型</label>
          <select v-model="form.type" class="form-select">
            <option value="full">完整分析</option>
            <option value="rhythm">节奏分析</option>
            <option value="emotion">情绪分析</option>
          </select>
        </div>
        <div class="form-group">
          <label>选择书籍</label>
          <div class="book-checklist">
            <label
              v-for="(b, i) in books"
              :key="i"
              class="book-checkbox"
            >
              <input
                type="checkbox"
                :value="i"
                v-model="form.selectedBooks"
              />
              <span>{{ b.title }}</span>
            </label>
            <div v-if="books.length === 0" class="text-muted" style="padding:8px 0;">书库为空</div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary btn-sm" @click="show = false">取消</button>
        <button class="btn btn-primary btn-sm" @click="submit">创建任务</button>
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
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.modal-header h3 { font-size: 15px; font-weight: 600; }
.modal-close { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--text-muted); }
.modal-body { flex: 1; overflow-y: auto; padding: 16px 18px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--border); }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.form-select { width: 100%; height: 32px; padding: 0 8px; font-size: 13px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; color: var(--text); }
.book-checklist { display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto; }
.book-checkbox { display: flex; align-items: center; gap: 6px; padding: 4px 8px; font-size: 12px; cursor: pointer; }
.book-checkbox input { margin: 0; }
.text-muted { color: var(--text-secondary); }
/* ── 按钮 — 全局 style.css 接管 ── */
</style>
