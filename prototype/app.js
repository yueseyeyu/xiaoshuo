
"use strict";

// $ / $$ 与常用工具函数已由 js/utils.js 全局提供，此处不再重复声明
const appShell = $('#app-shell');

// ============================================================
// API 数据层 — 从后端获取真实分析数据
// 写入 appState.apiData（在 state.js 中定义）
// ============================================================
async function loadApiData() {
  const endpoints = [
    { key: 'stats', path: '/api/stats' },
    { key: 'guidance', path: '/api/guidance' },
    { key: 'techniques', path: '/api/techniques' },
    { key: 'diagnosis', path: '/api/diagnosis' },
  ];
  const results = await Promise.allSettled(
    endpoints.map((ep) => apiGet(ep.path).then((res) => {
      if (res.ok) appState.apiData[ep.key] = res.data;
    }))
  );
  const successCount = results.filter((r) => r.status === 'fulfilled').length;
  appState.apiData.ready = successCount > 0;
  renderLibrary();
  renderDashboardProject();
  renderReports();
  if (successCount > 0) {
    console.log('[API] Loaded ' + successCount + '/' + endpoints.length + ' endpoints');
  } else {
    console.log('[API] Not available, using embedded data');
  }
}


async function loadSkeletonData() {
  const btn = $('#btn-load-skeleton');
  if (btn) { btn.textContent = '加载中...'; btn.disabled = true; }
  const { ok, data, error } = await apiGet('/api/skeleton');
  if (ok && data && data.volumes) {
    appState.apiData.skeleton = data;
    renderDesignFromSkeleton(data);
    showToast('骨架数据已加载（5卷 + 节奏基准）');
  } else {
    console.log('[API] Skeleton not available:', error);
    showToast('API 不可用，使用本地数据');
  }
  if (btn) { btn.textContent = '从后端加载骨架'; btn.disabled = false; }
}




function updateSaveStatus(state) {
  const el = $('#save-status');
  if (!el) return;
  if (state === 'saving') {
    el.textContent = '保存中...';
    el.style.opacity = '1';
  } else if (state === 'saved') {
    el.textContent = '已保存';
    el.style.opacity = '0.7';
  }
}

let saveStatusTimeout = null;
function scheduleSaveStatusSaved() {
  if (saveStatusTimeout) clearTimeout(saveStatusTimeout);
  saveStatusTimeout = setTimeout(() => updateSaveStatus('saved'), 800);
}


function isDemoProject(project) {
  if (!project) return false;
  return project.is_demo === true || project.isDemo === true || project.title === '《末日模拟器》';
}

function _currentProjectIdKey() {
  return 'current_project_id';
}

async function loadProject() {
  currentProject = null;
  appState.projectData = null;
  let projectId = null;
  try {
    projectId = localStorage.getItem(_currentProjectIdKey());
  } catch (e) {}
  if (projectId) {
    const project = await ProjectAPI.get(projectId);
    if (project && project.meta) {
      if (project.is_demo) {
        // 示例项目不持久化：刷新后自动回到空状态首页
        try { localStorage.removeItem(_currentProjectIdKey()); } catch (e) {}
      } else {
        currentProject = _normalizeProjectMeta(project);
        appState.projectData = project;
      }
    } else {
      try { localStorage.removeItem(_currentProjectIdKey()); } catch (e) {}
    }
  }
  renderDashboardProject();
  updateTopbarProjectName();
  populateProjectSwitcher();
}

function setCurrentProject(projectMeta) {
  currentProject = projectMeta || null;
  appState.projectData = null;
  try {
    if (projectMeta && projectMeta.id) {
      localStorage.setItem(_currentProjectIdKey(), projectMeta.id);
    } else {
      localStorage.removeItem(_currentProjectIdKey());
    }
  } catch (e) {}
  renderDashboardProject();
  updateTopbarProjectName();
  populateProjectSwitcher();
}

