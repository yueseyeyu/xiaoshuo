<script setup lang="ts">
/**
 * SystemHealthCard — 系统健康指标侧边卡片
 *
 * 从 DashboardView 提取，展示 GPU/VRAM/RAM/CPU 指标条和模型运行状态。
 */
import type { HardwareData, ConfigData } from '@/api/dashboard'

defineProps<{
  hardware: HardwareData | null
  config: ConfigData | null
  llmHealthy: boolean
}>()

function healthClass(pct: number, temp = false): string {
  if (temp) {
    if (pct >= 85) return 'danger'
    if (pct >= 75) return 'warning'
    return 'ok'
  }
  if (pct >= 90) return 'danger'
  if (pct >= 80) return 'warning'
  return 'ok'
}
</script>

<template>
  <div class="side-card">
    <div class="side-card-title">系统健康</div>
    <div class="side-card-body compact">
      <div class="health-list">
        <div class="health-row" v-if="hardware?.gpu_available">
          <span class="health-key">GPU</span>
          <div class="health-bar-wrap">
            <div class="health-bar">
              <span :class="healthClass(hardware?.gpu.temp ?? 0, true)" :style="{ width: (hardware?.gpu.temp || 0) + '%' }" />
            </div>
          </div>
          <span class="health-value">{{ hardware?.gpu.temp || '--' }}°C</span>
        </div>
        <div class="health-row" v-if="hardware?.gpu_available">
          <span class="health-key">显存</span>
          <div class="health-bar-wrap">
            <div class="health-bar">
              <span :class="healthClass(hardware?.gpu.vram_pct ?? 0)" :style="{ width: (hardware?.gpu.vram_pct || 0) + '%' }" />
            </div>
          </div>
          <span class="health-value">{{ hardware?.gpu.vram_pct || '--' }}%</span>
        </div>
        <div class="health-row">
          <span class="health-key">内存</span>
          <div class="health-bar-wrap">
            <div class="health-bar">
              <span :class="healthClass(hardware?.ram.pct ?? 0)" :style="{ width: (hardware?.ram.pct || 0) + '%' }" />
            </div>
          </div>
          <span class="health-value">{{ hardware?.ram.pct || '--' }}%</span>
        </div>
        <div class="health-row">
          <span class="health-key">CPU</span>
          <div class="health-bar-wrap">
            <div class="health-bar">
              <span :class="healthClass(hardware?.cpu.pct ?? 0)" :style="{ width: (hardware?.cpu.pct || 0) + '%' }" />
            </div>
          </div>
          <span class="health-value">{{ Math.round(hardware?.cpu.pct || 0) }}%</span>
        </div>
      </div>
      <div class="model-status">
        <span class="mini-status" :class="{ ok: llmHealthy }" />
        <span>{{ config?.local_model || '本地模型' }}</span>
        <span>{{ llmHealthy ? '运行中' : '离线' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.side-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
}
.side-card-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text);
}
.side-card-body.compact {
  font-size: 12px;
}
.health-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.health-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.health-key {
  width: 36px;
  font-size: 11px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.health-bar-wrap {
  flex: 1;
  height: 6px;
  background: var(--surface-solid);
  border-radius: 3px;
  overflow: hidden;
}
.health-bar {
  height: 100%;
  display: block;
}
.health-bar span {
  display: block;
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.health-bar span.ok { background: var(--success); }
.health-bar span.warning { background: var(--warning); }
.health-bar span.danger { background: var(--danger); }
.health-value {
  width: 44px;
  text-align: right;
  font-size: 11px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.model-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-secondary);
}
.mini-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}
.mini-status.ok {
  background: var(--success);
  box-shadow: 0 0 6px var(--success-rgb);
}
</style>
