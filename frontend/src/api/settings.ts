/**
 * SettingsAPI — 用户设置后端同步
 * 以扁平键值对形式读写后端 data/user_settings.json
 */
import { apiRequest } from './client'

export type SettingsMap = Record<string, string | number | boolean | null>

export const SettingsAPI = {
  async get(): Promise<{ ok: boolean; data?: SettingsMap; error?: string }> {
    return apiRequest<SettingsMap>('/api/settings')
  },

  async save(settings: SettingsMap): Promise<{ ok: boolean; data?: Record<string, unknown>; error?: string }> {
    return apiRequest<Record<string, unknown>>('/api/settings', { method: 'POST', body: settings })
  },
}
