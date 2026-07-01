"use strict";

// v9: 管线实时轮询
var _pipelinePollTimer = null;
function startPipelinePolling() {
  if (_pipelinePollTimer) return;
  _pipelinePollTimer = setInterval(async function() {
    var dashActive = $('#page-dashboard') && $('#page-dashboard').classList.contains('active');
    if (!dashActive) { stopPipelinePolling(); return; }
    var pipelineEl = $('#pipeline-station');
    if (!pipelineEl || pipelineEl.style.display === 'none') return;
    var { ok, data } = await apiGet('/api/progress', 5000);
    if (!ok || !data) return;
    if (!data.running) {
      pipelineEl.style.display = 'none';
      stopPipelinePolling();
      return;
    }
    var stage = data.pipeline_stage || null;
    var state = data.startup_state || {};
    var pipelineSub = $('#pipeline-header-sub');
    var pipelineStatusText = $('#pipeline-status-text');
    var pipelineTrack = $('#pipeline-track');
    if (pipelineSub) pipelineSub.textContent = (stage && stage.current_task) || state.message || '分析运行中';
    if (pipelineStatusText) pipelineStatusText.textContent = state.status || 'running';
    if (pipelineTrack) pipelineTrack.innerHTML = renderPipelineStageViz(stage, state);
  }, 3000);
}
function stopPipelinePolling() {
  if (_pipelinePollTimer) { clearInterval(_pipelinePollTimer); _pipelinePollTimer = null; }
}

// ============================================================
// 工作台 / 项目卡片
// ============================================================
function renderDashboardProject() {
  const hasProject = !!currentProject;
  const hero = $('#hero-has-project');
  const empty = $('#hero-empty-state');
  const sidebar = $('.dashboard-sidebar');
  const pipeline = $('.pipeline-station');
  const section = $('.dashboard-section');
  const kpiRow = $('.library-kpi-row');
  const stageBar = $('#creative-stage-bar');
  const workstation = $('#dashboard-workstation');
  if (hero) hero.style.display = hasProject ? '' : 'none';
  if (empty) empty.style.display = hasProject ? 'none' : '';
  if (sidebar) sidebar.style.display = hasProject ? '' : 'none';
  if (kpiRow) kpiRow.style.display = hasProject ? '' : 'none';
  if (workstation) workstation.style.gridTemplateColumns = hasProject ? '' : '1fr';
  const exitDemoBtn = $('#exit-demo-btn');
  if (exitDemoBtn) exitDemoBtn.style.display = (hasProject && isDemoProject(currentProject)) ? '' : 'none';
  const pageTitle = $('#dashboard-page-title');
  const fab = $('#continue-writing-fab');
  const fabMeta = $('#fab-meta');
  if (hasProject) {
    if (pageTitle) pageTitle.textContent = '工作台· ' + (currentProject.title || '未命名作品');
    $('#hero-title').textContent = currentProject.title || '未命名作品';
    $('#hero-greeting').textContent = greetingByHour() + '，' + (currentProject.author || '作者');
    $('#hero-volumes').textContent = currentProject.volumes || 0;
    $('#hero-chapters').textContent = currentProject.totalChapters || 0;
    $('#hero-genre').textContent = currentProject.genre || '未设置';
    $('#hero-stat-chapters').textContent = currentProject.writtenChapters || 0;
    const progress = currentProject.totalChapters ? Math.round((currentProject.writtenChapters || 0) / currentProject.totalChapters * 100) : 0;
    $('#hero-stat-progress').textContent = progress + '%';
    $('#hero-stat-cards').textContent = currentProject.cards || 0;
    $('#dashboard-subtitle').textContent = currentProject.genre ? (currentProject.genre + ' · ' + (currentProject.writtenChapters || 0) + '/' + (currentProject.totalChapters || 0) + ' 章') : '项目信息待完善';
    if (fab) fab.style.display = '';
    if (fabMeta) fabMeta.textContent = '第' + (currentProject.writtenChapters + 1 || 1) + '章';
  } else {
    if (pageTitle) pageTitle.textContent = '工作台';
    $('#dashboard-subtitle').textContent = '当前无进行中的项目';
    if (fab) fab.style.display = 'none';
  }
}

// greetingByHour 已在 utils.js 中定义，此处不再重复

