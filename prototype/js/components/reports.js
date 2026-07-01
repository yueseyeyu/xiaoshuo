"use strict";

// ============================================================
// 报告页 — v8.5 重写
// 数据来源: /api/reports/overview
// 新增: 创作建议引擎 / CSS迷你条形图 / 技法卡片展开 / 跨页联动
// ============================================================

let _reportOverview = null;
let _reportCards = [];
let _reportGenre = ''; // 动态初始化

function _resolveReportGenre() {
  // P0-1: 优先跟随当前项目题材，其次全局 currentGenre，最后 '全部'
  if (currentProject && currentProject.genre && currentProject.genre !== '未设置') {
    return currentProject.genre;
  }
  if (typeof currentGenre !== 'undefined' && currentGenre && currentGenre !== '全部') {
    return currentGenre;
  }
  return '全部';
}

async function loadReportOverview() {
  // P0-1: 首次加载时初始化题材
  if (!_reportGenre) _reportGenre = _resolveReportGenre();
  var apiGenre = _reportGenre === '全部' ? '' : _reportGenre;
  const { ok, data } = await apiGet('/api/reports/overview' + (apiGenre ? '?genre=' + encodeURIComponent(apiGenre) : ''));
  if (ok && data) {
    _reportOverview = data;
    renderReports();
  } else {
    console.warn('[Reports] overview API unavailable');
    renderReportsEmpty();
  }
}

async function initReportGenres() {
  if (!_reportGenre) _reportGenre = _resolveReportGenre();
  const { ok, data } = await apiGet('/api/books');
  if (ok && data && data.genres) {
    const select = $('#report-genre-select');
    if (select) {
      var options = '<option value="全部"' + (_reportGenre === '全部' ? ' selected' : '') + '>全部题材</option>';
      options += data.genres.map(function(g) {
        return '<option value="' + escapeHtml(g) + '"' + (g === _reportGenre ? ' selected' : '') + '>' + escapeHtml(g) + '</option>';
      }).join('');
      select.innerHTML = options;
    }
  }
}

function switchReportGenre() {
  const select = $('#report-genre-select');
  if (select) _reportGenre = select.value;
  showToast('正在加载 ' + _reportGenre + ' 报告数据...');
  loadReportOverview();
}

function renderReportsEmpty() {
  const grid = $('#report-grid');
  if (grid) {
    grid.innerHTML = '<div class="text-muted" style="padding:40px;text-align:center;">报告数据加载失败，请确认后端服务已启动</div>';
  }
}

// ============================================================
// P0-2: 创作建议引擎 — 把统计数字翻译成 actionable 洞察
// ============================================================

