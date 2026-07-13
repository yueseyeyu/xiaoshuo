<script setup lang="ts">
/**
 * SideBar — 侧边导航栏
 * 210px 展开模式，图标+文字并排，激活态左侧 accent 竖条
 */
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const props = defineProps<{ collapsed?: boolean }>()
const emit = defineEmits<{ (e: 'toggle'): void }>()

const route = useRoute()
const currentName = computed(() => route.name as string)

interface NavItem {
  name: string
  label: string
  icon: string
}

const navTop: NavItem[] = [
  { name: 'dashboard', label: '工作台', icon: 'M3 3h18v18H3zM7 7h4v4H7zM7 15h4v4H7zM15 7h4v4h-4zM15 15h4v4h-4z' },
  { name: 'library', label: '书库', icon: 'M4 6h7v2H4zm0 5h7v2H4zm0 5h7v2H4zm9-10h7v2h-7zm0 5h7v2h-7zm0 5h7v2h-7z' },
  { name: 'disassembly', label: '拆书', icon: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.08-3.08a6 6 0 0 1-7.06 7.06l-6.36 6.36a2.5 2.5 0 1 1-3.54-3.54l6.36-6.36a6 6 0 0 1 7.06-7.06l-2.08 2.08z' },
  { name: 'reports', label: '报告', icon: 'M9 17v-2H4.5A2.5 2.5 0 0 1 2 12.5v-9A2.5 2.5 0 0 1 4.5 1h9A2.5 2.5 0 0 1 16 3.5V9h-2V3.5a.5.5 0 0 0-.5-.5h-9a.5.5 0 0 0-.5.5v9a.5.5 0 0 0 .5.5H9zm9.5 7h-9a2.5 2.5 0 0 1-2.5-2.5v-9a2.5 2.5 0 0 1 2.5-2.5h9a2.5 2.5 0 0 1 2.5 2.5v9a2.5 2.5 0 0 1-2.5 2.5z' },
  { name: 'design', label: '设计', icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' },
  { name: 'world', label: '世界推演', icon: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2a8 8 0 0 1 8 8h-3a5 5 0 0 0-5-5V4zm0 16a8 8 0 0 1-8-8h3a5 5 0 0 0 5 5v3z' },
  { name: 'writing', label: '写作', icon: 'M11 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z' },
]

const navBottom: NavItem[] = [
  { name: 'logs', label: '日志', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' },
  { name: 'hardware', label: '硬件', icon: 'M4 4h16v12H4zM9 20h6M12 16v4' },
  { name: 'settings', label: '设置', icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 2a5 5 0 1 1 0-10 5 5 0 0 1 0 10z' },
]
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: props.collapsed }">
    <nav class="nav-top">
      <RouterLink
        v-for="item in navTop"
        :key="item.name"
        :to="{ name: item.name }"
        class="nav-item"
        :class="{ active: currentName === item.name }"
      >
        <span class="nav-active-bar"></span>
        <svg class="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="item.icon" />
        </svg>
        <span class="nav-label">{{ item.label }}</span>
      </RouterLink>
    </nav>
    <div class="nav-divider"></div>
    <nav class="nav-bottom">
      <RouterLink
        v-for="item in navBottom"
        :key="item.name"
        :to="{ name: item.name }"
        class="nav-item"
        :class="{ active: currentName === item.name }"
      >
        <span class="nav-active-bar"></span>
        <svg class="nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="item.icon" />
        </svg>
        <span class="nav-label">{{ item.label }}</span>
      </RouterLink>
    </nav>
    <button class="collapse-btn" @click="emit('toggle')" :title="props.collapsed ? '展开侧栏' : '折叠侧栏'">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path v-if="props.collapsed" d="M9 18l6-6-6-6" />
        <path v-else d="M15 18l-6-6 6-6" />
      </svg>
      <span class="nav-label" v-if="!props.collapsed">折叠</span>
    </button>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 210px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated);
  border-right: 1px solid var(--border);
  padding: 8px 0 12px;
  transition: width 0.2s ease;
  position: relative;
  overflow: hidden;
}

/* 底部氛围光 */
.sidebar::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 120px;
  background: linear-gradient(to top, rgba(var(--accent-rgb), 0.04), transparent);
  pointer-events: none;
  z-index: 0;
}

.sidebar.collapsed {
  width: 56px;
}

.nav-top,
.nav-bottom {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
  position: relative;
  z-index: 1;
}

.nav-bottom {
  margin-top: auto;
}

.nav-divider {
  height: 1px;
  background: var(--border);
  margin: 8px 16px;
  position: relative;
  z-index: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.15s ease;
  position: relative;
  height: 40px;
  overflow: hidden;
}

.nav-item:hover {
  background: var(--surface-hover);
  color: var(--text);
}

.nav-item.active {
  background: var(--surface-highlight);
  color: var(--accent);
}

/* 激活态左侧 accent 竖条 */
.nav-active-bar {
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: var(--accent);
  border-radius: 0 3px 3px 0;
  opacity: 0;
  transform: scaleY(0.5);
  transition: opacity 0.2s ease, transform 0.25s ease;
}

.nav-item.active .nav-active-bar {
  opacity: 1;
  transform: scaleY(1);
}

.nav-icon {
  flex-shrink: 0;
}

.nav-label {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  transition: opacity 0.15s ease;
}

.collapsed .nav-label {
  opacity: 0;
  width: 0;
}

.collapse-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin: 4px 8px 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-disabled);
  cursor: pointer;
  transition: all 0.15s;
  position: relative;
  z-index: 1;
  height: 36px;
}

.collapse-btn:hover {
  color: var(--text-secondary);
  background: var(--surface-hover);
}

.collapsed .collapse-btn {
  justify-content: center;
  padding: 8px;
}
</style>
