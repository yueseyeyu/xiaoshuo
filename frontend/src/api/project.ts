/**
 * 项目 API — 对接后端 /api/projects/* 端点
 */

import { apiGet, apiPost, apiPut, apiDelete } from './client'
import type {
  Project,
  ProjectListItem,
  ProjectSkeleton,
  WorldInfo,
  Character,
  Faction,
  Chapter,
} from '@/types'

export const ProjectAPI = {
  async list(): Promise<{ ok: boolean; data?: ProjectListItem[]; error?: string }> {
    const res = await apiGet<{ projects: ProjectListItem[] }>('/api/projects')
    return { ok: res.ok, data: res.data?.projects, error: res.error }
  },

  /** 列出项目（含 demo 标记） */
  async listWithDemo(): Promise<{ ok: boolean; data?: ProjectListItem[]; error?: string }> {
    const res = await apiGet<{ projects: ProjectListItem[] }>('/api/projects?include_demo=true')
    return { ok: res.ok, data: res.data?.projects, error: res.error }
  },

  async get(id: string) {
    return apiGet<Project>(`/api/projects/${id}`)
  },

  async create(meta: Record<string, unknown>) {
    return apiPost<{ ok: boolean; project: Project }>('/api/projects', { meta })
  },

  async update(id: string, body: Record<string, unknown>) {
    return apiPut<{ ok: boolean; project: Project }>(`/api/projects/${id}`, body)
  },

  async remove(id: string) {
    return apiDelete<{ ok: boolean }>(`/api/projects/${id}`)
  },

  /** 从示例模板创建项目 */
  async createFromDemo() {
    return apiPost<{ ok: boolean; project: Project }>('/api/projects', { from_demo: true })
  },

  /** 获取示例项目模板（只读） */
  async getDemoTemplate() {
    return apiGet<Project>('/api/projects/demo')
  },

  async getSkeleton(id: string) {
    return apiGet<ProjectSkeleton>(`/api/projects/${id}/skeleton`)
  },

  async updateSkeleton(id: string, skeleton: Partial<ProjectSkeleton>) {
    return apiPut<{ ok: boolean; skeleton: ProjectSkeleton }>(
      `/api/projects/${id}/skeleton`, skeleton
    )
  },

  async getWorld(id: string) {
    return apiGet<WorldInfo>(`/api/projects/${id}/world`)
  },

  async updateWorld(id: string, world: Partial<WorldInfo>) {
    return apiPut<{ ok: boolean }>(`/api/projects/${id}/world`, world)
  },

  async getCharacters(id: string) {
    const res = await apiGet<{ characters: Character[] }>(`/api/projects/${id}/characters`)
    return { ok: res.ok, data: res.data?.characters, error: res.error }
  },

  async updateCharacters(id: string, characters: Character[]) {
    return apiPut<{ ok: boolean }>(`/api/projects/${id}/characters`, { characters })
  },

  async getFactions(id: string) {
    const res = await apiGet<{ factions: Faction[] }>(`/api/projects/${id}/factions`)
    return { ok: res.ok, data: res.data?.factions, error: res.error }
  },

  async updateFactions(id: string, factions: Faction[]) {
    return apiPut<{ ok: boolean }>(`/api/projects/${id}/factions`, { factions })
  },

  async getChapters(id: string) {
    const res = await apiGet<{ chapters: Chapter[] }>(`/api/projects/${id}/chapters`)
    return { ok: res.ok, data: res.data?.chapters, error: res.error }
  },

  async getChapter(id: string, num: number) {
    return apiGet<Chapter>(`/api/projects/${id}/chapters/${num}`)
  },

  async updateChapter(id: string, num: number, body: Partial<Chapter>) {
    return apiPut<{ ok: boolean }>(`/api/projects/${id}/chapters/${num}`, body)
  },

  /** Demo 项目转正（清除 is_demo 标记） */
  async promote(id: string) {
    return apiPost<{ ok: boolean; project: Project }>(`/api/projects/${id}/promote`)
  },
}
