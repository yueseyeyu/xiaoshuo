<script setup lang="ts">
/**
 * QuickStartWizard — 快速开始向导（5步弹窗）
 * 从 DesignView 提取。创建项目 + 生成骨架后 emit('generated')。
 */
import { ref } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import { ProjectAPI } from '@/api/project'
import type { Volume, SkeletonChapter } from '@/types'

const emit = defineEmits<{
  close: []
  generated: []
}>()

const projectStore = useProjectStore()
const uiStore = useUiStore()

const qsStep = ref(1)
const qsMaxSteps = 5
const qsGenerating = ref(false)
const qsData = ref({
  genre: '',
  premise: '',
  synopsis: '',
  hook: '',
  protagonist: '',
  goldfinger: '',
  goals: '',
})

const GENRES = ['末世', '仙侠', '科幻', '都市', '悬疑', '无限流', '历史', '奇幻', '洪荒', '同人', '游戏', '玄幻']

function qsSelectGenre(g: string) {
  if (qsGenerating.value) return
  qsData.value.genre = g
  qsStep.value = 2
}

function qsNext() {
  if (qsGenerating.value) return
  if (qsStep.value === 2) {
    if (!qsData.value.premise.trim()) { uiStore.showToast('请输入一句话梗概'); return }
    qsStep.value = 3
  } else if (qsStep.value === 3) {
    if (!qsData.value.hook.trim()) { uiStore.showToast('请填写卖点'); return }
    qsStep.value = 4
  } else if (qsStep.value === 4) {
    if (!qsData.value.protagonist.trim()) { uiStore.showToast('请填写主角人设'); return }
    qsStep.value = 5
  }
}

function qsPrev() {
  if (qsGenerating.value) return
  if (qsStep.value > 1) qsStep.value--
}

function formatError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return '未知错误'
}

function showStepError(step: string, error?: unknown) {
  const detail = error === undefined ? '' : `：${typeof error === 'string' ? error : formatError(error)}`
  uiStore.showToast(`${step}失败${detail}`, 'error')
}

async function runApiStep(
  step: string,
  request: () => Promise<{ ok: boolean; error?: string }>,
): Promise<boolean> {
  try {
    const result = await request()
    if (!result.ok) {
      showStepError(step, result.error)
      return false
    }
    return true
  } catch (error) {
    showStepError(step, error)
    return false
  }
}

function closeWizard() {
  if (!qsGenerating.value) emit('close')
}

async function qsGenerate() {
  if (!qsData.value.premise.trim()) { uiStore.showToast('请输入梗概'); return }
  if (qsGenerating.value) return
  const requestData = { ...qsData.value }
  qsGenerating.value = true

  const fullSummary = requestData.premise +
    (requestData.hook ? ` 【卖点】${requestData.hook}` : '') +
    (requestData.protagonist ? ` 【主角】${requestData.protagonist}` : '') +
    (requestData.goldfinger ? ` 【金手指】${requestData.goldfinger}` : '')

  try {
    let createRes
    try {
      createRes = await ProjectAPI.create({
        title: requestData.premise.substring(0, 12) + '...',
        genre: requestData.genre || '末世',
        summary: fullSummary,
        volumes_count: 5,
        total_chapters: 300,
      })
    } catch (error) {
      showStepError('创建项目', error)
      return
    }

    if (!createRes.ok || !createRes.data?.project) {
      showStepError('创建项目', createRes.error)
      return
    }

    const proj = createRes.data.project
    try {
      await projectStore.loadProject(proj.id)
    } catch (error) {
      showStepError('加载项目', error)
      return
    }
    if (projectStore.currentProject?.id !== proj.id) {
      showStepError('加载项目', '项目已创建，但未加载到新项目')
      return
    }

    uiStore.showToast('项目已创建，正在生成骨架...', 'success')
    if (await generateSkeletonFromPremise(requestData)) {
      emit('generated')
      emit('close')
    }
  } catch (error) {
    showStepError('生成骨架', error)
  } finally {
    qsGenerating.value = false
  }
}

