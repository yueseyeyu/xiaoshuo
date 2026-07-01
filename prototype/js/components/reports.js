"use strict";

// ============================================================
// 报告页 — v8.4 重写
// 数据来源: /api/reports/overview (聚合真实数据，不再使用静态假数据)
// ============================================================

let _reportOverview = null;
let _reportCards = [];

async function loadReportOverview() {
  const { ok, data } = await apiGet('/api/reports/overview');
  if (ok && data) {
    _reportOverview = data;
    renderReports();
  } else {
    console.warn('[Reports] overview API unavailable');
    renderReportsEmpty();
  }
}

function renderReportsEmpty() {
  const grid = $('#report-grid');
  if (grid) {
    grid.innerHTML = '<div class="text-muted" style="padding:40px;text-align:center;">报告数据加载失败，请确认后端服务已启动</div>';
  }
}

function renderReports() {
  if (!_reportOverview) {
    loadReportOverview();
    return;
  }

  const ov = _reportOverview;
  const grid = $('#report-grid');
  if (!grid) return;

  const cards = [];

  // 1. 拆书总览
  const stats = ov.stats || {};
  const ra = ov.rhythm_audit || {};
  cards.push({
    type: 'overview',
    dotClass: 'green',
    title: '拆书总览',
    insight: stats.books + ' 本小说 · ' + fmtNumber(stats.chapters) + ' 章 · ' + fmtNumber(stats.words) + ' 字',
    meta: '节奏审计: ' + ra.passed + '/' + ra.total_books + ' 通过',
    tags: ['统计', '概览'],
    detail: buildOverviewDetail(ov),
  });

  // 2. 质量门控
  const qm = ov.quality_manifest || {};
  cards.push({
    type: 'quality',
    dotClass: qm.quarantined > 0 ? 'amber' : 'green',
    title: '质量门控报告',
    insight: '通过 ' + qm.approved + ' · 隔离 ' + qm.quarantined + ' · 淘汰 ' + qm.failed,
    meta: '商业分阈值 70 分',
    tags: ['质量', '门控'],
    detail: buildQualityDetail(ov),
  });

  // 3. 评分审计
  const sa = ov.score_audit || {};
  cards.push({
    type: 'score',
    dotClass: sa.status === 'PASS' ? 'green' : 'red',
    title: '评分审计',
    insight: '状态: ' + sa.status + ' · ' + (sa.total_books || 0) + ' 本已评分 · ' + (sa.outlier_count || 0) + ' 个异常',
    meta: sa.issues_count + ' 个问题',
    tags: ['评分', '审计'],
    detail: buildScoreDetail(ov),
  });

  // 4. 节奏分布
  const dist = ov.distributions || {};
  const paceDist = dist.pace || {};
  const paceTotal = Object.values(paceDist).reduce((a, b) => a + b, 0);
  const fastPct = paceTotal > 0 ? Math.round((paceDist.fast || 0) / paceTotal * 100) : 0;
  cards.push({
    type: 'rhythm',
    dotClass: 'purple',
    title: '节奏分布分析',
    insight: '快节奏 ' + fastPct + '% · 中节奏 ' + (paceTotal > 0 ? Math.round((paceDist.medium || 0) / paceTotal * 100) : 0) + '% · 慢节奏 ' + (paceTotal > 0 ? Math.round((paceDist.slow || 0) / paceTotal * 100) : 0) + '%',
    meta: stats.chapters + ' 章样本',
    tags: ['节奏', '分布'],
    detail: buildDistributionDetail(ov),
  });

  // 5. 爽点分布
  const pleasureDist = dist.pleasure || {};
  const pleasureTotal = Object.values(pleasureDist).reduce((a, b) => a + b, 0);
  const nonePct = pleasureTotal > 0 ? Math.round((pleasureDist.none || 0) / pleasureTotal * 100) : 0;
  cards.push({
    type: 'pleasure',
    dotClass: 'amber',
    title: '爽点分布分析',
    insight: '无爽点 ' + nonePct + '% · 小爽点 ' + (pleasureTotal > 0 ? Math.round((pleasureDist.minor || 0) / pleasureTotal * 100) : 0) + '% · 大爽点 ' + (pleasureTotal > 0 ? Math.round((pleasureDist.major || 0) / pleasureTotal * 100) : 0) + '%',
    meta: pleasureTotal + ' 章样本',
    tags: ['爽点', '分布'],
    detail: buildPleasureDetail(ov),
  });

  // 6. 技法卡片
  const tc = ov.technique_cards || [];
  const tcByCat = {};
  tc.forEach(c => { const cat = c.category || 'other'; tcByCat[cat] = (tcByCat[cat] || 0) + 1; });
  cards.push({
    type: 'tech',
    dotClass: 'blue',
    title: '技法卡片库',
    insight: tc.length + ' 张技法卡片 · ' + Object.keys(tcByCat).length + ' 个分类: ' + Object.keys(tcByCat).join('、'),
    meta: tc.length + ' 张卡片',
    tags: ['技法', '卡片'],
    detail: buildTechniqueCardsDetail(tc),
  });

  _reportCards = cards;

  // 渲染卡片
  grid.innerHTML = cards.map((r, idx) => {
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
  if (countEl) countEl.textContent = '共 ' + cards.length + ' 份报告';

  // 更新侧边栏
  const sidebarStats = $('#report-sidebar-stats');
  if (sidebarStats) {
    sidebarStats.innerHTML = cards.map(r => {
      return '<div class="summary-row"><span>' + escapeHtml(r.title || '') + '</span><span class="summary-row-value">' + escapeHtml(r.meta || '') + '</span></div>';
    }).join('');
  }

  // 更新后端数据统计面板
  const apiPanel = $('#report-api-stats');
  if (apiPanel && stats.books) {
    apiPanel.style.display = '';
    setText('rs-api-books', stats.books);
    setText('rs-api-chapters', fmtNumber(stats.chapters));
    setText('rs-api-genre', ov.genre || '末世');
    setText('rs-api-hook', ra.passed + '/' + ra.total_books + ' 通过');
  }
}

// ============================================================
// 详情内容构建器
// ============================================================

function buildOverviewDetail(ov) {
  const stats = ov.stats || {};
  const ra = ov.rhythm_audit || {};
  const lines = [];
  lines.push('【拆书总量】');
  lines.push('  小说: ' + (stats.books || 0) + ' 本');
  lines.push('  章节: ' + fmtNumber(stats.chapters || 0) + ' 章');
  lines.push('  总字数: ' + fmtNumber(stats.words || 0) + ' 字');
  lines.push('');
  lines.push('【节奏审计】');
  lines.push('  总计: ' + ra.total_books + ' 本');
  lines.push('  通过: ' + ra.passed + ' 本');
  lines.push('  警告: ' + ra.warnings + ' 本');
  lines.push('  失败: ' + ra.failed + ' 本');
  lines.push('');
  lines.push('【质量门控】');
  const qm = ov.quality_manifest || {};
  lines.push('  通过: ' + qm.approved);
  lines.push('  隔离: ' + qm.quarantined);
  lines.push('  淘汰: ' + qm.failed);
  return lines.join('\n');
}

function buildQualityDetail(ov) {
  const qm = ov.quality_manifest || {};
  const lines = [];
  lines.push('【质量门控结果】');
  lines.push('  通过 (approved): ' + qm.approved);
  lines.push('  隔离 (quarantined): ' + qm.quarantined);
  lines.push('  淘汰 (failed): ' + qm.failed);
  lines.push('');
  lines.push('说明: 商业分低于 70 分的作品被隔离，不参与跨书合成。');
  lines.push('当前隔离比例较高，说明大部分作品商业表现一般，');
  lines.push('但仍可用于节奏/技法分析。');
  return lines.join('\n');
}

function buildScoreDetail(ov) {
  const sa = ov.score_audit || {};
  const lines = [];
  lines.push('【评分审计】');
  lines.push('  状态: ' + (sa.status || 'N/A'));
  lines.push('  总书数: ' + (sa.total_books || 0));
  lines.push('  问题数: ' + (sa.issues_count || 0));
  lines.push('  异常书: ' + (sa.outlier_count || 0));
  lines.push('');
  const summary = sa.summary || {};
  if (Object.keys(summary).length > 0) {
    lines.push('【摘要】');
    Object.entries(summary).forEach(([k, v]) => {
      lines.push('  ' + k + ': ' + (typeof v === 'object' ? JSON.stringify(v) : v));
    });
  }
  return lines.join('\n');
}

function buildDistributionDetail(ov) {
  const dist = ov.distributions || {};
  const lines = [];
  
  // 节奏分布
  const pace = dist.pace || {};
  const paceTotal = Object.values(pace).reduce((a, b) => a + b, 0);
  lines.push('【节奏分布】 (总计 ' + paceTotal + ' 章)');
  Object.entries(pace).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => {
    const pct = paceTotal > 0 ? (v / paceTotal * 100).toFixed(1) : '0.0';
    lines.push('  ' + k + ': ' + v + ' (' + pct + '%)');
  });
  lines.push('');

  // 情绪分布
  const emotion = dist.emotion || {};
  const emoTotal = Object.values(emotion).reduce((a, b) => a + b, 0);
  lines.push('【情绪分布】 (总计 ' + emoTotal + ' 章)');
  Object.entries(emotion).sort((a, b) => b[1] - a[1]).slice(0, 10).forEach(([k, v]) => {
    const pct = emoTotal > 0 ? (v / emoTotal * 100).toFixed(1) : '0.0';
    lines.push('  ' + k + ': ' + v + ' (' + pct + '%)');
  });
  if (Object.keys(emotion).length > 10) {
    lines.push('  ... (共 ' + Object.keys(emotion).length + ' 种)');
  }
  return lines.join('\n');
}

function buildPleasureDetail(ov) {
  const dist = ov.distributions || {};
  const lines = [];
  const pleasure = dist.pleasure || {};
  const total = Object.values(pleasure).reduce((a, b) => a + b, 0);
  lines.push('【爽点分布】 (总计 ' + total + ' 章)');
  Object.entries(pleasure).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => {
    const pct = total > 0 ? (v / total * 100).toFixed(1) : '0.0';
    lines.push('  ' + k + ': ' + v + ' (' + pct + '%)');
  });
  lines.push('');
  lines.push('说明: "none" 表示本章无明确爽点，"minor" 为小爽点，');
  lines.push('"major" 为大爽点，"climax" 为高潮章。');
  return lines.join('\n');
}

