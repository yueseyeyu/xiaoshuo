<script setup lang="ts">
/**
 * KpiCard — 统一 KPI 卡片组件
 *
 * 用法：
 * <KpiCard icon="M12 2L2 7l10 5..." color="indigo" value="53" label="已入库书籍" />
 */
defineProps<{
  icon: string
  value: string | number
  label: string
  color?: 'indigo' | 'violet' | 'amber' | 'emerald' | 'accent' | string
  suffix?: string
}>()

const colorMap: Record<string, string> = {
  indigo: 'var(--indigo)',
  violet: 'var(--violet)',
  amber: 'var(--amber)',
  emerald: 'var(--emerald)',
  accent: 'var(--accent)',
}
</script>

<template>
  <div class="kpi-card" :style="{ '--kpi-color': colorMap[color || 'accent'] || (color || 'var(--accent)') }">
    <div class="kpi-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path :d="icon" />
      </svg>
    </div>
    <div class="kpi-value">{{ value }}<span v-if="suffix" class="kpi-suffix">{{ suffix }}</span></div>
    <div class="kpi-label">{{ label }}</div>
  </div>
</template>

<style scoped>
.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  justify-content: center;
  min-height: 0;
  padding: 16px;
  background: linear-gradient(180deg, rgba(var(--text-rgb), 0.05) 0%, var(--surface) 100%);
  border: 1px solid rgba(var(--text-rgb), 0.12);
  border-left: 3px solid var(--kpi-color);
  border-radius: 16px;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.kpi-card:hover {
  border-color: rgba(var(--text-rgb), 0.16);
  background: linear-gradient(180deg, rgba(var(--text-rgb), 0.06) 0%, var(--surface-hover) 100%);
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14);
}

.kpi-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--kpi-color) 12%, transparent);
  color: var(--kpi-color);
  border: 1px solid rgba(var(--text-rgb), 0.08);
}

.kpi-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  color: var(--kpi-color);
}

.kpi-suffix {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-left: 3px;
}

.kpi-label {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