function _normalizeProjectMeta(project) {
  if (!project) return null;
  const meta = project.meta || project;
  return {
    id: project.id || meta.id,
    title: meta.title || '未命名作品',
    author: meta.author || '作者',
    genre: meta.genre || '未设置',
    volumes: meta.volumes_count || meta.volumes || 0,
    totalChapters: meta.total_chapters || meta.totalChapters || 0,
    writtenChapters: meta.written_chapters || meta.writtenChapters || 0,
    cards: meta.cards || 0,
    summary: meta.summary || '',
    is_demo: project.is_demo === true || meta.is_demo === true || meta.title === '《末日模拟器》',
  };
}

// 兼容旧代码：saveProject 现在只切换当前项目，不持久化完整数据（数据走后端 API）
function saveProject(project) {
  setCurrentProject(_normalizeProjectMeta(project));
}











function renderPipelineStates() {
  document.querySelectorAll('.pipeline-stage').forEach((stage) => {
    const dot = stage.querySelector('.stage-dot');
    const name = stage.querySelector('.stage-name');
    const icon = stage.querySelector('.stage-icon');
    if (!dot) return;
    const state = dot.classList.contains('completed') ? 'completed' : (dot.classList.contains('running') ? 'running' : 'pending');
    stage.classList.remove('completed', 'running', 'pending');
    stage.classList.add(state);
    if (name) {
      name.classList.remove('completed', 'running', 'pending');
      name.classList.add(state);
    }
    if (icon) {
      icon.classList.remove('completed', 'running', 'pending');
      icon.classList.add(state);
    }
  });
}



// 点击页面其他地方关闭硬件下拉和写作页更多菜单
document.addEventListener('click', function(e) {
  const monitor = $('#hw-monitor');
  if (monitor && !monitor.contains(e.target)) closeHardwareDropdown();
  const more = $('.writing-more-dropdown.open');
  if (more && !more.contains(e.target)) more.classList.remove('open');
});











function updateActivityTimes() {
  $$('.activity-time[data-timestamp]').forEach((el) => {
    const spec = el.dataset.timestamp;
    const now = Date.now();
    let ts;
    if (spec.endsWith('h')) ts = now - parseInt(spec, 10) * 3600 * 1000;
    else if (spec.endsWith('m')) ts = now - parseInt(spec, 10) * 60 * 1000;
    else if (spec.endsWith('d')) ts = now - parseInt(spec, 10) * 86400 * 1000;
    else ts = new Date(spec).getTime() || now;
    el.textContent = timeAgo(new Date(ts));
  });
}

function togglePipelineDetail() {
  const track = $('#pipeline-track');
  const btn = $('#pipeline-toggle');
  if (!track || !btn) return;
  const collapsed = track.classList.toggle('collapsed');
  btn.classList.toggle('collapsed', collapsed);
  try { localStorage.setItem('pipeline_detail_collapsed', collapsed ? '1' : '0'); } catch(e) {}
}

function toggleSelectAllBooks() {
  const filtered = getFilteredBooks();
  const ids = filtered.map((b) => DATA.books.indexOf(b));
  const allSelected = ids.length > 0 && ids.every((idx) => selectedBookIds.has(idx));
  if (allSelected) ids.forEach((idx) => selectedBookIds.delete(idx));
  else ids.forEach((idx) => selectedBookIds.add(idx));
  renderLibrary();
}

function getFilteredBooks() {
  const searchInput = $('#library-search');
  const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
  let filtered = currentGenre === '全部' ? DATA.books : DATA.books.filter((b) => b.genre === currentGenre);
  if (query) {
    filtered = filtered.filter((b) =>
      (b.title && b.title.toLowerCase().includes(query)) ||
      (b.author && b.author.toLowerCase().includes(query)) ||
      (b.genre && b.genre.toLowerCase().includes(query))
    );
  }
  return applyLibrarySort(filtered);
}

function clearBookSelection() {
  selectedBookIds.clear();
  renderLibrary();
}


