"use strict";

// ============================================================
// 拆书分析页面
// ============================================================
async function loadDisassemblyData() {
  const listEl = $('#disassembly-book-list');
  if (listEl) listEl.innerHTML = '<div class="text-muted" style="font-size:13px;padding:8px 0;">加载拆书数据中...</div>';
  const { ok, data, error } = await apiGet('/api/disassembly/books');
  if (ok && data) {
    disassemblyData = data;
    renderDisassemblyPage();
  } else {
    console.error('[Disassembly] 加载拆书数据失败', error);
    if (listEl) listEl.innerHTML = '<div class="text-muted" style="font-size:13px;padding:8px 0;">加载失败，请确认后端已启动</div>';
  }
}

function renderDisassemblyPage() {
  if (!disassemblyData || !disassemblyData.books) return;
  const books = disassemblyData.books;

  // KPI
  const totalChapters = books.reduce(function(sum, b) { return sum + (b.summary && b.summary.chapters || 0); }, 0);
  const totalWords = books.reduce(function(sum, b) { return sum + (b.summary && b.summary.total_words || 0); }, 0);
  const avgWords = totalChapters > 0 ? Math.round(totalWords / totalChapters) : 0;
  setText('dis-kpi-books', books.length);
  setText('dis-kpi-chapters', fmtNumber(totalChapters));
  setText('dis-kpi-words', fmtNumber(totalWords));
  setText('dis-kpi-avg', fmtNumber(avgWords));

  renderDisassemblyList(books);
  renderDisassemblyStats(books);
}

function renderDisassemblyList(books) {
  const el = $('#disassembly-book-list');
  if (!el) return;
  if (books.length === 0) {
    el.innerHTML = '<div class="text-muted" style="font-size:13px;padding:8px 0;">暂无拆书数据</div>';
    return;
  }
  el.innerHTML = books.map(function(b) {
    const title = (b.key || '').replace(/^rhythm_/, '');
    const chapters = b.summary && b.summary.chapters || 0;
    return '<div class="dis-list-item" onclick="openDisassemblyDetail(\'' + escapeHtml(title) + '\')">' +
      '<span class="dis-list-name">' + escapeHtml(title) + '</span>' +
      '<span class="dis-list-chapters">' + chapters + ' 章</span>' +
    '</div>';
  }).join('');
}

function renderDisassemblyStats(books) {
  const totalChapters = books.reduce(function(sum, b) { return sum + (b.summary && b.summary.chapters || 0); }, 0);
  setText('dis-stat-chapters', fmtNumber(totalChapters));

  // 平均爽点密度：从 pleasure_dist 计算有爽点章节占比
  let pleasureChapters = 0;
  let pleasureTotal = 0;
  books.forEach(function(b) {
    const dist = b.summary && b.summary.pleasure_dist || {};
    Object.keys(dist).forEach(function(k) {
      const v = dist[k] || 0;
      pleasureTotal += v;
      if (k !== 'none') pleasureChapters += v;
    });
  });
  const pleasureRate = pleasureTotal > 0 ? (pleasureChapters / pleasureTotal * 100).toFixed(1) + '%' : '-';
  setText('dis-stat-pleasure', pleasureRate);

  // 平均节奏评分：fast 占比越高分数越高（简单估算）
  let paceTotal = 0;
  let fastCount = 0;
  books.forEach(function(b) {
    const dist = b.summary && b.summary.pace_dist || {};
    Object.keys(dist).forEach(function(k) {
      const v = dist[k] || 0;
      paceTotal += v;
      if (k === 'fast') fastCount += v;
    });
  });
  const paceScore = paceTotal > 0 ? (6 + (fastCount / paceTotal) * 4).toFixed(1) : '-';
  setText('dis-stat-pace', paceScore);
}

async function openDisassemblyDetail(name) {
  const modal = $('#disassembly-detail-modal');
  const title = $('#dis-detail-title');
  const body = $('#dis-detail-body');
  if (!modal || !body) return;
  title.textContent = name;
  body.innerHTML = '<div class="text-muted" style="font-size:13px;padding:16px 0;">加载章节详情...</div>';
  modal.style.display = 'flex';
  const { ok, data, error } = await apiGet('/api/disassembly/book?name=' + encodeURIComponent(name));
  if (ok && data) {
    renderDisassemblyDetail(data);
  } else {
    console.error('[Disassembly] 加载详情失败', error);
    body.innerHTML = '<div class="text-muted" style="font-size:13px;padding:16px 0;">加载详情失败：' + escapeHtml(error || '未知错误') + '</div>';
  }
}

function closeDisassemblyDetailModal() {
  const modal = $('#disassembly-detail-modal');
  if (modal) modal.style.display = 'none';
}