async function generateSkeletonFromPremise(qs: typeof qsData.value): Promise<boolean> {
  if (!projectStore.currentProject?.id) {
    uiStore.showToast('未找到当前项目，无法生成骨架', 'error')
    return false
  }
  const pid = projectStore.currentProject.id
  const premise = qs.premise

  interface VolumeTemplate {
    title: string
    range: string
    subtitle: string
    summary: string
    tags: string[]
  }

  const templates: Record<string, VolumeTemplate[]> = {
    '末世': [
      { title: '第一卷', range: '1-60章', subtitle: '灾变降临', summary: `${premise} 主角在灾变中觉醒能力，被迫面对末日初期的混乱。`, tags: ['觉醒', '逃亡', '生存'] },
      { title: '第二卷', range: '61-120章', subtitle: '废墟秩序', summary: '主角建立据点，组建团队，在资源匮乏中确立领导地位。', tags: ['据点', '团队', '资源'] },
      { title: '第三卷', range: '121-180章', subtitle: '暗流涌动', summary: '外部势力介入，内部出现分歧，主角面临信任与利益考验。', tags: ['冲突', '权谋', '分裂'] },
      { title: '第四卷', range: '181-240章', subtitle: '进化之路', summary: '危机升级，主角必须向更危险的区域进发，实力大幅提升。', tags: ['进化', '副本', 'Boss'] },
      { title: '第五卷', range: '241-300章', subtitle: '终极真相', summary: '幕后真相揭露，主角面临最终抉择，格局拉升至世界级。', tags: ['真相', '决战', '终章'] },
    ],
    _default: [
      { title: '第一卷', range: '1-60章', subtitle: '起步篇', summary: `${premise} 主角获得金手指，初步展示能力。`, tags: ['起步', '金手指'] },
      { title: '第二卷', range: '61-120章', subtitle: '发展篇', summary: '主角在更大舞台展现实力，建立势力或人脉。', tags: ['发展', '势力'] },
      { title: '第三卷', range: '121-180章', subtitle: '高潮篇', summary: '核心冲突爆发，主角面临最大挑战。', tags: ['高潮', '冲突'] },
      { title: '第四卷', range: '181-240章', subtitle: '转折篇', summary: '格局升级，新的威胁出现，主角突破瓶颈。', tags: ['转折', '升级'] },
      { title: '第五卷', range: '241-300章', subtitle: '终章', summary: '终极对决，主角达成目标，故事圆满收束。', tags: ['终章', '圆满'] },
    ],
  }
  const volData = templates[qs.genre] || templates._default

  const newVolumes: Volume[] = volData.map(v => ({
    title: v.title,
    subtitle: v.subtitle,
    chapters: v.range,
  }))

  const goalList = (qs.goals || '').split(/[→\->\n]/).map(s => s.trim()).filter(Boolean)
  const newChapters: SkeletonChapter[] = []
  for (let i = 0; i < 30; i++) {
    const chNum = i * 10 + 1
    const chEnd = chNum + 9
    const volIdx = Math.floor(i / 6)
    const vol = volData[volIdx] || volData[volData.length - 1]
    let chHook = '', chPleasure = '', chExpectation = ''
    if (i === 0) {
      chHook = qs.hook ? `开篇钩子：${qs.hook}` : '开篇钩子：前300字出冲突，金手指落地'
      chPleasure = qs.goldfinger ? `金手指首秀：${qs.goldfinger.substring(0, 40)}` : '金手指首次展示'
      chExpectation = '读者期待：主角如何应对危机'
    } else if (i === 1) {
      chHook = '章末悬念：第一次危机升级'
      chPleasure = '爽点：金手指威力初显'
    } else if (i === 2) {
      chHook = '黄金三章收束：小闭环完成'
      chPleasure = '爽点：第一次打脸/逆袭'
      chExpectation = '读者期待：主角的真正潜力'
    }
    const goalIdx = Math.min(i, goalList.length - 1)
    const goalText = goalList.length > 0 ? goalList[goalIdx] : `${vol.subtitle}阶段目标`
    newChapters.push({
      title: `第${chNum}-${chEnd}章`,
      goal: goalText,
      conflict: '待细化',
      result: '待细化',
      hook: chHook,
      pleasure: chPleasure,
      foreshadowing: '',
      expectation: chExpectation,
      scenes: [],
    })
  }

  if (!await runApiStep(
    '保存粗纲',
    () => ProjectAPI.updateSkeleton(pid, { volumes: newVolumes, chapters: newChapters }),
  )) {
    return false
  }

  const worldCore = premise + (qs.hook ? ` 核心卖点：${qs.hook}` : '')
  const worldPowers = qs.goldfinger || '待设定（建议：能力来源、升级路径、限制条件）'
  if (!await runApiStep(
    '保存世界观',
    () => ProjectAPI.updateWorld(pid, { core: worldCore, powers: worldPowers }),
  )) {
    return false
  }

  if (qs.protagonist) {
    const charName = qs.protagonist.split('，')[0].substring(0, 10) || '主角'
    if (!await runApiStep(
      '保存角色',
      () => ProjectAPI.updateCharacters(pid, [{
        name: charName,
        role: '主角',
        identity: '',
        personality: '',
        ability: qs.goldfinger || '',
        desc: qs.protagonist + (qs.goldfinger ? ` 金手指：${qs.goldfinger}` : ''),
      }]),
    )) {
      return false
    }
  }

  uiStore.showToast('骨架已生成！点击粗纲查看', 'success')
  return true
}
</script>

