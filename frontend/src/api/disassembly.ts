/**
 * Disassembly API — 拆书分析
 */

import { apiGet, apiPost } from './client'

export interface DisassemblyChapter {
  ch?: number
  pace?: string
  emotion?: string
  conflict?: boolean
  pleasure_type?: string
  pleasure_level?: string
  wc?: number
}

export interface DisassemblySummary {
  chapters?: number
  total_words?: number
  emotion_dist?: Record<string, number>
  pace_dist?: Record<string, number>
  conflict_dist?: Record<string, number>
  pleasure_dist?: Record<string, number>
  characters?: Array<{ name: string; role: string }>
}

export interface DisassemblyBook {
  key?: string
  title?: string
  genre?: string
  summary?: DisassemblySummary
  chapters?: DisassemblyChapter[]
  total?: number
  book?: string
}

export interface DisassemblyListResponse {
  books: DisassemblyBook[]
}

// ── 任务管理 ──

export interface AnalysisTask {
  id: string
  name?: string
  type: string
  genre?: string
  books: string[]
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message?: string
  created_at?: string
  updated_at?: string
}

export interface TaskListResponse {
  tasks: AnalysisTask[]
}

export interface TaskCreateBody {
  type: string
  name?: string
  genre?: string
  books: string[]
}

export const DisassemblyAPI = {
  /** 获取已拆书列表 */
  async getBooks() {
    return apiGet<DisassemblyListResponse>('/api/disassembly/books')
  },

  /** 获取单本书的拆书详情 */
  async getBookDetail(name: string) {
    return apiGet<DisassemblyBook>(`/api/disassembly/book?name=${encodeURIComponent(name)}`)
  },

  /** 获取任务列表 */
  async getTasks() {
    return apiGet<TaskListResponse>('/api/tasks')
  },

  /** 创建任务 */
  async createTask(body: TaskCreateBody) {
    return apiPost<{ ok: boolean; task: AnalysisTask }>('/api/tasks', body)
  },

  /** 查询单个任务状态 */
  async getTask(id: string) {
    return apiGet<AnalysisTask>(`/api/task?id=${encodeURIComponent(id)}`)
  },
}