function getWizardStepStates() {
  const steps = [
    { num: '1', title: '选择题材', subtitle: '聚焦你正在写的题材，如末世、无限流', desc: '选择题材' },
    { num: '2', title: '导入书籍', subtitle: '从书库挑选 3-5 本代表作', desc: '导入书籍' },
    { num: '3', title: '启动管线', subtitle: '系统自动拆书、评分、提炼技法', desc: '启动管线' }
  ];
  const genreDone = currentGenre !== '全部';
  const booksDone = DATA && DATA.books && DATA.books.length > 0;
  const tasksDone = tasks.length > 0;
  const conditions = [genreDone, booksDone, tasksDone];
  let currentIdx = conditions.findIndex((done) => !done);
  if (currentIdx === -1) currentIdx = steps.length;
  return steps.map((s, idx) => {
    let state = 'pending';
    if (idx < currentIdx) state = 'completed';
    else if (idx === currentIdx) state = 'running';
    return Object.assign({}, s, { state });
  });
}













const REPORT_DATA = [
  {
    title: '创作指导摘要',
    category: '写作指导',
    meta: '写作指导',
    insight: '当前卷需要强化主角动机转折，建议在第三章加入外部压力事件，以提升节奏张力。',
    detail: '通过对已写 127 章的节奏曲线分析，发现第 3 章、第 11 章和第 22 章的爽点密度偏低。\n\n建议：\n1. 在第 3 章末尾加入“黑塔提前降临”的伏笔；\n2. 让主角在资源分配上与队友产生冲突；\n3. 每章结尾保留一个未解答的悬念。'
  },
  {
    title: '跨书合成发现',
    category: '跨书对比',
    meta: '跨书对比',
    insight: '末世题材中“团体生存”与“种田”组合出现频率最高，可作为下一卷世界观锚点。',
    detail: '对 33 本末世/无限流头部作品进行标签共现分析后发现：\n\n- 高商业分作品中，76% 包含“团体生存”标签；\n- 其中又有 58% 同时包含“种田/囤货”标签；\n- 该组合在 30-60 万字区间表现最佳。\n\n结论：第二卷可围绕“据点建设 + 资源管理”展开。'
  },
  {
    title: '技法卡片库',
    category: '技法提炼',
    meta: '技法提炼',
    insight: '已提炼 156 张技法卡片，其中“悬念铺设”类占比 23%，可直接插入写作指导。',
    detail: '技法卡片分类统计：\n\n- 悬念铺设：36 张\n- 情绪渲染：28 张\n- 节奏控制：24 张\n- 人物塑造：31 张\n- 世界观揭示：22 张\n- 对话技巧：15 张\n\n推荐在下一卷优先使用“悬念铺设”类卡片。'
  },
  {
    title: '第127章节奏分析',
    category: '节奏拆解',
    meta: '节奏拆解',
    insight: '本章爽点密度偏低，结尾悬念不足。建议增加一个突发事件或情绪反转。',
    detail: '节奏曲线显示本章前 70% 推进平缓，高潮出现在 85% 位置但收尾过快。\n\n建议：\n1. 在 60% 处加入一次小型冲突；\n2. 结尾保留一个未解悬念；\n3. 减少环境描写，增加动作与对话。'
  },
  {
    title: '主角成长弧线',
    category: '人物分析',
    meta: '人物分析',
    insight: '主角从被动求生到主动领导过渡自然，但中期缺乏一次重大失败来加深人物厚度。',
    detail: '主角动机转变分析：\n\n- 第一阶段（1-60章）：被动求生，以自保为主；\n- 第二阶段（61-120章）：开始承担责任，但决策仍偏保守；\n- 第三阶段（121-180章）：需要一次信任崩塌来推动成熟。\n\n建议在第 140 章左右设计一次“误判导致队友牺牲”的情节。'
  },
  {
    title: '末世题材热度趋势',
    category: '市场分析',
    meta: '市场分析',
    insight: '“丧尸+种田”“异能+团队”两类开篇完读率最高，可作为新书开篇参考。',
    detail: '基于 28 本末世题材头部作品的开篇分析：\n\n- 丧尸+种田：完读率均值 18.3%；\n- 异能+团队：完读率均值 16.7%；\n- 重生囤货：完读率均值 14.2%；\n- 独行求生：完读率均值 11.5%。\n\n结论：新书开篇优先考虑“危机+团队建设”双线并进。'
  }
];
let currentReportIndex = null;






