/**
 * Dashboard API — 工作台所需的杂项后端端点
 *
 * 涵盖：书库统计、拆书管线进度、报告概览、硬件监控、分析启停
 */

import { apiGet, apiPost } from './client'

// ── 类型定义 ──

export interface BooksSummary {
  books: Array<{ title: string; author: string; genre: string }>
  count: number
  genre: string
  genres: string[]
  counts: Array<[string, number]>
}

export interface PipelineStage {
  stage: string
  stage_num: number
  total: number
  percent: number
  current_task: string
  current_book: string
  status: string
  completed_books: string[]
}

export interface StartupState {
  status: string
  message: string
  progress: number
}

export interface ProgressData {
  running: boolean
  startup_state: StartupState
  pipeline_stage: PipelineStage | null
  llm_healthy: boolean
}

export interface ReportOverview {
  genre: string
  stats?: { books: number; chapters: number; words: number }
  technique_cards?: Array<{ title: string; content: string; category?: string; id?: string }>
  rhythm_audit?: { total_books: number; passed: number; warnings: number; failed: number }
  score_audit?: { total_books: number; status: string; outlier_count?: number; summary?: Record<string, unknown> }
  quality_manifest?: { approved: number; quarantined: number; failed: number }
  distributions?: {
    pace?: Record<string, number>
    pleasure?: Record<string, number>
    emotion?: Record<string, number>
  }
}

export interface HardwareData {
  gpu: {
    temp: number
    util: number
    vram_pct: number
    vram_used_mb: number
    vram_total_mb: number
    fan_speed: number
  }
  cpu: { pct: number }
  ram: { pct: number; used_gb: number; total_gb: number }
  updated_at: string
  gpu_available: boolean
}

export interface ConfigData {
  version: string
  genre: string
  llm_port: number
  mode: string
  local_model: string
  cloud_model: string
  cloud_provider: string
}

export interface ModelInfo {
  name: string
  running: boolean
  healthy: boolean
  enabled: boolean
  port: number
  quant?: string
}

export interface ModelStatusData {
  mode: string
  models: {
    main_model?: ModelInfo
    cross_model?: ModelInfo
    [key: string]: ModelInfo | undefined
  }
  error?: string
}

export interface SceneResult {
  rank: number
  similarity: number
  book_name: string
  chapter: number
  scene_index: number
  char_count: number
  text_preview: string
  emotion: string
  pace: string
  conflict_level: string
  pleasure_type: string
  dominant_sub: string
  technique_summary: string
}

export interface SearchData {
  query: string
  genre: string
  total_scenes: number
  results: SceneResult[]
}

export interface IndexStats {
  genre: string
  total_scenes: number
  total_books: number
}

// ── API 函数 ──

export const DashboardAPI = {
  /** 书库统计 */
  async getBooks() {
    return apiGet<BooksSummary>('/api/books')
  },

  /** 拆书管线进度 */
  async getProgress() {
    return apiGet<ProgressData>('/api/progress')
  },

  /** 报告概览（技法卡片+节奏审计） */
  async getReportOverview(genre?: string) {
    const q = genre ? `?genre=${encodeURIComponent(genre)}` : ''
    return apiGet<ReportOverview>(`/api/reports/overview${q}`)
  },

  /** 硬件监控 */
  async getHardware() {
    return apiGet<HardwareData>('/api/hardware')
  },

  /** 系统配置 */
  async getConfig() {
    return apiGet<ConfigData>('/api/config')
  },

  /** 停止拆书分析 */
  async stopAnalysis() {
    return apiPost<{ ok: boolean; message: string }>('/api/stop', {})
  },

  /** 模型状态 */
  async getModelStatus() {
    return apiGet<ModelStatusData>('/api/model/status')
  },

  /** 启动模型 */
  async startModel() {
    return apiPost<{ success: boolean; status: ModelStatusData }>('/api/model/start', {})
  },

  /** 停止模型 */
  async stopModel() {
    return apiPost<{ success: boolean; status: ModelStatusData }>('/api/model/stop', {})
  },

  /** 场景搜索 */
  async search(q: string, genre?: string, top?: number) {
    const params = new URLSearchParams()
    params.set('q', q)
    if (genre) params.set('genre', genre)
    if (top) params.set('top', String(top))
    return apiGet<SearchData>(`/api/search?${params.toString()}`)
  },

  /** 索引统计 */
  async getStats(genre?: string) {
    const q = genre ? `?genre=${encodeURIComponent(genre)}` : ''
    return apiGet<IndexStats>(`/api/stats${q}`)
  },
}
