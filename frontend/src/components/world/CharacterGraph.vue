<script setup lang="ts">
/**
 * CharacterGraph — 角色关系图 (Cytoscape.js)
 *
 * 节点 = 角色（大小=influence，颜色=所属势力/角色类型）
 * 边 = 关系（师徒/敌对/同伴等）
 */
import { ref, onMounted, watch } from 'vue'
import cytoscape from 'cytoscape'
import type { Character } from '@/types'

const props = defineProps<{
  characters: Character[]
}>()

const emit = defineEmits<{
  (e: 'select', character: Character): void
}>()

const containerRef = ref<HTMLElement | null>(null)
let cy: cytoscape.Core | null = null

const roleColors: Record<string, string> = {
  '主角': '#38BDF8',
  '女主': '#22c55e',
  '导师': '#818CF8',
  '反派': '#EF4444',
  '配角': '#F59E0B',
}

function getRoleColor(role?: string): string {
  return roleColors[role || ''] || '#94a3b8'
}

function buildGraph(characters: Character[]) {
  if (!cy) return

  const nodes = characters.map((char) => ({
    data: {
      id: char.name,
      name: char.name,
      role: char.role || '配角',
      health: char.dynamic_state?.health ?? 1.0,
      ability: char.ability || '',
      color: getRoleColor(char.role),
    },
  }))

  // 自动推导关系边
  const edges: cytoscape.ElementDefinition[] = []
  for (let i = 0; i < characters.length; i++) {
    for (let j = i + 1; j < characters.length; j++) {
      const a = characters[i]
      const b = characters[j]
      const aRole = a.role || ''
      const bRole = b.role || ''

      // 主角 ↔ 女主 = 同伴
      if ((aRole === '主角' && bRole === '女主') || (aRole === '女主' && bRole === '主角')) {
        edges.push({
          data: {
            id: `${a.name}-${b.name}`,
            source: a.name,
            target: b.name,
            relType: 'companion',
            intensity: 8,
          },
        })
      }
      // 主角/女主 ↔ 导师 = 师徒
      else if (
        (aRole === '导师' && ['主角', '女主'].includes(bRole)) ||
        (bRole === '导师' && ['主角', '女主'].includes(aRole))
      ) {
        const mentor = aRole === '导师' ? a : b
        const student = mentor === a ? b : a
        edges.push({
          data: {
            id: `${mentor.name}-${student.name}`,
            source: mentor.name,
            target: student.name,
            relType: 'mentor',
            intensity: 6,
          },
        })
      }
      // 主角 ↔ 反派 = 敌对
      else if (
        (aRole === '主角' && bRole === '反派') ||
        (aRole === '反派' && bRole === '主角')
      ) {
        edges.push({
          data: {
            id: `${a.name}-${b.name}`,
            source: a.name,
            target: b.name,
            relType: 'rivalry',
            intensity: 9,
          },
        })
      }
    }
  }

  cy.elements().remove()
  cy.add([...nodes, ...edges])
  cy.layout({ name: 'cose', animate: true, padding: 30, nodeRepulsion: 6000, idealEdgeLength: 80 } as cytoscape.LayoutOptions).run()
}

// ── 缩放控制 ──
function zoomIn() { cy?.zoom({ level: cy.zoom() * 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }) }
function zoomOut() { cy?.zoom({ level: cy.zoom() / 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }) }
function fitGraph() { cy?.fit(undefined, 40) }