let importedReportData = null;
function showLoading() {
  const overlay = $('#loading-overlay');
  if (overlay) overlay.classList.add('show');
}

function hideLoading() {
  const overlay = $('#loading-overlay');
  if (overlay) overlay.classList.remove('show');
}







let WRITING_CURRENT_CHAPTER = 127;

const WRITING_CHAPTER_TITLES = {
  1: '考场异变',
  2: '初次模拟',
  3: '能力觉醒',
  13: '商场据点',
  26: '深夜突围',
  27: '暴雨前的寂静',
  126: '黑塔来信',
  127: '暴雨前的寂静',
  128: '内部听证',
  129: '临时同盟',
  130: '零号标记'
};

function getChapterTitle(ch) {
  return WRITING_CHAPTER_TITLES[ch] || ('第 ' + ch + ' 章');
}




const DESIGN_DATA = {
  volumes: [
    { title: '第一卷', range: '1-60章', subtitle: '灾变初临', summary: '主角在高考考场遭遇末日降临，被迫在混乱中保护同学并觉醒模拟器能力。', tags: ['觉醒','逃亡','校园'] },
    { title: '第二卷', range: '61-120章', subtitle: '废墟秩序', summary: '幸存者小队在废弃商场建立据点，主角通过模拟预判危险，逐步确立领导地位。', tags: ['据点','团体','资源'] },
    { title: '第三卷', range: '121-180章', subtitle: '暗流涌动', summary: '外界势力觊觎据点资源，内部出现分歧，主角面临信任与利益的考验。', tags: ['内讧','权谋','冲突'] },
    { title: '第四卷', range: '181-240章', subtitle: '进化之路', summary: '病毒二次变异，人类与怪物同步进化，主角团队被迫向更危险的城市核心进发。', tags: ['进化','副本','Boss'] },
    { title: '第五卷', range: '241-300章', subtitle: '新纪元', summary: '真相揭露，末日竟是高等文明的筛选试验，主角必须做出拯救还是逃离的抉择。', tags: ['真相','决战','终章'] }
  ],
  chapters: [
    { title: '第一章', goal: '建立末日氛围', conflict: '主角与监考老师对峙', result: '觉醒模拟器，逃离考场', scenes: ['考场混乱','首次模拟','能力觉醒'] },
    { title: '第二章', goal: '展示世界规则', conflict: '如何保护同学突围', result: '组建临时小队', scenes: ['丧尸出现','路线选择','救人'] },
    { title: '第三章', goal: '引入外部压力', conflict: '食物与信任危机', result: '占领小卖部作为据点', scenes: ['物资搜寻','冲突爆发','决策'] }
  ],
  world: {
    core: '末日模拟器：全球进入72小时轮回，每次死亡保留记忆碎片。',
    powers: '模拟点、天赋树、死亡惩罚、情报熵。',
    factions: [
      { name: '黑塔', desc: '神秘组织，掌控轮回核心。' },
      { name: '避难所', desc: '官方幸存者聚集地。' },
      { name: '拾荒者', desc: '游离于秩序之外的幸存者。' },
      { name: '清理人', desc: '黑塔下属的执行部队。' }
    ]
  },
  characters: [
    { name: '林默', role: '主角', desc: '冷静果断，拥有末日模拟器，能在梦中预演未来4小时。' },
    { name: '苏婉', role: '女主', desc: '医学生，擅长急救与毒理分析，团队医疗核心。' },
    { name: '老K', role: '导师', desc: '退役特种兵，传授生存技巧，是主角初期的武力依靠。' }
  ]
};

let designEditType = null;
let designEditIndex = null;



















function fmtSize(n) {
  if (n >= 1024) return (n / 1024).toFixed(1) + ' MB';
  return n + ' KB';
}

