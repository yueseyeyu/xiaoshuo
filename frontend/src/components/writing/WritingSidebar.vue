<script setup lang="ts">
/**
 * WritingSidebar — 写作页右侧参考面板（7 个标签页）
 *
 * 标签：细纲 / 角色 / 设定 / 门控 / 心智 / 风格 / AI
 * 从 WritingView 提取，管理自身的 API 调用和局部状态。
 */
import { ref, computed, onMounted } from 'vue'
import { useUiStore } from '@/stores/ui'
import { CreativeAPI, type PresetAuthor, type AuthorDetail, type DecisionOption } from '@/api/creative'
import { WritingAPI, type WritingStyleRule } from '@/api/writing'
import type { Character, SkeletonChapter, Volume, Project } from '@/types'

const props = defineProps<{
  chapterContent: string
  currentChapter: number
  totalChapters: number
  projectCharacters: Character[]
  skeletonChapters: SkeletonChapter[]
  skeletonVolumes: Volume[]
  currentProject: Project | null
}>()

const uiStore = useUiStore()

// ── 标签页 ──
const sidebarTab = ref<'outline' | 'characters' | 'world' | 'goal-gate' | 'author-mind' | 'style' | 'ai'>('outline')

// ── 逐章指令 ──
const instrBooks = ref<string[]>([])
const instrSelectedBook = ref('')
const instrChapterInput = ref(1)
const instrItems = ref<Array<{ level: string; text: string }>>([])
const instrLoading = ref(false)

// ── 目标门控 ──
interface GoalGateCondition {
  name?: string
  condition?: string
  passed: boolean
  detail?: string
  suggestion?: string
}
interface GoalGateResult {
  result: string
  conditions: GoalGateCondition[]
  iteration?: number
}
const goalGateResult = ref<GoalGateResult | null>(null)
const goalGateLoading = ref(false)

// ── 作者心智 ──
const presetAuthors = ref<PresetAuthor[]>([])
const selectedAuthorName = ref<string | null>(null)
const authorDetail = ref<AuthorDetail | null>(null)
const authorDetailLoading = ref(false)
const decisionScenario = ref('')
const decisionOptions = ref<DecisionOption[]>([])
const decisionLoading = ref(false)
const chosenDecisionIdx = ref<number | null>(null)

// ── 风格校准 ──
const styleRules = ref<WritingStyleRule[]>([])
const styleStatus = ref('')
const styleCalibrating = ref(false)

// ── 计算属性 ──
const volSize = 60
const currentVolIndex = computed(() => Math.floor((props.currentChapter - 1) / volSize))
const currentVolTitle = computed(() => {
  const v = props.skeletonVolumes[currentVolIndex.value]
  return v ? `${v.title} · ${v.subtitle || ''}` : `第${currentVolIndex.value + 1}卷`
})

const currentSegment = computed(() => {
  const segIdx = Math.floor((props.currentChapter - 1) / 10)
  return props.skeletonChapters[segIdx] || null
})

// ── 逐章指令 ──
async function loadInstrBooks() {
  const res = await WritingAPI.getInstructionBooks()
  if (res.ok && res.data?.books) {
    instrBooks.value = res.data.books
  }
}

async function loadInstructions() {
  if (!instrSelectedBook.value) {
    uiStore.showToast('请先选择参考书')
    return
  }
  instrLoading.value = true
  const res = await WritingAPI.getInstructions(instrSelectedBook.value, instrChapterInput.value)
  if (res.ok && res.data?.instructions && Array.isArray(res.data.instructions)) {
    instrItems.value = res.data.instructions
  } else {
    instrItems.value = []
    uiStore.showToast('未找到指令或加载失败')
  }
  instrLoading.value = false
}

