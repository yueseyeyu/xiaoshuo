<script setup lang="ts">
/**
 * EmptyState — 统一空状态组件
 *
 * Props:
 * - icon: SVG path 的 d 属性（多条 path 用空格分隔）
 * - title: 主标题
 * - description: 描述文字
 * - actionText?: 主按钮文字
 * - actionHref?: 点击后跳转的路由名
 *
 * Emits:
 * - action: 点击主按钮
 */
interface Props {
  icon: string
  title: string
  description: string
  actionText?: string
  compact?: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'action'): void }>()
</script>

<template>
  <div class="empty-state" :class="{ compact: props.compact }">
    <div class="empty-state-icon">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path :d="props.icon" />
      </svg>
    </div>
    <h3 class="empty-state-title">{{ props.title }}</h3>
    <p class="empty-state-desc">{{ props.description }}</p>
    <div v-if="props.actionText" class="empty-state-actions">
      <button class="btn btn-primary" @click="emit('action')">
        {{ props.actionText }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 48px 24px;
  min-height: 320px;
  color: var(--text);
}
.empty-state.compact {
  min-height: 180px;
  padding: 32px 24px;
}
.empty-state-icon {
  color: var(--text-muted);
  margin-bottom: 16px;
}
.empty-state-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 8px;
}
.empty-state-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 420px;
  margin: 0 0 20px;
}
.empty-state-actions {
  display: flex;
  gap: 12px;
}
</style>
