/**
 * Vue Router — 路由配置
 *
 * 所有页面已从 jQuery 原型迁移至 Vue 3 组件
 * LegacyView iframe 代理已彻底移除
 */

import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/world',
      name: 'world',
      component: () => import('@/views/WorldView.vue'),
      meta: { title: '世界推演', icon: 'globe' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: '工作台', icon: 'dashboard' },
    },
    {
      path: '/library',
      name: 'library',
      component: () => import('@/views/LibraryView.vue'),
      meta: { title: '书库', icon: 'library' },
    },
    {
      path: '/disassembly',
      name: 'disassembly',
      component: () => import('@/views/DisassemblyView.vue'),
      meta: { title: '拆书', icon: 'disassembly' },
    },
    {
      path: '/reports',
      name: 'reports',
      component: () => import('@/views/ReportsView.vue'),
      meta: { title: '报告', icon: 'reports' },
    },
    {
      path: '/design',
      name: 'design',
      component: () => import('@/views/DesignView.vue'),
      meta: { title: '设计', icon: 'design' },
    },
    {
      path: '/writing',
      name: 'writing',
      component: () => import('@/views/WritingView.vue'),
      meta: { title: '写作', icon: 'writing' },
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('@/views/LogsView.vue'),
      meta: { title: '日志', icon: 'logs' },
    },
    {
      path: '/hardware',
      name: 'hardware',
      component: () => import('@/views/HardwareView.vue'),
      meta: { title: '硬件', icon: 'hardware' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { title: '设置', icon: 'settings' },
    },
  ],
})

// 路由守卫：更新页面标题
router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} · 小说工坊` : '小说工坊'
})

export default router
