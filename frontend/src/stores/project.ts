/**
 * 项目 Store — 管理当前项目状态
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ProjectAPI } from '@/api/project'
import type { Project, ProjectListItem, ProjectMeta } from '@/types'

export const useProjectStore = defineStore('project', () => {
  // ── State ──
  const projects = ref<ProjectListItem[]>([])
  const currentProject = ref<Project | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── Computed ──
  const hasProject = computed(() => currentProject.value !== null)
  const projectTitle = computed(() => currentProject.value?.meta.title ?? '未命名作品')
  const projectGenre = computed(() => currentProject.value?.meta.genre ?? '末世')

  // ── Actions ──
  async function loadProjects() {
    loading.value = true
    error.value = null
    const res = await ProjectAPI.list()
    if (res.ok && res.data) {
      projects.value = res.data
    } else {
      error.value = res.error ?? '加载项目列表失败'
    }
    loading.value = false
  }

  async function loadProject(id: string) {
    loading.value = true
    error.value = null
    const res = await ProjectAPI.get(id)
    if (res.ok && res.data) {
      currentProject.value = res.data
    } else {
      error.value = res.error ?? '加载项目失败'
    }
    loading.value = false
  }

  async function createProject(meta: Partial<ProjectMeta>) {
    loading.value = true
    error.value = null
    const res = await ProjectAPI.create(meta)
    if (res.ok && res.data) {
      currentProject.value = res.data.project
      await loadProjects()
    } else {
      error.value = res.error ?? '创建项目失败'
    }
    loading.value = false
    return res.ok
  }

  /** 加载示例项目（复用已有 demo 或创建新的） */
  async function loadDemoProject(): Promise<boolean> {
    loading.value = true
    error.value = null
    // 先尝试复用已有 demo 项目
    const res = await ProjectAPI.listWithDemo()
    if (res.ok && res.data) {
      const demo = res.data.find((p) => p.is_demo)
      if (demo) {
        await loadProject(demo.id)
        return true
      }
    }
    // 没有则创建
    const createRes = await ProjectAPI.createFromDemo()
    if (createRes.ok && createRes.data) {
      currentProject.value = createRes.data.project
      await loadProjects()
      return true
    }
    error.value = createRes.error ?? '加载示例项目失败'
    loading.value = false
    return false
  }

  /** 退出并删除 demo 项目 */
  async function exitDemoProject(): Promise<void> {
    const demoId = currentProject.value?.id
    currentProject.value = null
    if (demoId) {
      await ProjectAPI.remove(demoId)
      await loadProjects()
    }
  }

  function clearCurrent() {
    currentProject.value = null
  }

  return {
    projects,
    currentProject,
    loading,
    error,
    hasProject,
    projectTitle,
    projectGenre,
    loadProjects,
    loadProject,
    createProject,
    loadDemoProject,
    exitDemoProject,
    clearCurrent,
  }
})
