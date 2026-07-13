<script setup lang="ts">
/**
 * AppSelect — 统一下拉框组件
 *
 * Props:
 *   modelValue: string | number
 *   options: Array<{ value: string | number; label: string }>
 *   placeholder?: string
 *   disabled?: boolean
 *   id?: string
 *
 * Emits: update:modelValue, change
 */
const props = defineProps<{
  modelValue: string | number
  options: Array<{ value: string | number; label: string }>
  placeholder?: string
  disabled?: boolean
  id?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string | number): void
  (e: 'change', v: string | number): void
}>()

function onChange(event: Event) {
  const target = event.target as HTMLSelectElement
  emit('update:modelValue', target.value)
  emit('change', target.value)
}
</script>

<template>
  <select :id="id" :disabled="disabled" :value="modelValue" class="app-select" @change="onChange">
    <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
    <option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
  </select>
</template>

<style scoped>
.app-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 6px 28px 6px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background-color: var(--surface);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  min-width: 120px;
  width: 100%;
}

.app-select:hover {
  border-color: var(--border-hover);
  background-color: var(--surface-hover);
}

.app-select:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.2);
}

.app-select option {
  background: var(--surface-solid);
  color: var(--text);
  padding: 6px 12px;
}

.app-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
