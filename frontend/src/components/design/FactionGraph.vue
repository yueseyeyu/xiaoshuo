<script setup lang="ts">
/**
 * FactionGraph — 设计页势力关系图（Cytoscape）
 *
 * 特性：
 * - 势力节点按类型着色，首节点作为主势力放大高亮
 * - 主势力与其余势力自动连线
 * - 点击节点触发编辑
 */
import { ref, watch, onMounted, onUnmounted } from 'vue'
import cytoscape from 'cytoscape'
import type { Faction } from '@/types'

const props = defineProps<{
  factions: Faction[]
}>()

const emit = defineEmits<{
  (e: 'edit-faction', index: number): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let cy: cytoscape.Core | null = null

const typeColors: Record<string, string> = {
  宗门: '#22c55e',
  帝国: '#f59e0b',
  组织: '#3b82f6',
  部落: '#8b5cf6',
  联盟: '#06b6d4',
  势力: '#64748b',
}

function getFactionColor(type?: string): string {
  return typeColors[type || ''] || typeColors['势力']
}

function getThemeColor(alpha?: number): string {
  const rgb = getComputedStyle(document.documentElement).getPropertyValue('--text-rgb').trim() || '248,250,252'
  if (alpha === undefined) return `rgb(${rgb})`
  return `rgba(${rgb},${alpha})`
}

function computePositions(n: number) {
  if (n === 0) return []
  const cx = 0
  const cy = 0
  if (n === 1) return [{ x: cx, y: cy }]
  if (n === 2) return [{ x: cx - 80, y: cy }, { x: cx + 80, y: cy }]
  const radius = Math.min(160, 60 + n * 18)
  return Array.from({ length: n }, (_, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2
    return { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius }
  })
}

function buildGraph() {
  if (cy) {
    cy.destroy()
    cy = null
  }
  if (!containerRef.value || props.factions.length === 0) return

  const positions = computePositions(props.factions.length)
  const nodes = props.factions.map((f, i) => ({
    data: {
      id: `fac-${i}`,
      index: i,
      name: f.name,
      type: f.type,
      color: getFactionColor(f.type),
      isMain: i === 0,
    },
    position: positions[i],
  }))

  const edges: cytoscape.ElementDefinition[] = []
  if (props.factions.length > 1) {
    for (let i = 1; i < props.factions.length; i++) {
      edges.push({
        data: {
          id: `edge-${i}`,
          source: 'fac-0',
          target: `fac-${i}`,
        },
      })
    }
  }

  cy = cytoscape({
    container: containerRef.value,
    elements: [...nodes, ...edges],
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(color)',
          'width': (ele: cytoscape.NodeSingular) => (ele.data('isMain') ? 44 : 36),
          'height': (ele: cytoscape.NodeSingular) => (ele.data('isMain') ? 44 : 36),
          'label': 'data(name)',
          'color': getThemeColor(),
          'font-size': '12px',
          'text-valign': 'bottom',
          'text-margin-y': 6,
          'border-width': (ele: cytoscape.NodeSingular) => (ele.data('isMain') ? 3 : 2),
          'border-color': (ele: cytoscape.NodeSingular) => (ele.data('isMain') ? 'var(--accent)' : getThemeColor(0.25)),
          'text-max-width': '80px',
          'text-wrap': 'wrap',
        },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': getThemeColor(0.15),
          'target-arrow-shape': 'triangle',
          'target-arrow-color': getThemeColor(0.25),
          'curve-style': 'bezier',
        },
      },
    ],
    layout: { name: 'preset' },
    minZoom: 0.5,
    maxZoom: 2,
    wheelSensitivity: 0.3,
  })

  cy.on('tap', 'node', (evt) => {
    const idx = evt.target.data('index') as number
    emit('edit-faction', idx)
  })
}

watch(() => props.factions, buildGraph, { deep: true })

onMounted(buildGraph)
onUnmounted(() => {
  if (cy) {
    cy.destroy()
    cy = null
  }
})
</script>

<template>
  <div ref="containerRef" class="faction-graph" />
</template>

<style scoped>
.faction-graph {
  width: 100%;
  height: 280px;
  background: var(--surface);
  border-radius: 8px;
}
</style>