<template>
  <Teleport to="body">
    <div class="qs-overlay" @click.self="closeWizard">
      <div class="qs-modal">
        <div class="qs-modal-header">
          <h3><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-3px;margin-right:4px;"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>快速开始：从梗概到大纲</h3>
          <button class="icon-btn" :disabled="qsGenerating" @click="closeWizard">×</button>
        </div>
        <!-- 步骤指示器 -->
        <div class="qs-indicator">
          <template v-for="s in qsMaxSteps" :key="s">
            <span class="qs-dot" :class="{ done: s < qsStep, active: s === qsStep }" />
            <span v-if="s < qsMaxSteps" class="qs-line" />
          </template>
        </div>
        <div class="qs-body">
          <!-- Step 1: 题材 -->
          <template v-if="qsStep === 1">
            <h3 class="qs-title">选择题材</h3>
            <p class="qs-desc">选择你正在写或想写的题材，系统会参考同类爆款数据辅助设计</p>
            <div class="qs-genre-grid">
              <button
                v-for="g in GENRES"
                :key="g"
                class="qs-genre-btn"
                :class="{ selected: qsData.genre === g }"
                :disabled="qsGenerating"
                @click="qsSelectGenre(g)"
              >{{ g }}</button>
            </div>
          </template>
          <!-- Step 2: 剧情 -->
          <template v-else-if="qsStep === 2">
            <h3 class="qs-title">剧情 — 用一句话抓住故事核心</h3>
            <p class="qs-desc">好的梗概 = 主角 + 金手指 + 核心冲突 + 目标</p>
            <div class="qs-input-area">
              <textarea v-model="qsData.premise" :disabled="qsGenerating" placeholder="例：高考生在末日考场觉醒模拟器..." rows="3" />
              <textarea v-model="qsData.synopsis" :disabled="qsGenerating" placeholder="扩展简介（可选）" rows="3" style="margin-top:8px;" />
            </div>
            <div class="qs-nav">
              <button class="btn btn-secondary" :disabled="qsGenerating" @click="qsPrev">上一步</button>
              <button class="btn btn-primary" :disabled="qsGenerating" @click="qsNext">下一步</button>
            </div>
          </template>
          <!-- Step 3: 卖点 -->
          <template v-else-if="qsStep === 3">
            <h3 class="qs-title">卖点 — 你的故事凭什么吸引读者？</h3>
            <p class="qs-desc">思考你的故事与同类作品的核心差异</p>
            <div class="qs-input-area">
              <textarea v-model="qsData.hook" :disabled="qsGenerating" placeholder="例：系统不是打怪升级，而是通过养灵宠代打" rows="3" />
            </div>
            <div class="qs-nav">
              <button class="btn btn-secondary" :disabled="qsGenerating" @click="qsPrev">上一步</button>
              <button class="btn btn-primary" :disabled="qsGenerating" @click="qsNext">下一步</button>
            </div>
          </template>
          <!-- Step 4: 人设 -->
          <template v-else-if="qsStep === 4">
            <h3 class="qs-title">人设与目标</h3>
            <div class="qs-input-area">
              <div class="qs-field">
                <label>主角人设</label>
                <textarea v-model="qsData.protagonist" :disabled="qsGenerating" placeholder="例：聪明但爱摆烂的理性派" rows="2" />
              </div>
              <div class="qs-field">
                <label>金手指/外挂</label>
                <textarea v-model="qsData.goldfinger" :disabled="qsGenerating" placeholder="例：灵宠养成系统" rows="2" />
              </div>
              <div class="qs-field">
                <label>阶段目标</label>
                <textarea v-model="qsData.goals" :disabled="qsGenerating" placeholder="例：征服宗门 → 征服帝国 → 登顶" rows="3" />
              </div>
            </div>
            <div class="qs-nav">
              <button class="btn btn-secondary" @click="qsPrev">上一步</button>
              <button class="btn btn-primary" @click="qsNext">下一步</button>
            </div>
          </template>
          <!-- Step 5: 确认 -->
          <template v-else-if="qsStep === 5">
            <h3 class="qs-title">确认并生成</h3>
            <p class="qs-desc">系统将根据以上设定创建项目并生成骨架</p>
            <div class="qs-confirm">
              <div class="qs-confirm-row"><span>题材</span><b>{{ qsData.genre }}</b></div>
              <div class="qs-confirm-row"><span>剧情</span><b>{{ qsData.premise }}</b></div>
              <div class="qs-confirm-row"><span>卖点</span><b>{{ qsData.hook || '未填写' }}</b></div>
              <div class="qs-confirm-row"><span>主角</span><b>{{ qsData.protagonist || '未填写' }}</b></div>
              <div class="qs-confirm-row"><span>金手指</span><b>{{ qsData.goldfinger || '未填写' }}</b></div>
            </div>
            <div class="qs-nav">
              <button class="btn btn-secondary" :disabled="qsGenerating" @click="qsPrev">上一步</button>
              <button class="btn btn-primary" :disabled="qsGenerating" @click="qsGenerate">
                {{ qsGenerating ? '正在生成...' : '创建项目并生成骨架' }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.qs-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1001; }