function renderDisassemblyDetail(data) {
  const body = $('#dis-detail-body');
  if (!body) return;
  const summary = data.summary || {};
  const chapters = data.chapters || [];
  const total = summary.chapters || chapters.length || 0;
  const words = summary.total_words || 0;
  const avg = total > 0 ? Math.round(words / total) : 0;

  body.innerHTML =
    '<div class="dis-detail-meta">' +
      '<div><b>题材</b><span>' + escapeHtml(data.genre || '末世') + '</span></div>' +
      '<div><b>总章节</b><span>' + total + '</span></div>' +
      '<div><b>总字数</b><span>' + fmtNumber(words) + '</span></div>' +
      '<div><b>平均章字数</b><span>' + fmtNumber(avg) + '</span></div>' +
    '</div>' +
    renderThreeStepAnalysis(data) +
    renderDistributionBars('情绪分布', summary.emotion_dist) +
    renderDistributionBars('节奏分布', summary.pace_dist) +
    renderDistributionBars('冲突分布', summary.conflict_dist) +
    renderDistributionBars('爽点分布', summary.pleasure_dist) +
    '<div class="dis-detail-chapters-title">逐章数据（前 30 章）</div>' +
    '<div class="dis-detail-chapters">' + chapters.slice(0, 30).map(function(c) {
      return '<div class="dis-detail-chapter-row">' +
        '<span class="dc-ch">第' + (c.ch || 0) + '章</span>' +
        '<span class="dc-wc">' + (c.wc || 0) + '字</span>' +
        '<span class="dc-emotion">' + escapeHtml(c.emotion || '') + '</span>' +
        '<span class="dc-pace">' + escapeHtml(c.pace || '') + '</span>' +
        '<span class="dc-conflict">' + (c.conflict === 'True' ? '冲突' : '无冲突') + '</span>' +
        '<span class="dc-pleasure">' + escapeHtml(c.pleasure_type || '无爽点') + '</span>' +
      '</div>';
    }).join('') + '</div>';
}

