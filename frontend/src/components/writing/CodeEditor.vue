<script setup lang="ts">
/**
 * CodeEditor — 基于 CodeMirror 6 的写作编辑器
 *
 * 特性：
 * - v-model 双向绑定
 * - 自动换行
 * - Tab 插入缩进（默认 \t）
 * - 撤销/重做
 * - 自定义主题适配亮/暗模式
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue'
import { EditorView, keymap, placeholder as cmPlaceholder } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'

const props = defineProps<{
  modelValue: string
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'input'): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const viewRef = shallowRef<EditorView | null>(null)

function getThemeExtension() {
  return EditorView.theme({
    '&': {
      backgroundColor: 'var(--surface-solid)',
      color: 'var(--text)',
      fontSize: '15px',
      lineHeight: '1.8',
      height: '100%',
    },
    '.cm-content': {
      padding: '16px',
      caretColor: 'var(--accent)',
      fontFamily: 'inherit',
    },
    '.cm-cursor': {
      borderLeftColor: 'var(--accent)',
    },
    '.cm-gutters': {
      backgroundColor: 'var(--surface)',
      color: 'var(--text-secondary)',
      borderRight: '1px solid var(--border)',
      fontSize: '12px',
    },
    '.cm-activeLine': {
      backgroundColor: 'rgba(var(--accent-rgb), 0.04)',
    },
    '.cm-activeLineGutter': {
      backgroundColor: 'rgba(var(--accent-rgb), 0.08)',
    },
    '.cm-selectionBackground': {
      backgroundColor: 'rgba(var(--accent-rgb), 0.2)',
    },
    '.cm-focused .cm-selectionBackground': {
      backgroundColor: 'rgba(var(--accent-rgb), 0.25)',
    },
    '.cm-placeholder': {
      color: 'var(--text-muted)',
    },
  }, { dark: true })
}

function createState(value: string) {
  const extensions = [
    history(),
    EditorView.lineWrapping,
    getThemeExtension(),
    keymap.of([
      ...defaultKeymap,
      ...historyKeymap,
      {
        key: 'Tab',
        preventDefault: true,
        run: (view: EditorView) => {
          view.dispatch(view.state.replaceSelection('\t'))
          return true
        },
      },
    ]),
    EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        const value = update.state.doc.toString()
        emit('update:modelValue', value)
        emit('input')
      }
    }),
  ]

  if (props.placeholder) {
    extensions.push(cmPlaceholder(props.placeholder))
  }

  return EditorState.create({
    doc: value,
    extensions,
  })
}

onMounted(() => {
  if (!containerRef.value) return
  const view = new EditorView({
    state: createState(props.modelValue),
    parent: containerRef.value,
  })
  viewRef.value = view
})

onUnmounted(() => {
  viewRef.value?.destroy()
  viewRef.value = null
})

watch(() => props.modelValue, (newValue) => {
  const view = viewRef.value
  if (!view) return
  const current = view.state.doc.toString()
  if (newValue === current) return
  view.dispatch({
    changes: { from: 0, to: current.length, insert: newValue },
  })
})

watch(() => props.placeholder, () => {
  const view = viewRef.value
  if (!view) return
  view.setState(createState(props.modelValue))
})
</script>

<template>
  <div ref="containerRef" class="code-editor" />
</template>

<style scoped>
.code-editor {
  flex: 1;
  overflow: hidden;
  background: var(--surface-solid);
}
.code-editor :deep(.cm-editor) {
  height: 100%;
}
.code-editor :deep(.cm-scroller) {
  font-family: inherit;
}
.code-editor.focus-editor :deep(.cm-content) {
  font-size: 17px;
  line-height: 1.9;
  padding: 40px 8vw;
}
</style>