function generateAdvice(type, ov) {
  var genre = ov.genre || _reportGenre || '当前题材';
  var dist = ov.distributions || {};
  var stats = ov.stats || {};
  var advice = [];

  switch (type) {
    case 'overview':
      var ra = ov.rhythm_audit || {};
      if (ra.total_books > 0) {
        var passRate = Math.round(ra.passed / ra.total_books * 100);
        if (passRate < 60) {
          advice.push({ icon: 'warning', text: '节奏审计通过率仅 ' + passRate + '%，建议优先研究未通过作品的节奏问题，避免同类错误' });
        } else {
          advice.push({ icon: 'check', text: '节奏审计通过率 ' + passRate + '%，大部分作品节奏合格，可作为可靠参考' });
        }
      }
      if (stats.books > 0) {
        var avgChapters = Math.round(stats.chapters / stats.books);
        advice.push({ icon: 'info', text: genre + '平均每本 ' + avgChapters + ' 章、' + Math.round(stats.words / stats.books / 10000) + ' 万字，建议你的大纲控制在类似体量' });
      }
      break;

    case 'quality':
      var qm = ov.quality_manifest || {};
      var qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0);
      if (qmTotal > 0) {
        var qmRate = Math.round((qm.approved || 0) / qmTotal * 100);
        if (qmRate < 50) {
          advice.push({ icon: 'warning', text: '通过率仅 ' + qmRate + '%，部分拆书数据质量存疑，参考时注意交叉验证' });
        } else {
          advice.push({ icon: 'check', text: '数据质量良好（通过率 ' + qmRate + '%），可放心参考' });
        }
      }
      break;

    case 'score':
      var sa = ov.score_audit || {};
      if (sa.outlier_count > 0) {
        advice.push({ icon: 'warning', text: '发现 ' + sa.outlier_count + ' 个评分异常值，建议检查这些作品的评分标准是否偏移' });
      } else if (sa.status === 'PASS') {
        advice.push({ icon: 'check', text: '评分体系一致，各维度评分可靠' });
      }
      break;

    case 'rhythm':
      var paceDist = dist.pace || {};
      var paceTotal = Object.values(paceDist).reduce(function(a, b) { return a + b; }, 0);
      if (paceTotal > 0) {
        var fastPct = Math.round((paceDist.fast || 0) / paceTotal * 100);
        var slowPct = Math.round((paceDist.slow || 0) / paceTotal * 100);
        if (fastPct > 60) {
          advice.push({ icon: 'bolt', text: genre + '快节奏占比 ' + fastPct + '%，建议前 3 章保持快节奏，开篇 2000 字内出现第一次冲突，避免铺垫过长' });
        } else if (slowPct > 40) {
          advice.push({ icon: 'info', text: genre + '慢节奏占比 ' + slowPct + '%，但开篇仍建议加速，可将慢节奏安排在 20 章后的过渡段' });
        } else {
          advice.push({ icon: 'info', text: genre + '节奏均衡（快' + fastPct + '%/慢' + slowPct + '%），建议"快-慢-快"波浪式推进，每 10 章一个节奏循环' });
        }
      }
      break;

    case 'pleasure':
      var pleasureDist = dist.pleasure || {};
      var pleasureTotal = Object.values(pleasureDist).reduce(function(a, b) { return a + b; }, 0);
      if (pleasureTotal > 0) {
        var nonePct = Math.round((pleasureDist.none || 0) / pleasureTotal * 100);
        var majorPct = Math.round((pleasureDist.major || 0) / pleasureTotal * 100);
        if (nonePct > 30) {
          advice.push({ icon: 'warning', text: '无爽点章节占比 ' + nonePct + '%，爆款平均每 3 章至少一个清晰爽点，连续 5 章无爽点会导致读者流失' });
        }
        if (majorPct < 10) {
          advice.push({ icon: 'bolt', text: '大爽点占比仅 ' + majorPct + '%，建议每卷至少安排 2-3 个大爽点（如装逼打脸、实力碾压、真相揭露）' });
        } else {
          advice.push({ icon: 'check', text: '大爽点分布合理（' + majorPct + '%），注意错落有致，避免爽点疲劳' });
        }
      }
      break;

    case 'tech':
      var tc = ov.technique_cards || [];
      if (tc.length > 0) {
        // 找出最高频技法
        var byCat = {};
        tc.forEach(function(c) { var cat = c.category || 'other'; if (!byCat[cat]) byCat[cat] = []; byCat[cat].push(c); });
        var topCat = Object.keys(byCat).sort(function(a, b) { return byCat[b].length - byCat[a].length; })[0];
        advice.push({ icon: 'bolt', text: genre + '高频技法分类：「' + topCat + '」（' + byCat[topCat].length + ' 张），建议优先学习并应用到你的大纲中' });
        advice.push({ icon: 'info', text: '点击下方技法卡片可查看具体内容，并一键「应用到大纲」' });
      }
      break;
  }

  return advice;
}

// 建议图标渲染
var _adviceIcons = {
  'warning': '<span style="color:var(--warning)">&#9888;</span>',
  'check': '<span style="color:var(--success)">&#10003;</span>',
  'bolt': '<span style="color:var(--accent)">&#9889;</span>',
  'info': '<span style="color:var(--text-secondary)">&#8505;</span>'
};

