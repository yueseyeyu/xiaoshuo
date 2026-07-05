<script setup lang="ts" generic="T extends string | number">
/**
 * TabBar — 统一标签栏组件
 *
 * 用法：
 * <TabBar v-model="activeTab" :options="[{ label: '拆书分析', value: 'disassembly' }, { label: '小说解构', value: 'deconstruction' }]" />
 */
import { computed } from 'vue'

interface TabOption<T> {
  label: string
  value: T
  disabled?: boolean
  icon?: string
}

const props = defineProps<{
  modelValue: T
  options: TabOption<T>[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: T): void
}>()

const activeIndex = computed(() => props.options.findIndex((o) => o.value === props.modelValue))

function select(option: TabOption<T>) {
  if (option.disabled) return
  emit('update:modelValue', option.value)
}
</script>

<template>
  <div class="tab-bar" role="tablist">
    <div class="tab-bar-track">
      <button
        v-for="option in options"
        :key="String(option.value)"
        class="tab-bar-item"
        :class="{ active: option.value === modelValue, disabled: option.disabled }"
        role="tab"
        :aria-selected="option.value === modelValue"
        @click="select(option)"
      >
        <svg v-if="option.icon" class="tab-bar-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="option.icon" />
        </svg>
        {{ option.label }}
      </button>
      <span class="tab-bar-indicator" :style="{ transform: `translateX(${activeIndex * 100}%)` }" />
    </div>
  </div>
</template>

<style scoped>
.tab-bar {
  display: inline-flex;
  padding: 4px;
  border-radius: var(--radius-lg, 12px);
  background: var(--surface-faint, rgba(var(--text-rgb), 0.04));
  border: 1px solid rgba(var(--text-rgb), 0.08);
}

.tab-bar-track {
  position: relative;
  display: flex;
  gap: 2px;
}

.tab-bar-item {
  position: relative;
  z-index: 1;
  padding: 7px 16px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--radius-md, 10px);
  cursor: pointer;
  transition: color 0.2s ease;
}

.tab-bar-item:hover:not(.disabled) {
  color: var(--text);
}

.tab-bar-item.active {
  color: var(--text);
}

.tab-bar-item.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tab-bar-icon {
  flex-shrink: 0;
  opacity: 0.8;
}

.tab-bar-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: calc(100% / v-bind('options.length'));
  border-radius: var(--radius-md, 10px);
  background: var(--surface-solid, rgba(var(--text-rgb), 0.08));
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
</style>
