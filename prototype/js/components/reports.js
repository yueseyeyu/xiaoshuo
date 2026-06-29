"use strict";

function renderReports() {
  const grid = $('#report-grid');
  if (!grid) return;
  const apiDataRef = (typeof appState !== 'undefined' && appState.apiData) || {};
  const guidance = apiDataRef.guidance || {};
  const techniques = apiDataRef.techniques || {};
  const diagnosis = apiDataRef.diagnosis || {};
  const stats = apiDataRef.stats || {};

  // 动态生成报告卡片：优先使用 API 数据，否则用静态数据
  const reports = [];

  // 1. 创作指导摘要（来自 API）
  if (guidance.guidance) {
    const firstGuidance = guidance.guidance ? guidance.guidance[0] : '';
    reports.push({
      type: 'writing',
      dotClass: 'green',
      title: '创作指导摘要',
      category: '写作指导',
      insight: (firstGuidance || '').substring(0, 100) || '从 ' + (stats.analyzed_books || 30) + ' 本末世小说中提炼的创作指导',
      meta: (stats.genre_focus || '末世') + '题材 · ' + (stats.analyzed_chapters || 0) + ' 章分析',
      tags: ['写作', '指导'],
      detail: (guidance.guidance || []).join('\n\n'),
    });
  } else {
    reports.push(REPORT_DATA[0]);
  }

  // 2. 跨书合成发现
  if (guidance.dominant_conflicts) {
    const topConflict = guidance.dominant_conflicts[0];
    reports.push({
      type: 'market',
      dotClass: 'blue',
      title: '跨书合成发现', category: '跨书对比',
      insight: '末世题材中"' + topConflict.type + '"类冲突占比 ' + topConflict.pct + '%，是主要叙事驱动力',
      meta: '覆盖 ' + (stats.analyzed_books || 30) + ' 本书 · ' + (guidance.arc_distribution ? '已分析弧线分布' : ''),
      tags: ['市场', '末世'],
      detail: '主导冲突类型：\n' + (guidance.dominant_conflicts || []).map(c => '- ' + c.type + ': ' + c.pct + '%').join('\n'),
    });
  } else {
    reports.push(REPORT_DATA[1]);
  }

  // 3. 技法卡片库
  if (techniques.sections) {
    reports.push({
      type: 'tech',
      dotClass: 'amber',
      title: '写作技法总纲', category: '技法提炼',
      insight: '包含 ' + techniques.sections.length + ' 个技法模块：' + techniques.sections.slice(0, 3).join('、') + '等',
      meta: techniques.sections.length + ' 个模块',
      tags: ['技法', '卡片'],
      detail: '技法模块列表：\n' + techniques.sections.map(s => '- ' + s).join('\n'),
    });
  } else {
    reports.push(REPORT_DATA[2]);
  }

  // 4. 深度诊断
  if (diagnosis && !diagnosis.error && Object.keys(diagnosis).length > 0) {
    reports.push({
      type: 'rhythm',
      dotClass: 'purple',
      title: '深度诊断对比', category: '节奏拆解',
      insight: 'Top vs Bottom 作品对比分析，揭示商业成功的关键因素',
      meta: '诊断数据已就绪',
      tags: ['诊断', '对比'],
      detail: formatDiagnosisReport(diagnosis),
    });
  } else {
    reports.push(REPORT_DATA[3]);
  }

  // 5. 角色指导
  if (guidance.character_guidance) {
    reports.push({
      type: 'character',
      dotClass: 'green',
      title: '角色创作指导', category: '人物分析',
      insight: (guidance.character_guidance || '').substring(0, 100),
      meta: stats.genre_focus || '末世',
      tags: ['人物', '角色'],
      detail: guidance.character_guidance || '',
    });
  } else {
    reports.push(REPORT_DATA[4]);
  }

  // 6. 钩子基准
  const hookBenchmark = guidance.opening_hook_benchmark;
  if (hookBenchmark != null) {
    reports.push({
      type: 'market',
      dotClass: 'blue',
      title: '开篇钩子基准',
      insight: '末世题材开篇平均钩子密度 ' + hookBenchmark + ' 个/千字，作为写作参考基准',
      meta: (stats.analyzed_books || 30) + ' 本样本',
      tags: ['市场', '趋势'],
      detail: '开篇钩子基准：' + hookBenchmark + ' 个/千字\n' + (guidance.hook_rule || ''),
    });
  } else {
    reports.push(REPORT_DATA[5]);
  }

  // 渲染报告卡片
  grid.innerHTML = reports.map((r, idx) => {
    const tagsHtml = (r.tags || []).map(t => '<span class="report-tag">' + escapeHtml(t) + '</span>').join('');
    return '<div class="report-card" data-report-type="' + escapeHtml(r.type || '') + '" onclick="openReportDetail(' + idx + ')">' +
      '<div class="report-header"><span class="lifecycle-dot ' + escapeHtml(r.dotClass || '') + '"></span><h3>' + escapeHtml(r.title || '') + '</h3></div>' +
      '<p class="report-insight">' + escapeHtml(r.insight || '') + '</p>' +
      '<div class="report-meta"><span>' + escapeHtml(r.meta || '') + '</span>' +
      '<div class="report-tags">' + tagsHtml + '</div></div>' +
      '</div>';
  }).join('');

  // 更新计数
  const countEl = $('#report-count');
  if (countEl) countEl.textContent = '共 ' + reports.length + ' 份报告';

  // 同步更新 REPORT_DATA 以支持详情弹窗
  window._DYNAMIC_REPORTS = reports;

  // 更新侧边栏统计
  const sidebarStats = $('#report-sidebar-stats');
  if (sidebarStats) {
    sidebarStats.innerHTML = reports.map(r => {
      return '<div class="summary-row"><span>' + escapeHtml(r.title || '') + '</span><span class="summary-row-value">' + escapeHtml(r.meta || '') + '</span></div>';
    }).join('');
  }

  // 更新后端数据统计
  const apiStats = apiDataRef.stats;
  if (apiStats && apiStats.analyzed_books) {
    const apiPanel = $('#report-api-stats');
    if (apiPanel) apiPanel.style.display = '';
    const rsBooks = $('#rs-api-books');
    if (rsBooks) rsBooks.textContent = apiStats.analyzed_books;
    const rsChapters = $('#rs-api-chapters');
    if (rsChapters) rsChapters.textContent = apiStats.analyzed_chapters;
    const rsGenre = $('#rs-api-genre');
    if (rsGenre) rsGenre.textContent = apiStats.genre_focus;
    const rsHook = $('#rs-api-hook');
    if (rsHook) rsHook.textContent = apiStats.hook_benchmark;
  }
}
function startAnalysisFromDetail() {
  if (selectedBookIndex === null) return;
  const b = DATA.books[selectedBookIndex];
  createTask('full_pipeline', '全部', [b.title]);
  navigate('disassembly');
  showToast('已创建分析任务');
}
function openReportDetail(idx) {
  currentReportIndex = idx;
  const reports = getCurrentReports();
  const r = reports[idx];
  if (!r) return;
  $('#report-detail-title').textContent = r.title;
  let extraContent = '';
  if (r.category === '节奏拆解') {
    extraContent = '<div class="report-detail-field"><label>节奏曲线</label><div class="rhythm-curve" id="rhythm-curve-' + idx + '"><canvas id="rhythm-canvas-' + idx + '"></canvas></div></div>';
  }
  if (r.category === '技法提炼') {
    extraContent = '<div class="report-detail-field"><label>技法卡片</label><div class="technique-grid" id="technique-grid-' + idx + '"></div></div>';
  }
  if (r.category === '跨书对比') {
    extraContent = '<div class="report-detail-field"><label>对比数据</label><div class="cross-book-data" id="cross-book-data-' + idx + '"></div></div>';
  }
  $('#report-detail-body').innerHTML =
    '<div class="report-detail-field"><label>核心洞察</label><textarea id="report-insight-edit">' + escapeHtml(r.insight || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>详细分析</label><textarea id="report-detail-edit">' + escapeHtml(r.detail || '') + '</textarea></div>' +
    extraContent +
    '<div class="report-ai-suggestions" id="report-ai-box" style="display:none"></div>';
  $('#report-detail').classList.add('open');
  $('#report-detail-overlay').classList.add('open');
  // 延迟渲染图表
  setTimeout(() => {
    if (r.category === '节奏拆解') drawRhythmCurve(idx);
    if (r.category === '技法提炼') renderTechniqueCards(idx);
    if (r.category === '跨书对比') renderCrossBookData(idx);
  }, 100);
}
function closeReportDetail() {
  const detail = $('#report-detail');
  const overlay = $('#report-detail-overlay');
  if (detail) detail.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
  currentReportIndex = null;
}
function aiSuggestReport() {
  const box = $('#report-ai-box');
  if (!box) return;
  box.style.display = 'block';
  box.innerHTML = '<h4>AI 建议</h4><ul>' +
    '<li>在第三章加入“黑塔提前出现”的伏笔，强化外部压力。</li>' +
    '<li>让主角在资源分配上与队友产生冲突，制造内在张力。</li>' +
    '<li>每章结尾保留一个未解答的悬念，提升追读率。</li>' +
    '</ul>';
}
function getCurrentReports() {
  return window._DYNAMIC_REPORTS && window._DYNAMIC_REPORTS.length ? window._DYNAMIC_REPORTS : REPORT_DATA;
}
function saveReportEdit() {
  if (currentReportIndex === null) return;
  const reports = getCurrentReports();
  reports[currentReportIndex].insight = $('#report-insight-edit').value;
  reports[currentReportIndex].detail = $('#report-detail-edit').value;
  showToast('报告已保存');
  closeReportDetail();
}
function drawRhythmCurve(idx) {
  const canvas = document.getElementById('rhythm-canvas-' + idx);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 200 * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = '200px';
  ctx.scale(dpr, dpr);
  const w = rect.width, h = 200, pad = 20;
  const points = [];
  for (let i = 0; i < 30; i++) {
    points.push(0.3 + 0.4 * Math.sin(i * 0.4) + 0.2 * Math.cos(i * 0.25) + 0.1 * Math.random());
  }
  ctx.strokeStyle = 'var(--accent)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((v, i) => {
    const x = pad + (w - 2 * pad) * i / (points.length - 1);
    const y = h - pad - v * (h - 2 * pad);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = 'rgba(245,158,11,0.1)';
  ctx.lineTo(w - pad, h - pad);
  ctx.lineTo(pad, h - pad);
  ctx.closePath();
  ctx.fill();
}
function renderTechniqueCards(idx) {
  const grid = document.getElementById('technique-grid-' + idx);
  if (!grid) return;
  const techniques = [
    { name: '悬念锚定', from: '《末日蟑螂》', excerpt: '每章结尾制造1个未解答的问题，读者留存率提升37%' },
    { name: '时间压缩', from: '《黑暗血时代》', excerpt: '关键场景使用短句+短段落，制造紧迫感' },
    { name: '反转预埋', from: '《末日轮盘》', excerpt: '在第3章就埋下第15章的反转线索' },
    { name: '对话张力', from: '《废土》', excerpt: '角色对话中隐含权力博弈，每句对话推进情节' },
  ];
  grid.innerHTML = techniques.map(t =>
    '<div class="technique-card">' +
    '<h4>' + t.name + '</h4>' +
    '<div class="tech-from">来源：' + t.from + '</div>' +
    '<div class="tech-excerpt">' + t.excerpt + '</div>' +
    '</div>'
  ).join('');
}
function renderCrossBookData(idx) {
  const container = document.getElementById('cross-book-data-' + idx);
  if (!container) return;
  container.innerHTML =
    '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
    '<tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:6px">维度</th><th style="text-align:left;padding:6px">《末日蟑螂》</th><th style="text-align:left;padding:6px">《黑暗血时代》</th><th style="text-align:left;padding:6px">你的作品</th></tr>' +
    '<tr style="border-bottom:1px solid var(--border)"><td style="padding:6px">节奏密度</td><td style="padding:6px">高</td><td style="padding:6px">中</td><td style="padding:6px;color:var(--accent)">中高</td></tr>' +
    '<tr style="border-bottom:1px solid var(--border)"><td style="padding:6px">悬念频率</td><td style="padding:6px">3.2/章</td><td style="padding:6px">2.1/章</td><td style="padding:6px;color:var(--accent)">2.8/章</td></tr>' +
    '<tr style="border-bottom:1px solid var(--border)"><td style="padding:6px">战斗占比</td><td style="padding:6px">35%</td><td style="padding:6px">28%</td><td style="padding:6px;color:var(--accent)">31%</td></tr>' +
    '</table>';
}
function importReportToWriting() {
  if (currentReportIndex == null) return;
  const reports = getCurrentReports();
  const r = reports[currentReportIndex];
  importedReportData = { title: r.title, insight: r.insight, detail: r.detail, importedAt: new Date().toLocaleString() };
  closeReportDetail();
  showToast('已导入写作辅助');
  renderImportedReport();
}
function formatDiagnosisReport(data) {
  const lines = [];
  lines.push('深度诊断数据概览：');
  lines.push('');
  if (data.summary) {
    lines.push('【摘要】');
    lines.push(data.summary);
    lines.push('');
  }
  if (data.top_vs_bottom && typeof data.top_vs_bottom === 'object') {
    lines.push('【Top vs Bottom 对比】');
    Object.entries(data.top_vs_bottom).forEach(([k, v]) => {
      lines.push('- ' + k + ': ' + v);
    });
    lines.push('');
  }
  if (data.insights && Array.isArray(data.insights)) {
    lines.push('【关键洞察】');
    data.insights.forEach(item => lines.push('- ' + item));
    lines.push('');
  }
  if (data.recommendations && Array.isArray(data.recommendations)) {
    lines.push('【优化建议】');
    data.recommendations.forEach(item => lines.push('- ' + item));
    lines.push('');
  }
  return lines.join('\n') || '诊断数据已加载，暂无结构化摘要。';
}
function filterReports(type) {
  $$('.report-filter').forEach(b => b.classList.toggle('active', b.dataset.reportFilter === type));
  const cards = $$('#report-grid .report-card');
  let visible = 0;
  cards.forEach(c => {
    const show = type === 'all' || c.dataset.reportType === type;
    c.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  const countEl = $('#report-count');
  if (countEl) countEl.textContent = '共 ' + visible + ' 份报告';
}
function regenerateReport(idx, event) {
  if (event) event.stopPropagation();
  showToast('正在重新生成报告 #' + (idx + 1));
}