// ── 目标门控 ──
async function verifyGoalGate() {
  const text = props.chapterContent || ''
  if (text.trim().length < 100) {
    uiStore.showToast('章节内容太少，至少需要 100 字', 'error')
    return
  }
  goalGateLoading.value = true
  const res = await CreativeAPI.verifyGoalGate({
    chapter_text: text,
    chapter_num: props.currentChapter,
    target_chars: [2000, 5000],
    min_pleasure_points: 1,
    emotion_curve_template: 'rising',
    require_canon_check: false,
    min_s3_score: 0,
    context: null,
  })
  goalGateLoading.value = false
  if (res.ok && res.data) {
    goalGateResult.value = res.data as GoalGateResult
  } else {
    uiStore.showToast('目标验证失败: ' + (res.error || '未知错误'), 'error')
  }
}

// ── 作者心智 ──
async function loadPresetAuthors() {
  const res = await CreativeAPI.getAuthorPresets()
  if (res.ok && res.data) {
    presetAuthors.value = res.data.authors || []
  }
}

async function selectAuthor(name: string) {
  selectedAuthorName.value = name
  authorDetail.value = null
  authorDetailLoading.value = true
  const res = await CreativeAPI.getAuthorDetail(name)
  authorDetailLoading.value = false
  if (res.ok && res.data) {
    authorDetail.value = res.data
  }
}

async function runDecisionEngine() {
  const scenario = decisionScenario.value.trim()
  if (!scenario) {
    uiStore.showToast('请输入创作场景')
    return
  }
  decisionLoading.value = true
  decisionOptions.value = []
  chosenDecisionIdx.value = null
  const authors = presetAuthors.value.slice(0, 5).map((a) => a.name)
  const res = await CreativeAPI.generateDecisionOptions(scenario, authors)
  decisionLoading.value = false
  if (res.ok && res.data) {
    decisionOptions.value = res.data.options || []
    if (decisionOptions.value.length === 0) {
      uiStore.showToast('未生成有效选项', 'info')
    }
  } else {
    uiStore.showToast('生成决策选项失败', 'error')
  }
}

async function chooseDecision(idx: number) {
  const opt = decisionOptions.value[idx]
  if (!opt) return
  await CreativeAPI.recordDecision(decisionScenario.value, opt.author || '', decisionOptions.value)
  chosenDecisionIdx.value = idx
  uiStore.showToast(`已采用 ${opt.author} 的方案，决策已记录`, 'success')
}

// ── 风格校准 ──
async function calibrateStyle() {
  styleCalibrating.value = true
  const res = await WritingAPI.calibrateStyle(props.currentChapter, props.chapterContent || '')
  styleCalibrating.value = false
  if (res.ok && res.data?.ok) {
    styleStatus.value = `累积 ${res.data.rule_count || 0} 条风格规则`
    styleRules.value = res.data.rules || []
  } else {
    styleStatus.value = '校准失败: ' + (res.data?.error || '未知错误')
  }
}

async function loadStyleRules() {
  const res = await WritingAPI.getStyleRules()
  if (res.ok && res.data?.ok) {
    styleStatus.value = `累积 ${res.data.rule_count || 0} 条风格规则`
    styleRules.value = res.data.rules || []
  } else {
    styleStatus.value = '后端未连接'
  }
}

// ── 生命周期 ──
onMounted(() => {
  loadInstrBooks()
  loadPresetAuthors()
  loadStyleRules()
})

defineExpose({ sidebarTab })
</script>

