/**
 * Creative API — 创意辅助端点
 *
 * 涵盖：作者心智模型、决策直觉引擎、章节目标门控、小说解构、提示词模板
 */

import { apiGet, apiPost } from './client'

// ── 作者心智模型 ──

export interface PresetAuthor {
  name: string
  style: string
  representative_works: string[]
}

export interface AuthorFramework {
  structure?: string
  structure_detail?: string
  pleasure_logic?: string
  pleasure_detail?: string
  rhythm_method?: string
  rhythm_detail?: string
  characterization?: string
  characterization_detail?: string
  conflict_style?: string
  conflict_detail?: string
  worldbuilding?: string
  worldbuilding_detail?: string
}

export interface AuthorDetail {
  name: string
  representative_works: string[]
  framework: AuthorFramework
  signature_techniques: Array<{ technique?: string; name?: string; desc?: string }>
  craft_notes: string[]
}

export interface DecisionOption {
  author: string
  choice: string
  reasoning?: string
  risk?: string
}

export const CreativeAPI = {
  /** 预设作者列表 */
  async getAuthorPresets() {
    return apiGet<{ authors: PresetAuthor[] }>('/api/creative/authors/presets')
  },

  /** 作者详情 */
  async getAuthorDetail(name: string) {
    return apiGet<AuthorDetail>(`/api/creative/authors/${encodeURIComponent(name)}`)
  },

  /** 生成决策选项 */
  async generateDecisionOptions(scenario: string, authors?: string[] | null) {
    return apiPost<{ options: DecisionOption[] }>('/api/creative/decision/options', {
      scenario,
      authors: authors || null,
      context: null,
    })
  },

  /** 记录决策选择 */
  async recordDecision(scenario: string, chosenAuthor: string, allOptions?: unknown) {
    return apiPost('/api/creative/decision/record', {
      scenario,
      chosen_author: chosenAuthor,
      all_options: allOptions || null,
    })
  },

  // ── 章节目标门控 ──

  /** 验证章节目标 */
  async verifyGoalGate(body: {
    chapter_text: string
    chapter_num: number
    target_chars?: [number, number]
    min_pleasure_points?: number
    emotion_curve_template?: string
    require_canon_check?: boolean
    min_s3_score?: number
    context?: unknown
  }) {
    return apiPost<{
      result: string
      conditions: Array<{
        name?: string
        condition?: string
        passed: boolean
        detail?: string
        suggestion?: string
      }>
      iteration?: number
    }>('/api/creative/goal-gate/verify', body)
  },

  /** 目标门控历史 */
  async getGoalGateHistory(limit = 10) {
    return apiGet<{ records: unknown[] }>(`/api/creative/goal-gate/history?limit=${limit}`)
  },

  // ── 小说解构 ──

  /** 可解构的书列表 */
  async getDeconstructableBooks(genre?: string) {
    const q = genre ? `?genre=${encodeURIComponent(genre)}` : ''
    return apiGet<{ books: Array<{ title: string; file_path: string; size_kb: number; genre: string }> }>(
      `/api/creative/deconstruct/books${q}`
    )
  },

  /** 执行解构 */
  async runDeconstruction(body: { text?: string; file_path?: string; max_chapters?: number | null }) {
    return apiPost<{
      genre_tags: Record<string, unknown>
      structure: Record<string, unknown>
      characters: Record<string, unknown>
      borrowable: Record<string, unknown>
      warnings: Record<string, unknown>
      metadata: Record<string, unknown>
    }>('/api/creative/deconstruct', body)
  },

  // ── 提示词模板 ──

  /** 模板列表 + 缓存统计 */
  async getPromptTemplates() {
    return apiGet<{
      templates: Array<{
        task_type: string
        description: string
        system_prompt_length: number
        system_prompt_hash: string
        system_prompt_preview: string
      }>
      cache_stats: Record<string, {
        calls: number
        estimated_cache_hit_rate: number
      }>
    }>('/api/creative/prompt-templates')
  },

  /** 模板详情 */
  async getPromptTemplateDetail(taskType: string) {
    return apiGet<{
      task_type: string
      description: string
      system_prompt: string
      user_template: string
      system_prompt_hash: string
    }>(`/api/creative/prompt-templates/${encodeURIComponent(taskType)}`)
  },

  /** 成本节省 */
  async getCostSavings() {
    return apiGet<{ estimated_savings: number }>('/api/creative/prompt-templates/cost-savings')
  },

  /** 合规扫描 — AI 指纹词检测 */
  async complianceScan(text: string) {
    return apiGet<{
      ok: boolean
      risk_level: string
      total_count: number
      high_risk_count: number
      by_category: Record<string, number>
      high_risk_hits: string[]
      ai_rate: number
      ai_rate_level: string
      ai_rate_passed: boolean
      ai_rate_recommendation: string
    }>(`/api/compliance/scan?text=${encodeURIComponent(text)}`)
  },

  /** 渲染提示词模板预览 */
  async renderPromptTemplate(taskType: string, context: Record<string, unknown>) {
    return apiPost<{ system_prompt: string; user_prompt: string }>(
      '/api/creative/prompt-templates/render',
      { task_type: taskType, context },
    )
  },
}