function filterTasks(filter) {
  taskFilter = filter;
  renderTasks();
}




function statusLabel(s) {
  return { queued: '排队中', running: '进行中', completed: '已完成', failed: '失败' }[s] || s;
}




function closeModalOnOverlay(e) {
  if (e.target === e.currentTarget) closeTaskModal();
}




const TASK_TYPE_LABELS = {
  full_pipeline: '完整管线',
  rhythm: '节奏分析',
  technique: '技法提炼',
  summary: '全文摘要',
  cross: '跨书对比',
  cards: '技法卡片',
  instructions: '逐章指令',
};






function markDraftUnsaved() {
  const el = $('#writing-save-status');
  if (el) el.textContent = '未保存';
}

function markDraftSaved() {
  const el = $('#writing-save-status');
  if (el) el.textContent = '已保存';
}


function navigateTo(page) {
  navigate(page);
}

function refreshReports() {
  showToast('报告已刷新');
  loadApiData();
}




let projectList = [];

async function loadProjectList() {
  const res = await ProjectAPI.list(true);
  projectList = (res && res.projects) ? res.projects : [];
  return projectList;
}

async function switchProject(projectId) {
  if (!projectId) return;
  const project = await ProjectAPI.get(projectId);
  if (project && project.meta) {
    saveProject(project);
    showToast('已切换到 ' + project.meta.title);
    renderDashboardProject();
    await populateProjectSwitcher();
  } else {
    showToast('切换作品失败');
  }
}

async function populateProjectSwitcher() {
  await loadProjectList();
  const select = $('#project-select');
  if (!select) return;
  select.innerHTML = '<option value="">切换作品</option>' +
    projectList.map((p) => '<option value="' + p.id + '"' + (currentProject && p.id === currentProject.id ? ' selected' : '') + '>' + (p.title || '未命名') + '</option>').join('');
}










// ============================================================
// 逐章指令面板 — 加载真实后端指令数据
// ============================================================
let instructionsLoaded = false;

async function initWritingTocScroll() {
  const toc = $('#writing-toc');
  if (!toc) return;
  const current = toc.querySelector('.toc-chapter.current');
  if (current) {
    current.scrollIntoView({ block: 'start', behavior: 'auto' });
  }
}





function toggleMobileSidebar() {
  appShell.classList.toggle('mobile-sidebar-open');
}

function closeMobileSidebar() {
  appShell.classList.remove('mobile-sidebar-open');
}

document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && document.body.classList.contains('focus-mode')) {
    document.body.classList.remove('focus-mode');
    const btn = $('#focus-toggle');
    if (btn) btn.textContent = '专注模式';
    closeFocusAiPanel();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if ($('#focus-ai-panel').classList.contains('open')) {
      closeFocusAiPanel();
      return;
    }
    if (document.body.classList.contains('focus-mode')) {
      toggleFocus();
      return;
    }
    if ($('#create-project-modal').classList.contains('open')) {
      closeCreateProjectModal();
      return;
    }
    closeReportDetail();
    closeTaskModal();
    closeDetail();
    closeMobileSidebar();
  }
  if (e.ctrlKey && e.key.toLowerCase() === 's') {
    e.preventDefault();
    saveDraft();
  }
  if (e.ctrlKey && e.key.toLowerCase() === 'b') {
    e.preventDefault();
    toggleFocus();
  }
  if (e.ctrlKey && e.shiftKey && e.key === 'C') {
    e.preventDefault();
    togglePanel('self-check');
  }
});


// ============================================================
// 场景参考面板 — 调用后端场景搜索 API
// ============================================================


// ============================================================
// 前端操作日志上报（在关键操作处调用）
// ============================================================
function reportOperation(action, detail) {
  detail = detail || {};
  apiPost('/api/logs/operations', { action: action, detail: detail }).catch(function() { /* 静默失败，不影响主流程 */ });
}

// init() 在 index.html 中由 js/main.js 加载后统一调用