// ============================================================
// v8.5: 工作台动态数据加载 — 从后端获取真实数据
// ============================================================
async function loadDashboardKPIs() {
  // 1. 书库统计
  var booksEl = $('#dash-kpi-books');
  var genresEl = $('#dash-kpi-genres');
  var cardsEl = $('#dash-kpi-cards');
  var statusEl = $('#dash-kpi-status');
  if (booksEl) {
    var { ok, data } = await apiGet('/api/books', 15000);
    if (ok && data) {
      if (booksEl) booksEl.textContent = data.count || 0;
      if (genresEl) genresEl.textContent = (data.genres || []).length;
    }
  }
  // 2. 技法卡片数
  if (cardsEl) {
    var { ok: okTc, data: tc } = await apiGet('/api/reports/overview', 15000);
    if (okTc && tc) {
      cardsEl.textContent = (tc.technique_cards || []).length;
      var ra = tc.rhythm_audit || {};
      if (statusEl) statusEl.textContent = ra.passed > 0 ? ra.passed + '/' + ra.total_books + ' 通过' : '空闲';
    }
  }
  // 3. 分析进度
  var pipelineEl = $('#pipeline-station');
  var pipelineSub = $('#pipeline-header-sub');
  var pipelineStatusText = $('#pipeline-status-text');
  var pipelineTrack = $('#pipeline-track');
  if (pipelineEl) {
    var { ok: okP, data: progress } = await apiGet('/api/progress');
    if (okP && progress && progress.running) {
      pipelineEl.style.display = '';
      var state = progress.startup_state || {};
      var stage = progress.pipeline_stage || null;
      if (pipelineSub) pipelineSub.textContent = (stage && stage.current_task) || state.message || '分析运行中';
      if (pipelineStatusText) pipelineStatusText.textContent = state.status || 'running';
      if (pipelineTrack) {
        pipelineTrack.innerHTML = renderPipelineStageViz(stage, state);
      }
      startPipelinePolling();
    } else {
      pipelineEl.style.display = 'none';
      stopPipelinePolling();
    }
  }
  // 4. 写作进度
  var progressCard = $('#dash-writing-progress-card');
  if (progressCard && currentProject) {
    progressCard.style.display = '';
    var pct = currentProject.totalChapters ? Math.round((currentProject.writtenChapters || 0) / currentProject.totalChapters * 100) : 0;
    var pctEl = $('#dash-progress-pct');
    var chEl = $('#dash-progress-chapter');
    var infoEl = $('#dash-progress-info');
    if (pctEl) pctEl.textContent = pct + '%';
    if (chEl) chEl.textContent = '第' + (currentProject.writtenChapters + 1 || 1) + '章';
    if (infoEl) infoEl.textContent = (currentProject.writtenChapters || 0) + '/' + (currentProject.totalChapters || 0) + ' 章';
  }
  // 5. 待处理任务
  var tasksEl = $('#dash-pending-tasks');
  if (tasksEl && typeof tasks !== 'undefined') {
    var active = tasks.filter(function(t) { return t.status === 'queued' || t.status === 'running'; });
    if (active.length === 0) {
      tasksEl.innerHTML = '<div class="mini-task"><span class="mini-status pending"></span><span class="mini-task-name">暂无任务</span><span class="mini-progress"></span></div>';
    } else {
      tasksEl.innerHTML = active.slice(0, 3).map(function(t) {
        return '<div class="mini-task"><span class="mini-status ' + t.status + '"></span><span class="mini-task-name">' + escapeHtml(t.typeLabel || t.type || '任务') + '</span><span class="mini-progress">' + (t.progress || 0) + '%</span></div>';
      }).join('');
    }
  }
}

function createProject() {
  $('#cp-title').value = '';
  $('#cp-genre').value = '末世';
  $('#cp-volumes').value = 5;
  $('#cp-chapters').value = 300;
  $('#cp-desc').value = '';
  $('#create-project-modal').classList.add('open');
}

function closeCreateProjectModal() {
  const modal = $('#create-project-modal');
  if (modal) modal.classList.remove('open');
}

async function confirmCreateProject() {
  const title = $('#cp-title').value.trim();
  if (!title) { showToast('请输入作品名称'); return; }
  const genre = $('#cp-genre').value || '末世';
  const volumes = parseInt($('#cp-volumes').value) || 5;
  const chapters = parseInt($('#cp-chapters').value) || 300;
  const result = await ProjectAPI.create({
    meta: {
      title: '《' + title.replace(/《|》/g, '') + '》',
      author: '作者',
      genre: genre,
      volumes_count: volumes,
      total_chapters: chapters,
      written_chapters: 0,
      summary: '',
    }
  });
  if (result && result.project) {
    saveProject(result.project);
    closeCreateProjectModal();
    showToast('已创建作品 ' + title);
    // 创建后引导
    setTimeout(() => {
      showToast('下一步：在书库中导入参考书，或在设计页规划粗纲');
    }, 2800);
  } else {
    showToast('创建作品失败');
  }
}

