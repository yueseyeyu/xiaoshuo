<script setup lang="ts">
/**
 * TechniqueMiniList — 技法卡片折叠列表（卡片内嵌版）
 * 管理展开/折叠状态，emit apply-technique 事件
 */
import { ref } from 'vue'

interface TechniqueCard {
  title?: string
  content?: string
  category?: string
  id?: string
}

const props = defineProps<{
  techByCat: Record<string, TechniqueCard[]>
}>()

const emit = defineEmits<{
  (e: 'apply-technique', name: string): void
}>()

const expandedCats = ref<Set<string>>(new Set())

function toggleCat(cat: string) {
  if (expandedCats.value.has(cat)) {
    expandedCats.value.delete(cat)
  } else {
    expandedCats.value.add(cat)
  }
  expandedCats.value = new Set(expandedCats.value)
}
</script>

<template>
  <div class="tech-mini-list">
    <div v-for="(items, cat) in techByCat" :key="cat" class="tech-cat-group" :class="{ expanded: expandedCats.has(cat) }">
      <div class="tech-cat-header" @click.stop="toggleCat(cat)">
        <span class="tech-cat-toggle">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="9 18 15 12 9 6"/></svg>
        </span>
        <span class="tech-cat-name">{{ cat }}</span>
        <span class="tech-cat-count">{{ items.length }} 张</span>
      </div>
      <div v-if="expandedCats.has(cat)" class="tech-cat-body">
        <div v-for="c in items.slice(0, 5)" :key="c.title || c.id" class="tech-item">
          <div class="tech-item-title">{{ c.title || c.id || '?' }}</div>
          <div class="tech-item-desc">{{ (c.content || '').substring(0, 120) }}{{ c.content && c.content.length > 120 ? '...' : '' }}</div>
          <button class="tech-apply-btn" @click.stop="emit('apply-technique', c.title || c.id || '')">应用到大纲</button>
        </div>
        <div v-if="items.length > 5" class="tech-more">还有 {{ items.length - 5 }} 张，点击卡片查看全部</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tech-mini-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tech-cat-group {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.15s;
}
.tech-cat-group:hover {
  border-color: var(--accent);
}
.tech-cat-group.expanded {
  border-color: var(--accent);
  box-shadow: 0 2px 8px rgba(var(--accent-rgb), 0.08);
}
.tech-cat-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  cursor: pointer;
  font-size: 12px;
  background: var(--surface-faint);
  transition: all 0.15s;
}
.tech-cat-header:hover { background: rgba(var(--accent-rgb), 0.08); }
.tech-cat-toggle {
  color: var(--accent);
  transition: transform 0.15s;
  display: flex;
}
.tech-cat-group.expanded .tech-cat-toggle { transform: rotate(90deg); }
.tech-cat-name { flex: 1; font-weight: 600; color: var(--text); }
.tech-cat-count {
  font-size: 10px;
  font-weight: 600;
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(var(--accent-rgb), 0.1);
}
.tech-cat-body {
  padding: 6px 8px;
  background: var(--surface-solid);
  border-top: 1px solid var(--border);
}
.tech-item { padding: 6px 0; border-bottom: 1px solid var(--border); }
.tech-item:last-child { border-bottom: none; }
.tech-item-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; color: var(--text); }
.tech-item-desc { font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; line-height: 1.4; }
.tech-apply-btn {
  font-size: 11px;
  padding: 3px 8px;
  border: 1px solid var(--accent);
  border-radius: 5px;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  transition: all 0.15s;
  font-weight: 500;
}
.tech-apply-btn:hover { background: var(--accent); color: var(--bg); }
.tech-more { font-size: 11px; color: var(--text-muted); text-align: center; padding: 6px 0; }
</style>
