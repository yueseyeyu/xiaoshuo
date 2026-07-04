/**
 * Library API — 书库管理
 */

import { apiGet, apiPost } from './client'

export interface Book {
  title: string
  author: string
  genre: string
  wordCount?: number
  size_kb?: number
  file?: string
  stem?: string     // 词干/文件名
  status?: string
  score?: number | null
  techniqueCards?: number | null
  totalChapters?: number
  tags?: string[]
  disassembly?: {
    chapters?: number
    emotion_dist?: Record<string, number>
    pace_dist?: Record<string, number>
  }
}

export interface LibraryData {
  books: Book[]
  count: number
  genre: string
  genres: string[]
  counts: Array<[string, number]>
}

export const LibraryAPI = {
  /** 获取全部书库数据 */
  async getBooks(genre?: string) {
    const q = genre && genre !== '全部' ? `?genre=${encodeURIComponent(genre)}` : ''
    return apiGet<LibraryData>(`/api/books${q}`)
  },

  /** 启动拆书分析 — 后端使用 query params 解析 genre/books */
  async startAnalysis(genre: string, books?: string) {
    const params = new URLSearchParams({ genre })
    if (books) params.set('books', books)
    return apiPost<{ ok: boolean; message: string }>(`/api/start?${params.toString()}`)
  },
}