<template>
  <aside class="writing-sidebar">
    <div class="sidebar-tabs">
      <button class="sb-tab" :class="{ active: sidebarTab === 'outline' }" @click="sidebarTab = 'outline'">细纲</button>
      <button class="sb-tab" :class="{ active: sidebarTab === 'characters' }" @click="sidebarTab = 'characters'">角色</button>
      <button class="sb-tab" :class="{ active: sidebarTab === 'world' }" @click="sidebarTab = 'world'">设定</button>
      <button class="sb-tab" :class="{ active: sidebarTab === 'goal-gate' }" @click="sidebarTab = 'goal-gate'">门控</button>
      <button class="sb-tab" :class="{ active: sidebarTab === 'author-mind' }" @click="sidebarTab = 'author-mind'">心智</button>
      <button class="sb-tab" :class="{ active: sidebarTab === 'style' }" @click="sidebarTab = 'style'">风格</button>
      <button class="sb-tab sb-tab-ai" :class="{ active: sidebarTab === 'ai' }" @click="sidebarTab = 'ai'">AI</button>
    </div>

    <!-- 细纲标签 -->
    <div v-show="sidebarTab === 'outline'" class="sb-content">
      <div class="sb-panel">
        <div class="sb-panel-header">本章细纲</div>
        <div class="sb-panel-body">
          <template v-if="currentSegment">
            <div class="outline-item"><b>目标</b><p>{{ currentSegment.goal || '暂无' }}</p></div>
            <div class="outline-item"><b>冲突</b><p>{{ currentSegment.conflict || '暂无' }}</p></div>
            <div class="outline-item"><b>结果</b><p>{{ currentSegment.result || '暂无' }}</p></div>
            <div v-if="currentSegment.hook" class="outline-item"><b>钩子</b><p>{{ currentSegment.hook }}</p></div>
            <div v-if="currentSegment.scenes?.length" class="outline-item">
              <b>场景</b>
              <ul class="scene-list">
                <li v-for="(s, i) in currentSegment.scenes" :key="i">{{ s }}</li>
              </ul>
            </div>
          </template>
          <div v-else class="sb-empty">当前章节暂无细纲，请先在设计页填写</div>
        </div>
      </div>
      <div class="sb-panel">
        <div class="sb-panel-header">大纲参考</div>
        <div class="sb-panel-body">
          <div class="outline-item"><b>当前卷</b><p>{{ currentVolTitle }}</p></div>
          <div class="outline-item"><b>当前段</b><p>第 {{ Math.floor((currentChapter - 1) / 10) * 10 + 1 }}-{{ Math.min(Math.floor((currentChapter - 1) / 10) * 10 + 10, totalChapters) }} 章</p></div>
          <div class="outline-item">
            <b>角色</b>
            <p>{{ projectCharacters.slice(0, 3).map(c => c.name).join(' / ') || '暂无角色' }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 角色标签 -->
    <div v-show="sidebarTab === 'characters'" class="sb-content">
      <div class="sb-panel">
        <div class="sb-panel-header">角色速查</div>
        <div class="sb-panel-body">
          <div v-if="projectCharacters.length === 0" class="sb-empty">暂无角色数据</div>
          <div v-for="(c, i) in projectCharacters" :key="i" class="quick-char">
            <b>{{ c.name }}</b>
            <span class="char-tag">{{ c.role }}</span>
            <p>{{ c.desc }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 设定标签 -->
    <div v-show="sidebarTab === 'world'" class="sb-content">
      <div class="sb-panel">
        <div class="sb-panel-header">设定速查</div>
        <div class="sb-panel-body">
          <div class="outline-item"><b>核心设定</b><p>{{ currentProject?.world?.core || '暂无' }}</p></div>
          <div v-if="currentProject?.world?.powers" class="outline-item">
            <b>能力体系</b>
            <p>{{ currentProject.world.powers }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 目标门控标签 -->
    <div v-show="sidebarTab === 'goal-gate'" class="sb-content">
      <div class="sb-panel">
        <div class="sb-panel-header">章节目标门控</div>
        <div class="sb-panel-body">
          <div v-if="!goalGateResult" class="gg-empty">
            <p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">点击下方按钮验证章节是否满足完成标准</p>
            <div class="gg-criteria-preview">
              <div class="gg-criteria-item">字数范围 (2000-5000字)</div>
              <div class="gg-criteria-item">爽点数量 (≥1个)</div>
              <div class="gg-criteria-item">情绪曲线 (上升型)</div>
              <div class="gg-criteria-item">Canon一致性检查</div>
              <div class="gg-criteria-item">S3评审得分 (≥70分)</div>
            </div>
          </div>
          <div v-else>
            <div class="gg-result" :class="goalGateResult.result === 'pass' ? 'gg-pass' : 'gg-fail'">
              <span class="gg-result-icon">{{ goalGateResult.result === 'pass' ? '✓' : '✗' }}</span>
              <div>
                <div class="gg-result-title">{{ goalGateResult.result === 'pass' ? '章节通过验证' : '未通过验证' }}</div>
                <div class="gg-result-meta">
                  {{ goalGateResult.conditions.length }} 项检查 ·
                  {{ goalGateResult.conditions.filter(c => c.passed).length }} 通过 ·
                  {{ goalGateResult.conditions.filter(c => !c.passed).length }} 未通过
                </div>
              </div>
            </div>
            <div class="gg-conditions">
              <div
                v-for="(c, i) in goalGateResult.conditions"
                :key="i"
                class="gg-condition"
                :class="c.passed ? 'passed' : 'failed'"
              >
                <div class="gg-cond-header">
                  <span class="gg-cond-icon">{{ c.passed ? '✓' : '✗' }}</span>
                  <span class="gg-cond-name">{{ c.name || c.condition }}</span>
                </div>
                <div v-if="c.detail" class="gg-cond-detail">{{ c.detail }}</div>
                <div v-if="c.suggestion" class="gg-cond-suggestion">建议：{{ c.suggestion }}</div>
              </div>
            </div>
            <div v-if="goalGateResult.iteration != null" class="gg-iteration">迭代次数：{{ goalGateResult.iteration }}</div>
          </div>
          <button class="btn btn-primary btn-sm gg-verify-btn" :disabled="goalGateLoading" @click="verifyGoalGate">
            {{ goalGateLoading ? '验证中...' : '验证完成标准' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 作者心智标签 -->
    <div v-show="sidebarTab === 'author-mind'" class="sb-content">
      <div class="sb-panel">
        <div class="sb-panel-header">预设作者心智模型</div>
        <div class="sb-panel-body">
          <div v-if="presetAuthors.length === 0" class="sb-empty">暂无预设作者</div>
          <div
            v-for="a in presetAuthors"
            :key="a.name"
            class="amind-author-card"
            :class="{ active: selectedAuthorName === a.name }"
            @click="selectAuthor(a.name)"
          >
            <div class="amind-author-avatar">{{ a.name[0] }}</div>
            <div class="amind-author-info">
              <div class="amind-author-name">{{ a.name }}</div>
              <div class="amind-author-style">{{ a.style || '' }}</div>
            </div>
          </div>
        </div>
      </div>
      <div v-if="selectedAuthorName" class="sb-panel">
        <div class="sb-panel-header">{{ selectedAuthorName }} · 心智模型</div>
        <div class="sb-panel-body">
          <div v-if="authorDetailLoading" class="sb-empty">加载中...</div>
          <template v-else-if="authorDetail">
            <div class="amind-detail-works">
              <span v-for="w in authorDetail.representative_works" :key="w" class="char-tag">{{ w }}</span>
            </div>
            <div class="amind-framework-grid">
              <template v-for="fw in [
                { label: '故事结构', val: authorDetail.framework.structure, det: authorDetail.framework.structure_detail },
                { label: '爽点逻辑', val: authorDetail.framework.pleasure_logic, det: authorDetail.framework.pleasure_detail },
                { label: '节奏方法论', val: authorDetail.framework.rhythm_method, det: authorDetail.framework.rhythm_detail },
                { label: '人物塑造', val: authorDetail.framework.characterization, det: authorDetail.framework.characterization_detail },
                { label: '冲突风格', val: authorDetail.framework.conflict_style, det: authorDetail.framework.conflict_detail },
                { label: '世界观构建', val: authorDetail.framework.worldbuilding, det: authorDetail.framework.worldbuilding_detail },
              ]" :key="fw.label">
                <div v-if="fw.val" class="amind-fw-item">
                  <div class="amind-fw-label">{{ fw.label }}</div>
                  <div class="amind-fw-value">{{ fw.val }}</div>
                  <div v-if="fw.det" class="amind-fw-detail">{{ fw.det }}</div>
                </div>
              </template>
            </div>
            <div v-if="authorDetail.signature_techniques?.length" class="amind-subsection">
              <b>标志性技法</b>
              <ul class="amind-tech-list">
                <li v-for="(t, i) in authorDetail.signature_techniques" :key="i">{{ t.technique || t.name }}{{ t.desc ? ' — ' + t.desc : '' }}</li>
              </ul>
            </div>
          </template>
        </div>
      </div>
      <div class="sb-panel sb-panel-accent">
        <div class="sb-panel-header">决策直觉引擎</div>
        <div class="sb-panel-body">
          <textarea v-model="decisionScenario" class="amind-scenario-input" placeholder="输入创作场景，如：主角面对强敌，实力差距悬殊" rows="3" />
          <button class="btn btn-primary btn-sm" :disabled="decisionLoading" @click="runDecisionEngine" style="margin-top:6px;width:100%;">
            {{ decisionLoading ? '生成中...' : '生成决策选项' }}
          </button>
          <div v-if="decisionOptions.length" class="amind-options-list">
            <div
              v-for="(opt, i) in decisionOptions"
              :key="i"
              class="amind-option-card"
              :class="{ chosen: chosenDecisionIdx === i }"
            >
              <div class="amind-option-header">
                <span class="amind-option-author">{{ opt.author || '?' }}</span>
                <button class="btn btn-secondary btn-sm" @click="chooseDecision(i)">采用</button>
              </div>
              <div class="amind-option-choice">{{ opt.choice || '' }}</div>
              <div v-if="opt.reasoning" class="amind-option-reasoning">{{ opt.reasoning }}</div>
              <div v-if="opt.risk" class="amind-option-risk">风险：{{ opt.risk }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 风格校准标签 -->
    <div v-show="sidebarTab === 'style'" class="sb-content">
      <div class="sb-panel">
        <div class="sb-panel-header">风格校准</div>
        <div class="sb-panel-body">
          <div class="style-calibrate-status">{{ styleStatus || '点击校准以积累风格规则' }}</div>
          <button class="btn btn-primary btn-sm" :disabled="styleCalibrating" @click="calibrateStyle" style="margin-top:6px;width:100%;">
            {{ styleCalibrating ? '校准中...' : '校准当前章节' }}
          </button>
        </div>
      </div>
      <div class="sb-panel">
        <div class="sb-panel-header">风格规则 ({{ styleRules.length }})</div>
        <div class="sb-panel-body">
          <div v-if="styleRules.length === 0" class="sb-empty">暂无规则，完成 S3 评审后自动积累</div>
          <div v-for="(r, i) in styleRules" :key="i" class="style-rule-item">
            <span class="style-rule-dim">[{{ r.dimension }}]</span>
            <span class="style-rule-text">{{ r.rule }}</span>
            <span class="style-rule-weight">x{{ r.weight }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- AI工具标签 -->
    <div v-show="sidebarTab === 'ai'" class="sb-content">
      <div class="sb-panel sb-panel-accent">
        <div class="sb-panel-header">AI指纹检测清单</div>
        <div class="sb-panel-body">
          <label class="check-item"><input type="checkbox" checked /> 避免"首先/其次"机械衔接</label>
          <label class="check-item"><input type="checkbox" /> 检查是否有过度解释性总结</label>
          <label class="check-item"><input type="checkbox" checked /> 确保动词优先，少用形容词堆叠</label>
          <label class="check-item"><input type="checkbox" /> 对话是否带有角色个性</label>
          <label class="check-item check-warn"><input type="checkbox" checked /> 删掉"不得不说/众所周知"</label>
        </div>
      </div>
      <div class="sb-panel sb-panel-accent">
        <div class="sb-panel-header">逐章指令</div>
        <div class="sb-panel-body">
          <div class="instr-controls">
            <select v-model="instrSelectedBook" class="instr-select">
              <option value="">选择参考书</option>
              <option v-for="b in instrBooks" :key="b" :value="b">{{ b }}</option>
            </select>
            <input v-model.number="instrChapterInput" type="number" min="1" class="instr-chapter" />
            <button class="btn btn-primary btn-sm" @click="loadInstructions">加载</button>
          </div>
          <div v-if="instrLoading" class="sb-empty">加载中...</div>
          <div v-else-if="instrItems.length === 0" class="sb-empty">请选择参考书与章节，点击加载获取指令</div>
          <div v-else class="instr-list">
            <div
              v-for="(item, i) in instrItems"
              :key="i"
              class="instr-item"
              :class="'instr-' + item.level"
            >
              <span class="instr-level">{{ item.level }}</span>
              <span class="instr-text">{{ item.text }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.writing-sidebar { width: 280px; flex-shrink: 0; border-left: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
.sidebar-tabs { display: flex; border-bottom: 1px solid var(--border); }
.sb-tab { flex: 1; padding: 8px 2px; border: none; background: transparent; color: var(--text-secondary); font-size: 11px; cursor: pointer; transition: all 0.15s; border-bottom: 2px solid transparent; white-space: nowrap; }
.sb-tab:hover { color: var(--text); }
.sb-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.sb-tab-ai { color: var(--amber); }
.sb-tab-ai.active { color: var(--amber); border-bottom-color: var(--amber); }
.sb-content { flex: 1; overflow-y: auto; padding: 8px; }
.sb-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; overflow: hidden; }
.sb-panel-accent { border-color: rgba(245, 158, 11, 0.3); }
.sb-panel-header { padding: 8px 12px; font-size: 12px; font-weight: 600; border-bottom: 1px solid var(--border); cursor: pointer; }
.sb-panel-body { padding: 10px 12px; }
.sb-empty { padding: 12px; color: var(--text-secondary); font-size: 12px; text-align: center; }

.outline-item { margin-bottom: 8px; }
.outline-item b { font-size: 11px; color: var(--text-secondary); display: block; margin-bottom: 2px; }
.outline-item p { font-size: 12px; margin: 0; line-height: 1.5; }
.scene-list { margin: 4px 0 0; padding-left: 16px; font-size: 12px; color: var(--text-secondary); }

.quick-char { padding: 8px 0; border-bottom: 1px solid var(--border); }
.quick-char:last-child { border-bottom: none; }
.quick-char b { font-size: 13px; }
.char-tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: rgba(56, 189, 248, 0.1); color: var(--accent); margin-left: 6px; }
.quick-char p { font-size: 12px; color: var(--text-secondary); margin: 4px 0 0; }

.check-item { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 0; cursor: pointer; }
.check-item input { accent-color: var(--accent); }
.check-warn { color: var(--warning); }

.instr-controls { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.instr-select { flex: 1; min-width: 100px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); font-size: 12px; }
.instr-chapter { width: 50px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); font-size: 12px; }
.instr-list { display: flex; flex-direction: column; gap: 6px; }
.instr-item { padding: 6px 8px; background: var(--surface-solid); border-radius: 4px; border-left: 3px solid var(--border); font-size: 12px; }
.instr-critical { border-left-color: var(--danger); }
.instr-warning { border-left-color: var(--warning); }
.instr-info { border-left-color: var(--accent); }
.instr-level { font-size: 10px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 2px; }
.instr-text { line-height: 1.5; }

/* ── 目标门控 ── */
.gg-empty { text-align: center; padding: 8px 0; }
.gg-criteria-preview { display: flex; flex-direction: column; gap: 4px; text-align: left; }
.gg-criteria-item { font-size: 11px; color: var(--text-secondary); padding: 2px 0 2px 12px; position: relative; }
.gg-criteria-item::before { content: ''; position: absolute; left: 0; top: 8px; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); opacity: 0.5; }
.gg-result { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 8px; margin-bottom: 8px; }
.gg-result.gg-pass { background: rgba(34, 197, 94, 0.1); }
.gg-result.gg-fail { background: rgba(239, 68, 68, 0.1); }
.gg-result-icon { font-size: 20px; font-weight: 700; }
.gg-pass .gg-result-icon { color: var(--success); }
.gg-fail .gg-result-icon { color: var(--danger); }
.gg-result-title { font-size: 13px; font-weight: 600; }
.gg-result-meta { font-size: 11px; color: var(--text-secondary); }
.gg-conditions { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
.gg-condition { padding: 6px 8px; border-radius: 6px; border: 1px solid var(--border); }
.gg-condition.passed { border-color: rgba(34, 197, 94, 0.3); }
.gg-condition.failed { border-color: rgba(239, 68, 68, 0.3); }
.gg-cond-header { display: flex; align-items: center; gap: 6px; }
.gg-cond-icon { font-size: 12px; font-weight: 700; }
.gg-condition.passed .gg-cond-icon { color: var(--success); }
.gg-condition.failed .gg-cond-icon { color: var(--danger); }
.gg-cond-name { font-size: 12px; font-weight: 500; }
.gg-cond-detail { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }
.gg-cond-suggestion { font-size: 11px; color: var(--warning); margin-top: 2px; }
.gg-iteration { font-size: 11px; color: var(--text-secondary); text-align: right; }
.gg-verify-btn { width: 100%; margin-top: 8px; }

/* ── 作者心智 ── */
.amind-author-card { display: flex; align-items: center; gap: 8px; padding: 8px; border-radius: 6px; cursor: pointer; transition: all 0.15s; }
.amind-author-card:hover { background: var(--surface-hover); }
.amind-author-card.active { background: rgba(56, 189, 248, 0.08); border: 1px solid var(--accent); }
.amind-author-avatar { width: 32px; height: 32px; border-radius: 50%; background: var(--accent); color: var(--bg); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; flex-shrink: 0; }
.amind-author-name { font-size: 13px; font-weight: 600; }
.amind-author-style { font-size: 11px; color: var(--text-secondary); }
.amind-detail-works { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.amind-framework-grid { display: grid; grid-template-columns: 1fr; gap: 6px; }
.amind-fw-item { padding: 6px; background: var(--surface-solid); border-radius: 6px; border: 1px solid var(--border); }
.amind-fw-label { font-size: 10px; color: var(--text-secondary); text-transform: uppercase; }
.amind-fw-value { font-size: 12px; font-weight: 500; margin-top: 2px; }
.amind-fw-detail { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.amind-subsection { margin-top: 8px; }
.amind-subsection b { font-size: 12px; }
.amind-tech-list { margin: 4px 0 0; padding-left: 16px; font-size: 11px; color: var(--text-secondary); }
.amind-scenario-input { width: 100%; background: var(--surface-solid); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-size: 12px; padding: 6px 8px; resize: vertical; font-family: inherit; }
.amind-options-list { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.amind-option-card { padding: 8px; background: var(--surface-solid); border: 1px solid var(--border); border-radius: 6px; }
.amind-option-card.chosen { border-color: var(--success); background: rgba(34, 197, 94, 0.05); }
.amind-option-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.amind-option-author { font-size: 12px; font-weight: 600; color: var(--accent); }
.amind-option-choice { font-size: 12px; line-height: 1.5; }
.amind-option-reasoning { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }
.amind-option-risk { font-size: 11px; color: var(--warning); margin-top: 2px; }

/* ── 风格校准 ── */
.style-calibrate-status { font-size: 12px; color: var(--text-secondary); padding: 4px 0; }
.style-rule-item { display: flex; align-items: flex-start; gap: 4px; padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
.style-rule-item:last-child { border-bottom: none; }
.style-rule-dim { color: var(--accent); font-size: 11px; flex-shrink: 0; }
.style-rule-text { flex: 1; line-height: 1.4; }
.style-rule-weight { font-size: 11px; color: var(--text-secondary); flex-shrink: 0; }

/* ── 按钮 — 全局 style.css 接管 ── */

@media (max-width: 1024px) { .writing-sidebar { width: 220px; } }
@media (max-width: 768px) { .writing-sidebar { display: none; } }
</style>
