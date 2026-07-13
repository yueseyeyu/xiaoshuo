/**
 * Reports API — 报告与指导端点
 */

import { apiGet } from './client'

// ── 类型定义 ──

export interface GuidanceItem {
  category: string
  title: string
  content: string
  priority: string
  examples?: string[]
}

export interface GuidanceData {
  guidance: GuidanceItem[]
  genre: string
  error?: string
}

export interface TechniqueItem {
  name: string
  category: string
  description: string
  example?: string
  usage?: string
}

export interface TechniqueData {
  techniques: TechniqueItem[]
  genre: string
  source?: string
}

export interface SkeletonData {
  book: string
  skeleton: string
  format?: string
  error?: string
}

export interface BlueprintParams {
  chapter: number
  total_chapters: number
  genre?: string
  outline_summary?: string
  canon_context?: string
  previous_summary?: string
  project_id?: string
}

export interface DiagnosisResult {
  book: string
  chapter: number
  diagnosis: Array<{
    category: string
    severity: string
    description: string
    suggestion?: string
  }>
  error?: string
}

// ── API 函数 ──

export const ReportsAPI = {
  /** 综合写作指导 */
  async getGuidance(genre?: string) {
    const q = genre ? `?genre=${encodeURIComponent(genre)}` : ''
    return apiGet<GuidanceData>(`/api/guidance${q}`)
  },

  /** 技法库 */
  async getTechniques(genre?: string) {
    const q = genre ? `?genre=${encodeURIComponent(genre)}` : ''
    return apiGet<TechniqueData>(`/api/techniques${q}`)
  },

  /** 章节骨架/大纲 */
  async getSkeleton(book?: string, genre?: string) {
    const params = new URLSearchParams()
    if (book) params.set('book', book)
    if (genre) params.set('genre', genre)
    const q = params.toString() ? `?${params.toString()}` : ''
    return apiGet<SkeletonData>(`/api/skeleton${q}`)
  },

  /** 章节施工单（蓝图） */
  async getBlueprint(params: BlueprintParams) {
    const q = new URLSearchParams()
    q.set('chapter', String(params.chapter))
    q.set('total_chapters', String(params.total_chapters))
    if (params.genre) q.set('genre', params.genre)
    if (params.outline_summary) q.set('outline_summary', params.outline_summary)
    if (params.canon_context) q.set('canon_context', params.canon_context)
    if (params.previous_summary) q.set('previous_summary', params.previous_summary)
    if (params.project_id) q.set('project_id', params.project_id)
    return apiGet<Record<string, unknown>>(`/api/blueprint?${q.toString()}`)
  },

  /** 深度诊断 */
  async getDiagnosis(book: string, chapter?: number, genre?: string) {
    const params = new URLSearchParams()
    params.set('book', book)
    if (chapter) params.set('chapter', String(chapter))
    if (genre) params.set('genre', genre)
    return apiGet<DiagnosisResult>(`/api/diagnosis?${params.toString()}`)
  },
}