async function loadDemoProject() {
  clearToasts();
  showToast('正在加载示例项目，请稍候...', 0);
  try {
    // 优先复用已存在的示例项目，避免重复创建
    const list = await ProjectAPI.list({ include_demo: true });
    const demo = list && list.projects && list.projects.find(p => p.is_demo);
    if (demo) {
      const project = await ProjectAPI.get(demo.id);
      clearToasts();
      if (project && project.meta) {
        saveProject(project);
        showToast('已加载示例项目');
        return;
      }
    }
    // 没有示例项目时才创建
    const result = await ProjectAPI.createFromDemo();
    clearToasts();
    if (result && result.project) {
      saveProject(result.project);
      showToast('已加载示例项目');
    } else {
      showToast('加载示例项目失败：接口未返回项目数据');
    }
  } catch (e) {
    clearToasts();
    console.error('loadDemoProject failed', e);
    showToast('加载示例项目失败：' + (e.message || '网络超时'));
  }
}

async function exitDemoProject() {
  const demoId = currentProject && currentProject.id;
  setCurrentProject(null);
  if (demoId) {
    try { await ProjectAPI.delete(demoId); } catch (e) { console.error('delete demo failed', e); }
  }
  showToast('已退出示例项目');
}

async function stopAnalysis() {
  var { ok, data } = await apiPost('/api/stop', {});
  if (ok && data) showToast(data.message || '已停止');
  loadDashboardKPIs();
}

// v9: 动态管线阶段可视化
var PIPELINE_STAGES = [
  { key: 'chunk', label: '分块', icon: '\u2702\uFE0F' },
  { key: 'recursive_summarize', label: '递归摘要', icon: '\u{1F4DC}' },
  { key: 'rhythm', label: '节奏分析', icon: '\u{1F3B5}' },
  { key: 'emotion', label: '情绪标注', icon: '\u{1F496}' },
  { key: 'conflict', label: '冲突检测', icon: '\u26A1' },
  { key: 'pleasure', label: '爽点分析', icon: '\u{1F380}' },
  { key: 'synthesize', label: '综合输出', icon: '\u{1F4E6}' },
];

function renderPipelineStageViz(stage, state) {
  // 如果没有 stage 详情，显示简化版
  if (!stage) {
    var msg = (state && state.message) || '分析运行中';
    var pct = (state && state.progress) || 0;
    return '<div class="pipeline-simple">' +
      '<div class="pipeline-simple-msg">' + escapeHtml(msg) + '</div>' +
      '<div class="pipeline-simple-bar"><div class="pipeline-simple-fill" style="width:' + pct + '%"></div></div>' +
    '</div>';
  }

  var stageNum = stage.stage_num || 0;
  var totalStages = stage.total || PIPELINE_STAGES.length;
  var percent = stage.percent || 0;
  var currentKey = stage.stage || '';
  var currentBook = stage.current_book || '';
  var currentTask = stage.current_task || '';
  var status = stage.status || 'running';
  var completedBooks = stage.completed_books || [];

  // 构建阶段步骤条
  var stagesHtml = PIPELINE_STAGES.map(function(s, i) {
    var idx = i + 1;
    var cls = 'pending';
    if (idx < stageNum) cls = 'completed';
    else if (idx === stageNum) cls = status === 'error' ? 'error' : 'running';
    return '<div class="pipeline-step ' + cls + '">' +
      '<div class="pipeline-step-icon">' + s.icon + '</div>' +
      '<div class="pipeline-step-label">' + s.label + '</div>' +
    '</div>';
  }).join('');

  // 进度信息
  var progressPct = totalStages > 0 ? Math.round((stageNum - 1) / totalStages * 100 + percent / totalStages) : 0;
  var infoHtml = '<div class="pipeline-info-row">' +
    '<span class="pipeline-info-task">' + escapeHtml(currentTask || '处理中...') + '</span>' +
    (currentBook ? '<span class="pipeline-info-book">\u{1F4D6} ' + escapeHtml(currentBook) + '</span>' : '') +
    '<span class="pipeline-info-pct">' + progressPct + '%</span>' +
  '</div>';

  // 进度条
  var barHtml = '<div class="pipeline-progress-bar">' +
    '<div class="pipeline-progress-fill' + (status === 'running' ? ' animated' : '') + '" style="width:' + progressPct + '%"></div>' +
  '</div>';

  // 已完成书籍
  var booksHtml = '';
  if (completedBooks.length > 0) {
    booksHtml = '<div class="pipeline-completed-books">' +
      '<span class="pipeline-completed-label">已完成 (' + completedBooks.length + '):</span>' +
      completedBooks.slice(-5).map(function(b) { return '<span class="pipeline-book-chip">' + escapeHtml(b) + '</span>'; }).join('') +
    '</div>';
  }

  return '<div class="pipeline-stages-viz">' +
    '<div class="pipeline-steps-row">' + stagesHtml + '</div>' +
    barHtml +
    infoHtml +
    booksHtml +
  '</div>';
}
