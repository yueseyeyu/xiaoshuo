/**
 * 世界状态 API — 对接后端世界推演端点
 */

import { apiGet, apiPut, apiPost } from './client'
import type { WorldState, WorldSnapshot, SimulationEvent } from '@/types'

export const WorldAPI = {
  /** 获取当前世界状态 */
  async getState(projectId: string) {
    return apiGet<WorldState>(`/api/projects/${projectId}/world_state`)
  },

  /** 更新世界状态 */
  async updateState(projectId: string, state: Partial<WorldState>) {
    return apiPut<{ ok: boolean; world_state: WorldState }>(`/api/projects/${projectId}/world_state`, state)
  },

  /** 保存快照 — 调用专用 POST /world_state/snapshot 端点 */
  async saveSnapshot(projectId: string, chapter: number) {
    return apiPost<{ ok: boolean; snapshot: WorldSnapshot }>(
      `/api/projects/${projectId}/world_state/snapshot`, { chapter }
    )
  },

  /** 获取推演事件 — 调用专用 GET /world_state/events 端点 */
  async getEvents(projectId: string, chapter?: number) {
    const q = chapter !== undefined ? `?chapter=${chapter}` : ''
    return apiGet<{ events: SimulationEvent[] }>(
      `/api/projects/${projectId}/world_state/events${q}`
    )
  },

  /** 获取世界状态快照对比 */
  async getDiff(projectId: string, fromChapter: number, toChapter: number) {
    return apiGet<{
      from: WorldSnapshot
      to: WorldSnapshot
      changes: Array<{ target_type: string; target_id: string; field: string; from: number; to: number; delta: number }>
    }>(`/api/projects/${projectId}/world_state/diff?from=${fromChapter}&to=${toChapter}`)
  },

  /**
   * 启动推演 — 通过 fetch + ReadableStream 接收 SSE 流
   *
   * 因为后端使用 POST 方法，不能使用 EventSource（仅支持 GET），
   * 改用 fetch + ReadableStream 解析 SSE 数据。
   */
  async startSimulation(
    projectId: string,
    fromChapter: number,
    toChapter: number,
    handlers: SimulationHandlers
  ): Promise<() => void> {
    const controller = new AbortController()

    const fetchPromise = fetch(`/api/projects/${projectId}/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_chapter: fromChapter, to_chapter: toChapter }),
      signal: controller.signal,
    })

    fetchPromise.then(async (resp) => {
      if (!resp.ok) {
        handlers.onError?.(`HTTP ${resp.status}`)
        return
      }

      const reader = resp.body?.getReader()
      if (!reader) {
        handlers.onError?.('无法读取响应流')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // 解析 SSE 数据块（以 \n\n 分隔）
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''

          for (const part of parts) {
            const lines = part.split('\n')
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6))
                  if (data.status === 'complete') {
                    handlers.onComplete?.(data)
                  } else if (data.error) {
                    handlers.onError?.(data.error)
                  } else if (data.status === 'started' || data.status === 'round_complete') {
                    handlers.onProgress?.(data)
                  } else {
                    handlers.onEvent?.(data)
                  }
                } catch {
                  // 忽略解析失败
                }
              }
            }
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          handlers.onError?.(err instanceof Error ? err.message : String(err))
        }
      }
    }).catch((err) => {
      if (!controller.signal.aborted) {
        handlers.onError?.(err instanceof Error ? err.message : String(err))
      }
    })

    // 返回取消函数
    return () => controller.abort()
  },

  /**
   * 导出推演事件到大纲草稿 (v8.6 WSE 深化)
   *
   * 将指定章节范围内的推演事件 + 世界状态快照转化为结构化大纲草稿。
   */
  async exportToOutline(
    projectId: string,
    fromChapter: number,
    toChapter: number,
    genre: string = '末世',
  ) {
    return apiPost<{
      project_id: string
      from_chapter: number
      to_chapter: number
      world_context: string
      chapter_drafts: Array<{
        chapter: number
        events: SimulationEvent[]
        faction_summary: string
        character_summary: string
        suggested_outline: string
      }>
    }>(`/api/projects/${projectId}/world_state/export_outline`, {
      from_chapter: fromChapter,
      to_chapter: toChapter,
      genre,
    })
  },
}

/** 推演事件回调 */
export interface SimulationHandlers {
  onEvent?: (event: SimulationEvent) => void
  onProgress?: (data: { status: string; chapter?: number; round?: number; total_rounds?: number }) => void
  onComplete?: (data: { status: string; from_chapter: number; to_chapter: number }) => void
  onError?: (error: string) => void
}
