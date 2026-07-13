<script setup lang="ts">
import { computed } from 'vue'

/**
 * MiniLineChart — 轻量级 SVG 折线图
 * 用于硬件监控趋势、日志耗时分布等场景。
 */
interface Point { label: string; value: number }

const props = defineProps<{
  data: Point[]
  color?: string
  height?: number
  max?: number
}>()

const padding = 4
const width = 100
const height = props.height || 32

const computedMax = computed(() => {
  const m = props.max ?? Math.max(...props.data.map((d) => d.value), 1)
  return m
})

function x(i: number) {
  if (props.data.length <= 1) return padding
  return padding + (i / (props.data.length - 1)) * (width - padding * 2)
}

function y(v: number) {
  return height - padding - (v / computedMax.value) * (height - padding * 2)
}

const path = computed(() => {
  return props.data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(d.value)}`).join(' ')
})

const areaPath = computed(() => {
  if (props.data.length === 0) return ''
  const top = props.data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(d.value)}`).join(' ')
  return `${top} L ${x(props.data.length - 1)} ${height - padding} L ${x(0)} ${height - padding} Z`
})
</script>

<template>
  <svg class="mini-line-chart" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none">
    <path class="mini-line-area" :d="areaPath" :fill="color || 'var(--accent)'" fill-opacity="0.15" />
    <path class="mini-line" :d="path" :stroke="color || 'var(--accent)'" fill="none" stroke-width="1.5" vector-effect="non-scaling-stroke" />
  </svg>
</template>

<style scoped>
.mini-line-chart {
  width: 100%;
  height: 100%;
  overflow: visible;
}
.mini-line {
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>