function renderAdvice(adviceList) {
  if (!adviceList || adviceList.length === 0) return '';
  return adviceList.map(function(a) {
    return '<div class="report-advice">' +
      (_adviceIcons[a.icon] || _adviceIcons.info) +
      '<span>' + escapeHtml(a.text) + '</span>' +
      '</div>';
  }).join('');
}

// ============================================================
// P0-3: CSS 迷你条形图 — 纯 CSS 实现，无需外部依赖
// ============================================================

function renderMiniBars(data, labels, total) {
  if (!data || Object.keys(data).length === 0) return '';
  var entries = Object.entries(data).sort(function(a, b) { return b[1] - a[1]; });
  var colors = { fast: '#22C55E', medium: '#F59E0B', slow: '#EF4444', major: '#F97316', minor: '#FBBF24', none: '#6B7280', climax: '#DC2626' };
  return '<div class="mini-bar-chart">' + entries.map(function(_a) {
    var k = _a[0], v = _a[1];
    var pct = total > 0 ? Math.round(v / total * 100) : 0;
    var label = labels[k] || k;
    var color = colors[k] || 'var(--accent)';
    return '<div class="mini-bar-row">' +
      '<span class="mini-bar-label">' + escapeHtml(label) + '</span>' +
      '<div class="mini-bar-track"><div class="mini-bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
      '<span class="mini-bar-value">' + pct + '%</span>' +
      '</div>';
  }).join('') + '</div>';
}

var _paceLabels = { fast: '快节奏', medium: '中节奏', slow: '慢节奏', unknown: '未知' };
var _pleasureLabels = { none: '无爽点', minor: '小爽点', major: '大爽点', climax: '高潮章' };