function renderDistributionBars(title, dist) {
  if (!dist) return '';
  const keys = Object.keys(dist);
  if (keys.length === 0) return '';
  const total = keys.reduce(function(sum, k) { return sum + (dist[k] || 0); }, 0);
  if (total === 0) return '';
  const colors = ['#38bdf8', '#f59e0b', '#22c55e', '#ef4444', '#a78bfa', '#f97316', '#14b8a6', '#ec4899'];
  return '<div class="dis-detail-section"><b>' + escapeHtml(title) + '</b>' +
    '<div class="dis-detail-bars">' + keys.map(function(k, i) {
      const v = dist[k] || 0;
      const pct = (v / total * 100).toFixed(1);
      return '<div class="dis-detail-bar">' +
        '<div class="dis-detail-bar-label"><span>' + escapeHtml(k) + '</span><span>' + pct + '% (' + v + ')</span></div>' +
        '<div class="dis-detail-bar-track"><div class="dis-detail-bar-fill" style="width:' + pct + '%;background:' + colors[i % colors.length] + '"></div></div>' +
      '</div>';
    }).join('') + '</div></div>';
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ============================================================
// 拆书三步法 (v8.2)
// 步1: 拆核心 (卖点与金手指)
// 步2: 拆细节 (节奏与大纲)
// 步3: 拆人性 (人设与动机)
// ============================================================
function renderThreeStepAnalysis(data) {
  var summary = data.summary || {};
  var genre = data.genre || '';

  // 步1: 拆核心 — 从 genre_synthesis 提取卖点与金手指
  var step1Content = buildStep1Core(genre, summary);

  // 步2: 拆细节 — 从节奏分布和章节数据提取
  var step2Content = buildStep2Detail(summary, data.chapters || []);

  // 步3: 拆人性 — 从人物设定提取
  var step3Content = buildStep3Character(summary);

  return '<div class="dis-three-step">' +
    '<div class="dis-three-step-title">拆书三步法</div>' +
    '<div class="dis-three-step-intro">拆核心（卖点与金手指）→ 拆细节（节奏与大纲）→ 拆人性（人设与动机）</div>' +
    buildStepCard(1, '拆核心', '卖点与金手指', '找出这本书\"凭什么让读者追下去\"', step1Content) +
    buildStepCard(2, '拆细节', '节奏与大纲', '分析章节级别的节奏控制和爽点投放', step2Content) +
    buildStepCard(3, '拆人性', '人设与动机', '分析人物弧线和行为驱动力', step3Content) +
  '</div>';
}

function buildStepCard(step, title, subtitle, desc, content) {
  return '<div class="dis-step-card" onclick="toggleStepCard(this)">' +
    '<div class="dis-step-header">' +
      '<span class="dis-step-num">步' + step + '</span>' +
      '<div class="dis-step-info">' +
        '<div class="dis-step-title">' + title + '</div>' +
        '<div class="dis-step-subtitle">' + subtitle + '</div>' +
      '</div>' +
      '<span class="dis-step-toggle">&#9660;</span>' +
    '</div>' +
    '<div class="dis-step-desc">' + desc + '</div>' +
    '<div class="dis-step-body" style="display:none">' + content + '</div>' +
  '</div>';
}

function buildStep1Core(genre, summary) {
  var html = '<div class="dis-step-table">';

  // 题材卖点
  html += '<div class="dis-step-row"><span class="dis-step-label">题材</span><span>' + escapeHtml(genre || '未标注') + '</span></div>';

  // 冲突类型分布 → 核心卖点
  var conflictDist = summary.conflict_dist || {};
  var conflictKeys = Object.keys(conflictDist);
  if (conflictKeys.length > 0) {
    var topConflict = conflictKeys.reduce(function(a, b) { return (conflictDist[a] || 0) > (conflictDist[b] || 0) ? a : b; });
    html += '<div class="dis-step-row"><span class="dis-step-label">核心冲突</span><span>' + escapeHtml(topConflict) + '</span></div>';
  }

  // 爽点分布 → 主爽点类型
  var pleasureDist = summary.pleasure_dist || {};
  var pleasureKeys = Object.keys(pleasureDist).filter(function(k) { return k !== 'none'; });
  if (pleasureKeys.length > 0) {
    html += '<div class="dis-step-row"><span class="dis-step-label">主爽点</span><span>' + pleasureKeys.join(' / ') + '</span></div>';
  }

  // 情绪分布 → 情绪基调
  var emotionDist = summary.emotion_dist || {};
  var emotionKeys = Object.keys(emotionDist);
  if (emotionKeys.length > 0) {
    var topEmotion = emotionKeys.reduce(function(a, b) { return (emotionDist[a] || 0) > (emotionDist[b] || 0) ? a : b; });
    html += '<div class="dis-step-row"><span class="dis-step-label">情绪基调</span><span>' + escapeHtml(topEmotion) + '</span></div>';
  }

  html += '</div>';
  html += '<div class="dis-step-tip">提示：拆核心回答\"这本书凭什么让读者追下去\"。卖点 = 题材 + 冲突 + 爽点 的组合；金手指 = 主角的独特优势。</div>';
  return html;
}

function buildStep2Detail(summary, chapters) {
  var html = '<div class="dis-step-table">';

  // 节奏分布
  var paceDist = summary.pace_dist || {};
  var paceKeys = Object.keys(paceDist);
  if (paceKeys.length > 0) {
    html += '<div class="dis-step-row"><span class="dis-step-label">节奏分布</span><span>' +
      paceKeys.map(function(k) { return k + '(' + (paceDist[k] || 0) + ')'; }).join(' / ') +
    '</span></div>';
  }

  // 章节统计数据
  var total = chapters.length || summary.chapters || 0;
  html += '<div class="dis-step-row"><span class="dis-step-label">总章节</span><span>' + total + '</span></div>';

  // 平均章字数
  var avgWC = total > 0 ? Math.round((summary.total_words || 0) / total) : 0;
  html += '<div class="dis-step-row"><span class="dis-step-label">平均章字数</span><span>' + fmtNumber(avgWC) + '</span></div>';

  // 爽点密度
  var pleasureTotal = 0;
  var pleasureHit = 0;
  var pd = summary.pleasure_dist || {};
  Object.keys(pd).forEach(function(k) {
    var v = pd[k] || 0;
    pleasureTotal += v;
    if (k !== 'none') pleasureHit += v;
  });
  var density = pleasureTotal > 0 ? (pleasureHit / pleasureTotal * 100).toFixed(1) + '%' : '-';
  html += '<div class="dis-step-row"><span class="dis-step-label">爽点密度</span><span>' + density + '</span></div>';

  html += '</div>';
  html += '<div class="dis-step-tip">提示：拆细节回答\"作者如何控制节奏\"。关注爽点投放频率、章节长度规律、节奏快慢交替模式。</div>';
  return html;
}

function buildStep3Character(summary) {
  var html = '<div class="dis-step-table">';

  // 主要人物信息（从 summary 中提取）
  var characters = summary.characters || [];
  if (characters.length > 0) {
    html += '<div class="dis-step-row"><span class="dis-step-label">人物数量</span><span>' + characters.length + '</span></div>';
    characters.slice(0, 5).forEach(function(c) {
      html += '<div class="dis-step-row"><span class="dis-step-label-small">' + escapeHtml(c.name || '未知') + '</span><span>' + escapeHtml(c.role || '') + '</span></div>';
    });
  } else {
    html += '<div class="dis-step-row"><span class="dis-step-label">人物</span><span>暂无数据</span></div>';
  }

  // 情绪分布 → 人物动机
  var emotionDist = summary.emotion_dist || {};
  var emotionKeys = Object.keys(emotionDist);
  if (emotionKeys.length > 1) {
    html += '<div class="dis-step-row"><span class="dis-step-label">情绪多样性</span><span>' + emotionKeys.length + ' 种情绪</span></div>';
  }

  html += '</div>';
  html += '<div class="dis-step-tip">提示：拆人性回答\"角色为什么这么做\"。关注人物动机、行为一致性、核心欲望和恐惧。</div>';
  return html;
}

function toggleStepCard(card) {
  var body = card.querySelector('.dis-step-body');
  var toggle = card.querySelector('.dis-step-toggle');
  if (body && toggle) {
    if (body.style.display === 'none') {
      body.style.display = 'block';
      toggle.innerHTML = '&#9650;';
    } else {
      body.style.display = 'none';
      toggle.innerHTML = '&#9660;';
    }
  }
}
