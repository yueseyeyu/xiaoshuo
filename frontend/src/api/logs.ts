/**
 * Logs API — 日志端点
 * 对接 /api/logs、/api/logs/dates 端点
 */

import { apiGet } from './client'

// ── 类型 ──

export interface LogEntry {
  time?: string
  method?: string
  path?: string
  status?: number
  elapsed?: number
  detail?: Record<string, unknown>
}

export interface LogsData {
  entries?: LogEntry[]
  total?: number
}

// ── API ──

export const LogsAPI = {
  /** 获取日志列表 */
  async getLogs(params: URLSearchParams) {
    return apiGet<LogsData>(`/api/logs?${params.toString()}`)
  },

  /** 获取日志日期列表 */
  async getDates() {
    return apiGet<Record<string, string[]>>('/api/logs/dates')
  },
}