// ============================================================
// 主渲染函数
// ============================================================

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
    advice: generateAdvice('overview', ov),
  });

  // 2. 分析质量概览
  const qm = ov.quality_manifest || {};
  const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0);
  const qmPassRate = qmTotal > 0 ? Math.round((qm.approved || 0) / qmTotal * 100) : 0;
  cards.push({
    type: 'quality',
    dotClass: qmPassRate >= 80 ? 'green' : (qmPassRate >= 50 ? 'amber' : 'red'),
    title: '分析质量概览',
    insight: (qm.approved || 0) + ' 本通过质量检查 · 通过率 ' + qmPassRate + '%',
    meta: qmTotal + ' 本总计',
    tags: ['质量', '概览'],
    detail: buildQualityDetail(ov),
    advice: generateAdvice('quality', ov),
  });

  // 3. 评分一致性检查
  const sa = ov.score_audit || {};
  cards.push({
    type: 'score',
    dotClass: sa.status === 'PASS' ? 'green' : 'red',
    title: '评分一致性检查',
    insight: '检查状态: ' + (sa.status === 'PASS' ? '通过' : '异常') + ' · ' + (sa.total_books || 0) + ' 本已评分',
    meta: (sa.outlier_count || 0) + ' 个异常值',
    tags: ['评分', '一致性'],
    detail: buildScoreDetail(ov),
    advice: generateAdvice('score', ov),
  });

  // 4. 节奏分布（P0-3: 加迷你条形图）
  const dist = ov.distributions || {};
  const paceDist = dist.pace || {};
  const paceTotal = Object.values(paceDist).reduce(function(a, b) { return a + b; }, 0);
  const fastPct = paceTotal > 0 ? Math.round((paceDist.fast || 0) / paceTotal * 100) : 0;
  cards.push({
    type: 'rhythm',
    dotClass: 'purple',
    title: '节奏分布分析',
    insight: '快节奏 ' + fastPct + '% · 中节奏 ' + (paceTotal > 0 ? Math.round((paceDist.medium || 0) / paceTotal * 100) : 0) + '% · 慢节奏 ' + (paceTotal > 0 ? Math.round((paceDist.slow || 0) / paceTotal * 100) : 0) + '%',
    meta: stats.chapters + ' 章样本',
    tags: ['节奏', '分布'],
    detail: buildDistributionDetail(ov),
    advice: generateAdvice('rhythm', ov),
    chart: renderMiniBars(paceDist, _paceLabels, paceTotal),
  });

  // 5. 爽点分布（P0-3: 加迷你条形图）
  const pleasureDist = dist.pleasure || {};
  const pleasureTotal = Object.values(pleasureDist).reduce(function(a, b) { return a + b; }, 0);
  const nonePct = pleasureTotal > 0 ? Math.round((pleasureDist.none || 0) / pleasureTotal * 100) : 0;
  cards.push({
    type: 'pleasure',
    dotClass: 'amber',
    title: '爽点分布分析',
    insight: '无爽点 ' + nonePct + '% · 小爽点 ' + (pleasureTotal > 0 ? Math.round((pleasureDist.minor || 0) / pleasureTotal * 100) : 0) + '% · 大爽点 ' + (pleasureTotal > 0 ? Math.round((pleasureDist.major || 0) / pleasureTotal * 100) : 0) + '%',
    meta: pleasureTotal + ' 章样本',
    tags: ['爽点', '分布'],
    detail: buildPleasureDetail(ov),
    advice: generateAdvice('pleasure', ov),
    chart: renderMiniBars(pleasureDist, _pleasureLabels, pleasureTotal),
  });

  // 6. 技法卡片（P0-4: 主视图改为可展开列表）
  const tc = ov.technique_cards || [];
  const tcByCat = {};
  tc.forEach(function(c) { var cat = c.category || '其他'; if (!tcByCat[cat]) tcByCat[cat] = []; tcByCat[cat].push(c); });
  cards.push({
    type: 'tech',
    dotClass: 'blue',
    title: '技法卡片库',
    insight: tc.length + ' 张技法卡片 · ' + Object.keys(tcByCat).length + ' 个分类: ' + Object.keys(tcByCat).join('、'),
    meta: tc.length + ' 张卡片',
    tags: ['技法', '卡片'],
    detail: buildTechniqueCardsDetail(tc),
    advice: generateAdvice('tech', ov),
    techCards: tc, // P0-4: 传递完整技法数据
    techByCat: tcByCat,
  });

  _reportCards = cards;

  // 渲染卡片 — P0-2: 加入建议行, P0-3: 加入图表, P0-4: 技法卡片特殊渲染
  grid.innerHTML = cards.map(function(r, idx) {
    var tagsHtml = (r.tags || []).map(function(t) { return '<span class="report-tag">' + escapeHtml(t) + '</span>'; }).join('');
    var chartHtml = r.chart ? '<div class="report-chart">' + r.chart + '</div>' : '';
    var adviceHtml = renderAdvice(r.advice);

    // P0-4: 技法卡片特殊渲染 — 可展开列表
    var techHtml = '';
    if (r.type === 'tech' && r.techCards && r.techCards.length > 0) {
      techHtml = '<div class="tech-mini-list" onclick="event.stopPropagation()">';
      var cats = Object.entries(r.techByCat);
      cats.forEach(function(_a) {
        var cat = _a[0], items = _a[1];
        techHtml += '<div class="tech-cat-group">' +
          '<div class="tech-cat-header" onclick="this.parentElement.classList.toggle(\'expanded\')">' +
            '<span class="tech-cat-toggle">&#9654;</span>' +
            '<span class="tech-cat-name">' + escapeHtml(cat) + '</span>' +
            '<span class="tech-cat-count">' + items.length + ' 张</span>' +
          '</div>' +
          '<div class="tech-cat-body">' +
            items.slice(0, 5).map(function(c) {
              return '<div class="tech-item">' +
                '<div class="tech-item-title">' + escapeHtml(c.title || c.id || '?') + '</div>' +
                '<div class="tech-item-desc">' + escapeHtml((c.content || '').substring(0, 120)) + (c.content && c.content.length > 120 ? '...' : '') + '</div>' +
                '<button class="tech-apply-btn" onclick="event.stopPropagation();applyTechniqueToOutline(' + JSON.stringify(c.title || c.id || '').replace(/"/g, '&quot;') + ',\'' + escapeHtml((c.content || '').substring(0, 200)).replace(/'/g, "\\'") + '\')">应用到大纲</button>' +
              '</div>';
            }).join('') +
            (items.length > 5 ? '<div class="tech-more">还有 ' + (items.length - 5) + ' 张，点击卡片查看全部</div>' : '') +
          '</div>' +
        '</div>';
      });
      techHtml += '</div>';
    }

    return '<div class="report-card" data-report-type="' + escapeHtml(r.type || '') + '" onclick="openReportDetail(' + idx + ')">' +
      '<div class="report-header"><span class="lifecycle-dot ' + escapeHtml(r.dotClass || '') + '"></span><h3>' + escapeHtml(r.title || '') + '</h3></div>' +
      '<p class="report-insight">' + escapeHtml(r.insight || '') + '</p>' +
      chartHtml +
      techHtml +
      adviceHtml +
      '<div class="report-meta"><span>' + escapeHtml(r.meta || '') + '</span>' +
      '<div class="report-tags">' + tagsHtml + '</div></div>' +
      '</div>';
  }).join('');

  // 更新计数
  var countEl = $('#report-count');
  if (countEl) countEl.textContent = '共 ' + cards.length + ' 份报告';

  // 更新侧边栏
  var sidebarStats = $('#report-sidebar-stats');
  if (sidebarStats) {
    sidebarStats.innerHTML = cards.map(function(r) {
      return '<div class="summary-row"><span>' + escapeHtml(r.title || '') + '</span><span class="summary-row-value">' + escapeHtml(r.meta || '') + '</span></div>';
    }).join('');
  }

  // 更新后端数据统计面板
  var apiPanel = $('#report-api-stats');
  if (apiPanel && stats.books) {
    apiPanel.style.display = '';
    setText('rs-api-books', stats.books);
    setText('rs-api-chapters', fmtNumber(stats.chapters));
    setText('rs-api-genre', ov.genre || _reportGenre);
    setText('rs-api-hook', ra.passed + '/' + ra.total_books + ' 通过');
  }
}

