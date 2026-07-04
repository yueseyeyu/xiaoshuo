/**
 * API 客户端 — 统一 HTTP 请求封装
 *
 * 所有请求通过 Vite dev server 代理到 FastAPI (localhost:8089)
 */

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<{ ok: boolean; data?: T; error?: string }> {
  try {
    const init: RequestInit = {
      method: options.method ?? 'GET',
      headers: { 'Content-Type': 'application/json' },
    }
    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body)
    }
    const resp = await fetch(path, init)
    if (!resp.ok) {
      const text = await resp.text().catch(() => '')
      return { ok: false, error: `HTTP ${resp.status}: ${text}` }
    }
    const data = await resp.json() as T
    return { ok: true, data }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

export function apiGet<T>(path: string) {
  return apiRequest<T>(path)
}

export function apiPost<T>(path: string, body?: unknown) {
  return apiRequest<T>(path, { method: 'POST', body })
}

export function apiPut<T>(path: string, body?: unknown) {
  return apiRequest<T>(path, { method: 'PUT', body })
}

export function apiDelete<T>(path: string) {
  return apiRequest<T>(path, { method: 'DELETE' })
}