function buildTechniqueCardsDetail(cards) {
  if (!cards || cards.length === 0) return '暂无技法卡片数据';
  const byCat = {};
  cards.forEach(c => {
    const cat = c.category || 'other';
    if (!byCat[cat]) byCat[cat] = [];
    byCat[cat].push(c);
  });
  const lines = [];
  lines.push('技法卡片共 ' + cards.length + ' 张，按分类:\n');
  Object.entries(byCat).forEach(([cat, items]) => {
    lines.push('【' + cat + '】(' + items.length + ' 张)');
    items.forEach(c => {
      lines.push('  - ' + (c.title || c.id || '?') + ': ' + (c.content || '').substring(0, 80));
    });
    lines.push('');
  });
  return lines.join('\n');
}

// ============================================================
// 报告详情弹窗
// ============================================================

let _currentReportIndex = null;

function openReportDetail(idx) {
  _currentReportIndex = idx;
  const r = _reportCards[idx];
  if (!r) return;
  const titleEl = $('#report-detail-title');
  if (titleEl) titleEl.textContent = r.title;
  const bodyEl = $('#report-detail-body');
  if (bodyEl) {
    bodyEl.innerHTML =
      '<div class="report-detail-field"><label>核心洞察</label><div class="report-detail-text">' + escapeHtml(r.insight || '') + '</div></div>' +
      '<div class="report-detail-field"><label>详细分析</label><pre class="report-detail-pre">' + escapeHtml(r.detail || '') + '</pre></div>';
  }
  const detail = $('#report-detail');
  const overlay = $('#report-detail-overlay');
  if (detail) detail.classList.add('open');
  if (overlay) overlay.classList.add('open');
}

function closeReportDetail() {
  const detail = $('#report-detail');
  const overlay = $('#report-detail-overlay');
  if (detail) detail.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
  _currentReportIndex = null;
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

function refreshReports() {
  showToast('正在刷新报告数据...');
  loadReportOverview();
}

function importReportToWriting() {
  if (_currentReportIndex == null) return;
  const r = _reportCards[_currentReportIndex];
  if (!r) return;
  importedReportData = { title: r.title, insight: r.insight, detail: r.detail, importedAt: new Date().toLocaleString() };
  closeReportDetail();
  showToast('已导入写作辅助');
  renderImportedReport();
}

function startAnalysisFromDetail() {
  if (selectedBookIndex === null) return;
  const b = DATA.books[selectedBookIndex];
  createTask('full_pipeline', '全部', [b.title]);
  navigate('disassembly');
  showToast('已创建分析任务');
}