// ============================================================
// P0-7: 技法卡片「应用到大纲」— 跨页联动
// ============================================================

function applyTechniqueToOutline(title, content) {
  // 存入 sessionStorage 供设计页读取
  try {
    sessionStorage.setItem('pending_technique', JSON.stringify({ title: title, content: content, ts: Date.now() }));
  } catch (e) {}
  showToast('技法「' + title + '」已准备，正在跳转到设计页...');
  setTimeout(function() {
    navigate('design');
    // 等设计页加载后提示用户
    setTimeout(function() {
      var pending = null;
      try { pending = JSON.parse(sessionStorage.getItem('pending_technique')); } catch (e) {}
      if (pending) {
        showToast('已加载技法：' + pending.title + '。点击细纲段可将其作为场景参考');
        // 如果有当前项目且细纲有数据，追加到第一个细纲段的 scenes
        if (DESIGN_DATA && DESIGN_DATA.chapters && DESIGN_DATA.chapters.length > 0) {
          var ch = DESIGN_DATA.chapters[0];
          if (!ch.scenes) ch.scenes = [];
          if (!ch.scenes.some(function(s) { return s.indexOf(pending.title) >= 0; })) {
            ch.scenes.push('[' + pending.title + '] ' + (pending.content || '').substring(0, 60));
            // 自动保存
            if (currentProject && currentProject.id) {
              ProjectAPI.updateSkeleton(currentProject.id, { volumes: DESIGN_DATA.volumes, chapters: DESIGN_DATA.chapters }).then(function() {
                showToast('已将技法追加到第一个细纲段');
                showDesign('detailed');
                loadDesignData();
              });
            }
          }
        }
        sessionStorage.removeItem('pending_technique');
      }
    }, 500);
  }, 300);
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
  lines.push('【分析质量概览】');
  const qm = ov.quality_manifest || {};
  const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0);
  lines.push('  通过: ' + (qm.approved || 0) + ' / ' + qmTotal + ' 本');
  lines.push('  通过率: ' + (qmTotal > 0 ? Math.round((qm.approved || 0) / qmTotal * 100) : 0) + '%');
  return lines.join('\n');
}