function initCytoscape() {
  if (!containerRef.value) return

  cy = cytoscape({
    container: containerRef.value,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(color)',
          'width': (ele: cytoscape.NodeSingular) => {
            const health = ele.data('health') ?? 1.0
            return 24 + health * 24
          },
          'height': (ele: cytoscape.NodeSingular) => {
            const health = ele.data('health') ?? 1.0
            return 24 + health * 24
          },
          'label': 'data(name)',
          'color': '#f8fafc',
          'font-size': '12px',
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'border-width': 2,
          'border-color': 'rgba(255,255,255,0.2)',
        },
      },
      {
        selector: 'edge',
        style: {
          'width': (ele: cytoscape.EdgeSingular) => Math.max(1, (ele.data('intensity') ?? 1) * 0.8),
          'line-color': (ele: cytoscape.EdgeSingular) => {
            const t = ele.data('relType')
            if (t === 'rivalry') return '#ef4444'
            if (t === 'companion') return '#22c55e'
            if (t === 'mentor') return '#818CF8'
            return '#94a3b8'
          },
          'target-arrow-color': (ele: cytoscape.EdgeSingular) => {
            const t = ele.data('relType')
            if (t === 'rivalry') return '#ef4444'
            if (t === 'companion') return '#22c55e'
            if (t === 'mentor') return '#818CF8'
            return '#94a3b8'
          },
          'target-arrow-shape': (ele: cytoscape.EdgeSingular) => {
            const t = ele.data('relType')
            if (t === 'mentor') return 'triangle'
            return 'none'
          },
          'curve-style': 'bezier',
          'opacity': 0.7,
          'line-style': (ele: cytoscape.EdgeSingular) => {
            const t = ele.data('relType')
            if (t === 'rivalry') return 'dashed'
            return 'solid'
          },
        },
      },
      {
        selector: 'node:selected',
        style: {
          'border-width': 3,
          'border-color': '#38BDF8',
        },
      },
    ] as unknown as cytoscape.StylesheetCSS[],
    minZoom: 0.3,
    maxZoom: 3,
  })

  // 节点点击 → 通知父组件
  cy.on('tap', 'node', (evt) => {
    const id = evt.target.id()
    const char = props.characters.find((c) => c.name === id)
    if (char) emit('select', char)
  })

  buildGraph(props.characters)
}

onMounted(() => {
  initCytoscape()
})

watch(() => props.characters, (newChars) => {
  if (cy) {
    buildGraph(newChars)
  } else {
    initCytoscape()
  }
}, { deep: true })
</script>

<template>
  <div class="graph-wrapper">
    <div ref="containerRef" class="character-graph"></div>

    <!-- 图例 -->
    <div class="graph-legend">
      <div class="legend-title">角色类型</div>
      <div class="legend-item" v-for="(color, role) in roleColors" :key="role">
        <span class="legend-dot" :style="{ background: color }"></span>
        <span>{{ role }}</span>
      </div>
      <div class="legend-divider"></div>
      <div class="legend-title">关系</div>
      <div class="legend-item"><span class="legend-line" style="background:#22c55e"></span>同伴</div>
      <div class="legend-item"><span class="legend-line" style="background:#818CF8"></span>师徒</div>
      <div class="legend-item"><span class="legend-line" style="background:#ef4444"></span>敌对</div>
    </div>

    <!-- 缩放控制 -->
    <div class="graph-controls">
      <button class="graph-ctrl-btn" title="放大" @click="zoomIn">+</button>
      <button class="graph-ctrl-btn" title="缩小" @click="zoomOut">−</button>
      <button class="graph-ctrl-btn" title="适应" @click="fitGraph">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h6M4 4v6M20 4h-6M20 4v6M4 20h6M4 20v-6M20 20h-6M20 20v-6"/></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.graph-wrapper {
  position: relative;
}

.character-graph {
  width: 100%;
  height: 350px;
  background: var(--surface-faint);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.graph-legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 11px;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-width: 120px;
  z-index: 5;
}
.legend-title { font-weight: 600; color: var(--text); font-size: 10px; text-transform: uppercase; margin-bottom: 2px; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.legend-line { width: 16px; height: 2px; border-radius: 1px; flex-shrink: 0; }
.legend-divider { height: 1px; background: var(--border); margin: 4px 0; }

.graph-controls {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 5;
}
.graph-ctrl-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface-solid);
  color: var(--text-secondary);
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  padding: 0;
}
.graph-ctrl-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(var(--accent-rgb), 0.08);
}
</style>