.qs-modal { background: var(--surface-solid); border: 1px solid var(--border); border-radius: 12px; width: 90%; max-width: 560px; max-height: 85vh; display: flex; flex-direction: column; }
.qs-modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.qs-modal-header h3 { font-size: 15px; font-weight: 600; }
.icon-btn { background: none; border: none; font-size: 20px; color: var(--text-secondary); cursor: pointer; padding: 4px 8px; }
.icon-btn:hover { color: var(--text); }
.qs-indicator { display: flex; align-items: center; justify-content: center; gap: 0; padding: 12px 16px; }
.qs-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--border); transition: all 0.2s; }
.qs-dot.active { background: var(--accent); transform: scale(1.2); }
.qs-dot.done { background: var(--success); }
.qs-line { width: 32px; height: 2px; background: var(--border); margin: 0 4px; }
.qs-body { padding: 16px; overflow-y: auto; flex: 1; }
.qs-title { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
.qs-desc { font-size: 13px; color: var(--text-secondary); margin-bottom: 16px; }
.qs-genre-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.qs-genre-btn { padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.qs-genre-btn:hover { border-color: var(--accent); }
.qs-genre-btn.selected { border-color: var(--accent); background: rgba(56, 189, 248, 0.08); color: var(--accent); }
.qs-input-area { display: flex; flex-direction: column; gap: 8px; }
.qs-input-area textarea { padding: 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font-size: 14px; font-family: inherit; resize: vertical; }
.qs-input-area textarea:focus { outline: none; border-color: var(--accent); }
.qs-field { margin-bottom: 10px; }
.qs-field label { font-size: 12px; color: var(--text-secondary); display: block; margin-bottom: 4px; }
.qs-field textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font-size: 13px; font-family: inherit; resize: vertical; }
.qs-field textarea:focus { outline: none; border-color: var(--accent); }
.qs-nav { display: flex; justify-content: space-between; margin-top: 16px; }
.qs-confirm { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 16px; }
.qs-confirm-row { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px solid var(--border); }
.qs-confirm-row:last-child { border-bottom: none; }
.qs-confirm-row span { color: var(--text-secondary); }
.qs-confirm-row b { max-width: 70%; text-align: right; }

/* ── 按钮 — 全局 style.css 接管 ── */

@media (max-width: 768px) {
  .qs-genre-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