function buildQualityDetail(ov) {
  const qm = ov.quality_manifest || {};
  const lines = [];
  lines.push('【分析质量概览】');
  const qmTotal = (qm.approved || 0) + (qm.quarantined || 0) + (qm.failed || 0);
  lines.push('  通过: ' + (qm.approved || 0) + ' / ' + qmTotal + ' 本');
  lines.push('  通过率: ' + (qmTotal > 0 ? Math.round((qm.approved || 0) / qmTotal * 100) : 0) + '%');
  lines.push('');
  lines.push('说明: 通过质量检查的作品数据更可靠，');
  lines.push('适合作为创作参考。未通过的作品仍保留在书库中，');
  lines.push('但不参与跨书合成分析。');
  return lines.join('\n');
}

function buildScoreDetail(ov) {
  const sa = ov.score_audit || {};
  const lines = [];
  lines.push('【评分一致性检查】');
  lines.push('  检查状态: ' + (sa.status === 'PASS' ? '通过' : '异常'));
  lines.push('  已评分: ' + (sa.total_books || 0) + ' 本');
  lines.push('  异常值: ' + (sa.outlier_count || 0) + ' 个');
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
  var byCat = {};
  cards.forEach(function(c) {
    var cat = c.category || 'other';
    if (!byCat[cat]) byCat[cat] = [];
    byCat[cat].push(c);
  });
  var html = '<div class="tech-detail-list">';
  Object.entries(byCat).forEach(function(_a) {
    var cat = _a[0], items = _a[1];
    html += '<div class="tech-detail-cat">';
    html += '<h4>' + escapeHtml(cat) + ' (' + items.length + ' 张)</h4>';
    items.forEach(function(c) {
      html += '<div class="tech-detail-item">' +
        '<div class="tech-detail-title">' + escapeHtml(c.title || c.id || '?') + '</div>' +
        '<div class="tech-detail-content">' + escapeHtml(c.content || '') + '</div>' +
        '<button class="btn btn-secondary btn-sm" onclick="applyTechniqueToOutline(\'' + escapeHtml(c.title || c.id || '').replace(/'/g, "\\'") + '\',\'' + escapeHtml((c.content || '').substring(0, 200)).replace(/'/g, "\\'") + '\')">应用到大纲</button>' +
      '</div>';
    });
    html += '</div>';
  });
  html += '</div>';
  return html;
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
    var adviceHtml = renderAdvice(r.advice);
    bodyEl.innerHTML =
      '<div class="report-detail-field"><label>核心洞察</label><div class="report-detail-text">' + escapeHtml(r.insight || '') + '</div></div>' +
      (adviceHtml ? '<div class="report-detail-field"><label>创作建议</label>' + adviceHtml + '</div>' : '') +
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

function exportReportDetail() {
  if (_currentReportIndex == null) return;
  const r = _reportCards[_currentReportIndex];
  if (!r) return;
  var text = r.title + '\n\n核心洞察：\n' + (r.insight || '');
  if (r.advice && r.advice.length > 0) {
    text += '\n\n创作建议：\n';
    r.advice.forEach(function(a) { text += '- ' + a.text + '\n'; });
  }
  text += '\n详细分析：\n' + (r.detail || '');
  var blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = '报告_' + r.title + '.txt';
  a.click();
  URL.revokeObjectURL(url);
  showToast('报告已导出');
}
