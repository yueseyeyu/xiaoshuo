<script setup lang="ts">
/**
 * ConfirmModal — 全局确认对话框
 *
 * 通过 uiStore.showConfirm({ title, message, confirmText, cancelText, type })
 * 调用，返回 Promise<boolean>。
 */
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()
const confirm = uiStore.confirm

function onConfirm() {
  uiStore.closeConfirm(true)
}

function onCancel() {
  uiStore.closeConfirm(false)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="confirm-fade">
      <div v-if="confirm.visible" class="confirm-overlay" @click.self="onCancel">
        <div class="confirm-dialog" role="dialog" aria-modal="true">
          <div class="confirm-header">
            <span class="confirm-icon" :class="confirm.type">
              <svg v-if="confirm.type === 'danger'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
              </svg>
            </span>
            <h3 class="confirm-title">{{ confirm.title }}</h3>
          </div>
          <p class="confirm-message">{{ confirm.message }}</p>
          <div class="confirm-actions">
            <button class="btn btn-ghost btn-sm" @click="onCancel">{{ confirm.cancelText }}</button>
            <button class="btn btn-primary btn-sm" :class="confirm.type === 'danger' ? 'btn-danger' : ''" @click="onConfirm">{{ confirm.confirmText }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
}

.confirm-dialog {
  width: 100%;
  max-width: 420px;
  padding: 24px;
  border-radius: 16px;
  background: var(--surface);
  border: 1px solid rgba(var(--text-rgb), 0.1);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.35);
}

.confirm-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.confirm-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: var(--warning);
  background: rgba(var(--warning-rgb), 0.12);
}

.confirm-icon.danger {
  color: var(--danger);
  background: rgba(var(--danger-rgb), 0.12);
}

.confirm-title {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
}

.confirm-message {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin: 0 0 24px 0;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.confirm-fade-enter-active,
.confirm-fade-leave-active {
  transition: opacity 0.2s ease;
}
.confirm-fade-enter-from,
.confirm-fade-leave-to {
  opacity: 0;
}
</style>
