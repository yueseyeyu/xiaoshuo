<script setup lang="ts">
/**
 * CreateProjectModal — 创建新作品模态框
 *
 * 从 DashboardView 提取，封装表单状态与验证逻辑。
 */
import { ref } from 'vue'
import { useUiStore } from '@/stores/ui'
import { useProjectStore } from '@/stores/project'

const uiStore = useUiStore()
const projectStore = useProjectStore()

const show = defineModel<boolean>('show', { required: true })
const creating = ref(false)

const form = ref({
  title: '',
  genre: '末世',
  volumes: 5,
  chapters: 300,
  summary: '',
})

async function confirmCreate() {
  const title = form.value.title.trim()
  if (!title) {
    uiStore.showToast('请输入作品名称', 'error')
    return
  }
  creating.value = true
  const cleanTitle = '《' + title.replace(/《|》/g, '') + '》'
  const ok = await projectStore.createProject({
    title: cleanTitle,
    author: '作者',
    genre: form.value.genre,
    volumes_count: form.value.volumes,
    total_chapters: form.value.chapters,
    written_chapters: 0,
    summary: form.value.summary,
  })
  creating.value = false
  if (ok) {
    show.value = false
    form.value = { title: '', genre: '末世', volumes: 5, chapters: 300, summary: '' }
    uiStore.showToast('已创建作品', 'success')
    setTimeout(() => {
      uiStore.showToast('下一步：在书库中导入参考书，或在设计页规划粗纲', 'info')
    }, 2800)
  } else {
    uiStore.showToast('创建作品失败', 'error')
  }
}
</script>

<template>
  <div v-if="show" class="modal-overlay" @click.self="show = false">
    <div class="modal-card">
      <div class="modal-header">
        <h3>创建新作品</h3>
        <button class="icon-btn" @click="show = false">×</button>
      </div>
      <div class="modal-body">
        <div class="form-row">
          <label>作品名称</label>
          <input type="text" v-model="form.title" placeholder="输入书名..." />
        </div>
        <div class="form-row">
          <label>题材类型</label>
          <select v-model="form.genre">
            <option value="末世">末世</option>
            <option value="仙侠">仙侠</option>
            <option value="科幻">科幻</option>
            <option value="都市">都市</option>
            <option value="悬疑">悬疑</option>
            <option value="无限流">无限流</option>
            <option value="历史">历史</option>
            <option value="奇幻">奇幻</option>
            <option value="洪荒">洪荒</option>
            <option value="同人">同人</option>
          </select>
        </div>
        <div class="form-row">
          <label>规划卷数</label>
          <input type="number" v-model.number="form.volumes" min="1" max="20" />
        </div>
        <div class="form-row">
          <label>预计总章数</label>
          <input type="number" v-model.number="form.chapters" min="1" max="2000" />
        </div>
        <div class="form-row">
          <label>作品简介<span class="form-hint">（可选）</span></label>
          <textarea v-model="form.summary" rows="2" placeholder="简单描述你的故事方向..."></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="show = false">取消</button>
        <button class="btn btn-primary" :disabled="creating" @click="confirmCreate">
          {{ creating ? '创建中...' : '创建作品' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-card {
  width: 460px;
  max-width: 90vw;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.modal-header h3 {
  font-size: 16px;
  font-weight: 600;
}
.icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-btn:hover {
  background: var(--surface-hover);
}
.modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-row label {
  font-size: 13px;
  color: var(--text-secondary);
}
.form-hint {
  color: var(--text-muted);
  font-size: 11px;
  margin-left: 4px;
}
.form-row input,
.form-row select,
.form-row textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
}
.form-row input:focus,
.form-row select:focus,
.form-row textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.form-row textarea {
  resize: vertical;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px 20px;
  border-top: 1px solid var(--border);
}
/* ── 按钮 — 全局 style.css 接管 ── */
</style>
