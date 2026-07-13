<script setup lang="ts">
/**
 * AppLayout — 全局布局壳
 * TopBar + Sidebar + RouterView 主内容区
 */
import TopBar from './TopBar.vue'
import SideBar from './SideBar.vue'
import { useUiStore } from '@/stores/ui'

const uiStore = useUiStore()
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <div class="app-body">
      <SideBar :collapsed="uiStore.sidebarCollapsed" @toggle="uiStore.toggleSidebar()" />
      <main class="main-content">
        <RouterView />
      </main>
    </div>
    <!-- Toast 通知 -->
    <div class="toast-container" v-if="uiStore.toasts.length">
      <div
        v-for="toast in uiStore.toasts"
        :key="toast.id"
        class="toast"
        :class="toast.type"
        @click="uiStore.dismissToast(toast.id)"
      >
        {{ toast.text }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 210px 1fr;
  grid-template-rows: var(--topbar-height) 1fr;
  grid-template-areas:
    "topbar topbar"
    "sidebar main";
  height: 100vh;
  overflow: hidden;
}

.app-shell :deep(.topbar) {
  grid-area: topbar;
}

.app-shell :deep(.sidebar) {
  grid-area: sidebar;
}

.app-body {
  display: contents;
}

.main-content {
  grid-area: main;
  overflow: auto;
  background: var(--bg);
}

.toast-container {
  position: fixed;
  bottom: 24px;
  right: 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 9999;
}

.toast {
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  animation: toast-in 0.2s ease;
  max-width: 360px;
}

.toast.success {
  background: var(--success);
  color: var(--bg);
}

.toast.error {
  background: var(--danger);
  color: white;
}

.toast.info {
  background: var(--info);
  color: white;
}

@keyframes toast-in {
  from { transform: translateX(20px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
</style>
