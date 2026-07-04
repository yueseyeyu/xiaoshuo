<script setup lang="ts">
/**
 * DesignEditModal — 设计页编辑抽屉
 * 支持 5 种编辑类型：卷/章节/角色/世界观/势力
 */
export type EditType = 'volume' | 'chapter' | 'character' | 'world' | 'faction'

defineProps<{
  open: boolean
  title: string
  type: EditType | null
  form: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save'): void
  (e: 'update:form', key: string, value: string): void
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="design-edit-overlay" @click.self="emit('close')">
      <div class="design-edit-modal">
        <div class="design-edit-header">
          <span class="design-edit-title">{{ title }}</span>
          <button class="icon-btn" @click="emit('close')">&times;</button>
        </div>
        <div class="design-edit-body">
          <!-- 卷编辑 -->
          <template v-if="type === 'volume'">
            <div class="edit-field"><label>卷标题</label><input :value="form.title" type="text" @input="emit('update:form', 'title', ($event.target as HTMLInputElement).value)" /></div>
            <div class="edit-field"><label>章节范围</label><input :value="form.range" type="text" @input="emit('update:form', 'range', ($event.target as HTMLInputElement).value)" /></div>
            <div class="edit-field"><label>副标题</label><input :value="form.subtitle" type="text" @input="emit('update:form', 'subtitle', ($event.target as HTMLInputElement).value)" /></div>
            <div class="edit-field"><label>摘要</label><textarea :value="form.summary" rows="3" @input="emit('update:form', 'summary', ($event.target as HTMLTextAreaElement).value)" /></div>
            <div class="edit-field"><label>标签（逗号分隔）</label><input :value="form.tags" type="text" @input="emit('update:form', 'tags', ($event.target as HTMLInputElement).value)" /></div>
          </template>
          <!-- 章节编辑 -->
          <template v-else-if="type === 'chapter'">
            <div class="edit-section"><label class="edit-section-title">基础结构</label>
              <div class="edit-field"><label>标题</label><input :value="form.title" type="text" @input="emit('update:form', 'title', ($event.target as HTMLInputElement).value)" /></div>
              <div class="edit-field"><label>目标</label><textarea :value="form.goal" rows="2" @input="emit('update:form', 'goal', ($event.target as HTMLTextAreaElement).value)" /></div>
              <div class="edit-field"><label>冲突</label><textarea :value="form.conflict" rows="2" @input="emit('update:form', 'conflict', ($event.target as HTMLTextAreaElement).value)" /></div>
              <div class="edit-field"><label>结果</label><textarea :value="form.result" rows="2" @input="emit('update:form', 'result', ($event.target as HTMLTextAreaElement).value)" /></div>
            </div>
            <div class="edit-section"><label class="edit-section-title">网文核心要素 <span class="edit-hint">（决定读者留存率）</span></label>
              <div class="edit-field"><label>钩子</label><textarea :value="form.hook" rows="2" placeholder="例：结尾揭露主角身世之谜" @input="emit('update:form', 'hook', ($event.target as HTMLTextAreaElement).value)" /></div>
              <div class="edit-field"><label>爽点</label><textarea :value="form.pleasure" rows="2" placeholder="例：装逼打脸，实力碾压" @input="emit('update:form', 'pleasure', ($event.target as HTMLTextAreaElement).value)" /></div>
              <div class="edit-field"><label>伏笔</label><textarea :value="form.foreshadowing" rows="2" placeholder="例：老K的伤疤 → 第45章揭露" @input="emit('update:form', 'foreshadowing', ($event.target as HTMLTextAreaElement).value)" /></div>
              <div class="edit-field"><label>期待感</label><textarea :value="form.expectation" rows="2" placeholder="例：暗示更大危机即将到来" @input="emit('update:form', 'expectation', ($event.target as HTMLTextAreaElement).value)" /></div>
            </div>
            <div class="edit-section"><label class="edit-section-title">场景列表</label>
              <div class="edit-field"><label>场景（每行一个）</label><textarea :value="form.scenes" rows="3" @input="emit('update:form', 'scenes', ($event.target as HTMLTextAreaElement).value)" /></div>
            </div>
          </template>
          <!-- 角色编辑 -->
          <template v-else-if="type === 'character'">
            <div class="edit-field"><label>姓名</label><input :value="form.name" type="text" @input="emit('update:form', 'name', ($event.target as HTMLInputElement).value)" /></div>
            <div class="edit-field"><label>身份</label><input :value="form.role" type="text" @input="emit('update:form', 'role', ($event.target as HTMLInputElement).value)" /></div>
            <div class="edit-field"><label>人物小传</label><textarea :value="form.desc" rows="4" @input="emit('update:form', 'desc', ($event.target as HTMLTextAreaElement).value)" /></div>
          </template>
          <!-- 世界观编辑 -->
          <template v-else-if="type === 'world'">
            <div class="edit-field"><label>核心设定</label><textarea :value="form.core" rows="4" @input="emit('update:form', 'core', ($event.target as HTMLTextAreaElement).value)" /></div>
            <div class="edit-field"><label>能力体系</label><textarea :value="form.powers" rows="3" @input="emit('update:form', 'powers', ($event.target as HTMLTextAreaElement).value)" /></div>
          </template>
          <!-- 势力编辑 -->
          <template v-else-if="type === 'faction'">
            <div class="edit-field"><label>势力名称</label><input :value="form.name" type="text" @input="emit('update:form', 'name', ($event.target as HTMLInputElement).value)" /></div>
            <div class="edit-field"><label>势力描述</label><textarea :value="form.desc" rows="3" @input="emit('update:form', 'desc', ($event.target as HTMLTextAreaElement).value)" /></div>
          </template>
        </div>
        <div class="design-edit-footer">
          <button class="btn btn-ghost" @click="emit('close')">取消</button>
          <button class="btn btn-primary" @click="emit('save')">保存</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.design-edit-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.design-edit-modal { background: var(--surface-solid); border: 1px solid var(--border); border-radius: 12px; width: 90%; max-width: 560px; max-height: 85vh; display: flex; flex-direction: column; }
.design-edit-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.design-edit-title { font-size: 15px; font-weight: 600; }
.icon-btn { background: none; border: none; font-size: 20px; color: var(--text-secondary); cursor: pointer; padding: 4px 8px; }
.icon-btn:hover { color: var(--text); }
.design-edit-body { padding: 16px; overflow-y: auto; flex: 1; }
.design-edit-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); }
.edit-section { margin-bottom: 16px; }
.edit-section-title { font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px; color: var(--accent); }
.edit-hint { font-size: 11px; color: var(--text-secondary); font-weight: 400; }
.edit-field { margin-bottom: 10px; }
.edit-field label { font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: 4px; }
.edit-field input, .edit-field textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font-size: 13px; font-family: inherit; }
.edit-field input:focus, .edit-field textarea:focus { outline: none; border-color: var(--accent); }
</style>