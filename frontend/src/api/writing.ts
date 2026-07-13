/**
 * Writing API — 写作辅助端点
 * 对接 /api/instructions、/api/style/* 端点
 */

import { apiGet, apiPost } from './client'

// ── 类型 ──

export interface InstructionItem {
  level: string
  text: string
}

export interface InstructionsData {
  book?: string
  chapter?: number
  instructions?: InstructionItem[]
  total?: number
  error?: string
}

export interface WritingStyleRule {
  dimension: string
  rule: string
  weight: number
}

export interface StyleCalibrateResult {
  ok: boolean
  rule_count?: number
  rules?: WritingStyleRule[]
  error?: string
}

export interface StyleRulesData {
  ok: boolean
  rule_count?: number
  rules?: WritingStyleRule[]
}

// ── API ──

export const WritingAPI = {
  /** 获取可参考书列表 */
  async getInstructionBooks() {
    return apiGet<{ books?: string[]; genre?: string }>('/api/instructions')
  },

  /** 获取写作指令（指定参考书和章节） */
  async getInstructions(book: string, chapter: number) {
    const params = new URLSearchParams({ book, ch: String(chapter) })
    return apiGet<InstructionsData>(`/api/instructions?${params.toString()}`)
  },

  /** 风格校准 */
  async calibrateStyle(chapterId: number, text: string) {
    return apiPost<StyleCalibrateResult>('/api/style/calibrate', {
      chapter_id: chapterId,
      text,
      version: '',
    })
  },

  /** 获取风格规则列表 */
  async getStyleRules() {
    return apiGet<StyleRulesData>('/api/style/rules')
  },
}