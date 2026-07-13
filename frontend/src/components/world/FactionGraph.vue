<script setup lang="ts">
/**
 * FactionGraph — 势力关系图 (Cytoscape.js)
 *
 * 节点 = 势力（大小=power_level，颜色=type）
 * 边 = 关系（粗细=intensity，颜色=type）
 */
import { ref, onMounted, watch } from 'vue'
import cytoscape from 'cytoscape'
import type { Faction } from '@/types'

const props = defineProps<{
  factions: Faction[]
}>()

const emit = defineEmits<{
  (e: 'select', faction: Faction): void
}>()

const containerRef = ref<HTMLElement | null>(null)
let cy: cytoscape.Core | null = null

const typeColors: Record<string, string> = {
  '神秘组织': '#A78BFA',
  '官方组织': '#38BDF8',
  '帮派': '#F59E0B',
  '军事组织': '#EF4444',
  '宗门': '#22D3EE',
  '帝国': '#818CF8',
  '议会': '#22c55e',
}

function getTypeColor(type?: string): string {
  return typeColors[type || ''] || '#94a3b8'
}

function getThemeColor(alpha?: number): string {
  const rgb = getComputedStyle(document.documentElement).getPropertyValue('--text-rgb').trim() || '248,250,252'
  if (alpha === undefined) return `rgb(${rgb})`
  return `rgba(${rgb},${alpha})`
}

function buildGraph(factions: Faction[]) {
  if (!cy) return

  const nodes = factions.map((fac) => ({
    data: {
      id: fac.id || fac.name,
      name: fac.name,
      type: fac.type || '未知',
      power: fac.state?.power_level ?? 5,
      desc: fac.desc,
      color: getTypeColor(fac.type),
    },
  }))

  // 自动推导关系边：威胁度高的势力之间产生敌对边
  const edges: cytoscape.ElementDefinition[] = []
  for (let i = 0; i < factions.length; i++) {
    for (let j = i + 1; j < factions.length; j++) {
      const a = factions[i]
      const b = factions[j]
      const aThreat = a.state?.threat_level ?? 0.3
      const bThreat = b.state?.threat_level ?? 0.3
      const powerDiff = Math.abs(
        (a.state?.power_level ?? 5) - (b.state?.power_level ?? 5)
      )

      // 高威胁 + 实力接近 → 敌对
      if (aThreat > 0.5 && bThreat > 0.5 && powerDiff <= 3) {
        edges.push({
          data: {
            id: `${a.id || a.name}-${b.id || b.name}`,
            source: a.id || a.name,
            target: b.id || b.name,
            relType: 'hostile',
            intensity: Math.round((aThreat + bThreat) * 5),
          },
        })
      }
      // 实力差距大 → 附庸/贸易
      else if (powerDiff >= 4) {
        const stronger = (a.state?.power_level ?? 5) > (b.state?.power_level ?? 5) ? a : b
        const weaker = stronger === a ? b : a
        edges.push({
          data: {
            id: `${stronger.id || stronger.name}-${weaker.id || weaker.name}`,
            source: stronger.id || stronger.name,
            target: weaker.id || weaker.name,
            relType: 'vassal',
            intensity: powerDiff,
          },
        })
      }
    }
  }

  // 合并用户自定义关系
  for (const fac of factions) {
    if (!fac.relations) continue
    for (const rel of fac.relations) {
      const edgeId = `custom-${fac.id}-${rel.target_id}`
      if (!edges.find((e) => e.data.id === edgeId)) {
        edges.push({
          data: {
            id: edgeId,
            source: fac.id || fac.name,
            target: rel.target_id,
            relType: rel.type,
            intensity: rel.intensity,
          },
        })
      }
    }
  }

  cy.elements().remove()
  cy.add([...nodes, ...edges])
  cy.layout({ name: 'cose', animate: true, padding: 30, nodeRepulsion: 8000, idealEdgeLength: 100 } as cytoscape.LayoutOptions).run()
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
          'width': (ele: cytoscape.NodeSingular) => 30 + (ele.data('power') ?? 5) * 6,
          'height': (ele: cytoscape.NodeSingular) => 30 + (ele.data('power') ?? 5) * 6,
          'label': 'data(name)',
          'color': getThemeColor(),
          'font-size': '12px',
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'border-width': 2,
          'border-color': getThemeColor(0.2),
        },
      },
      {
        selector: 'edge',
        style: {
          'width': (ele: cytoscape.EdgeSingular) => Math.max(1, (ele.data('intensity') ?? 1)),
          'line-color': (ele: cytoscape.EdgeSingular) => {
            const t = ele.data('relType')
            if (t === 'hostile') return '#ef4444'
            if (t === 'ally') return '#22c55e'
            if (t === 'vassal') return '#818CF8'
            if (t === 'trade') return '#F59E0B'
            return '#94a3b8'
          },
          'target-arrow-color': (ele: cytoscape.EdgeSingular) => {
            const t = ele.data('relType')
            if (t === 'hostile') return '#ef4444'
            if (t === 'ally') return '#22c55e'
            if (t === 'vassal') return '#818CF8'
            if (t === 'trade') return '#F59E0B'
            return '#94a3b8'
          },
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'opacity': 0.7,
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
    const fac = props.factions.find((f) => (f.id || f.name) === id)
    if (fac) emit('select', fac)
  })

  buildGraph(props.factions)
}

onMounted(() => {
  initCytoscape()
})

watch(() => props.factions, (newFactions) => {
  if (cy) {
    buildGraph(newFactions)
  } else {
    initCytoscape()
  }
}, { deep: true })
</script>

<template>
  <div class="graph-wrapper">
    <div ref="containerRef" class="faction-graph"></div>

    <!-- 图例 -->
    <div class="graph-legend">
      <div class="legend-title">势力类型</div>
      <div class="legend-item" v-for="(color, type) in typeColors" :key="type">
        <span class="legend-dot" :style="{ background: color }"></span>
        <span>{{ type }}</span>
      </div>
      <div class="legend-divider"></div>
      <div class="legend-title">关系</div>
      <div class="legend-item"><span class="legend-line" style="background:#ef4444"></span>敌对</div>
      <div class="legend-item"><span class="legend-line" style="background:#22c55e"></span>同盟</div>
      <div class="legend-item"><span class="legend-line" style="background:#818CF8"></span>附庸</div>
      <div class="legend-item"><span class="legend-line" style="background:#F59E0B"></span>贸易</div>
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

.faction-graph {
  width: 100%;
  height: 400px;
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
  max-width: 140px;
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
