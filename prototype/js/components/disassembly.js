"use strict";

// ============================================================
// 拆书分析页面
// v10: 统一书目列表 + 题材/状态筛选 + 主区域详情 + 导入写作参考
// ============================================================
var disassemblySelectedBook = null;
var disFilter = { genre: 'all', status: 'all' };
var currentDisDetail = null; // 当前拆书详情数据，供"应用到设计页"使用

async function loadDisassemblyData() {
  var listEl = $('#disassembly-book-list');
  if (listEl) listEl.innerHTML = '<div class="text-muted" style="font-size:13px;padding:8px 0;">加载中...</div>';
  // 确保 DATA (书库数据) 已加载
  if (!DATA) {
    await loadLibraryData();
  }
  var { ok, data, error } = await apiGet('/api/disassembly/books');
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
  var books = disassemblyData.books;

  // KPI
  var totalChapters = books.reduce(function(sum, b) { return sum + (b.summary && b.summary.chapters || 0); }, 0);
  var totalWords = books.reduce(function(sum, b) { return sum + (b.summary && b.summary.total_words || 0); }, 0);
  var avgWords = totalChapters > 0 ? Math.round(totalWords / totalChapters) : 0;
  setText('dis-kpi-books', books.length);
  setText('dis-kpi-chapters', fmtNumber(totalChapters));
  setText('dis-kpi-words', fmtNumber(totalWords));
  setText('dis-kpi-avg', fmtNumber(avgWords));

  // 如果 DATA 还没加载，先渲染筛选和列表（可能只显示已拆书）
  renderDisassemblyFilters();
  renderDisassemblyList();
  renderDisassemblyStats(books);
}

// 筛选条：题材 + 状态
function renderDisassemblyFilters() {
  var container = $('#dis-filters');
  if (!container) return;

  // 从 DATA.books 收集所有题材
  var genreSet = {};
  var libBooks = (typeof DATA !== 'undefined' && DATA.books) ? DATA.books : [];
  libBooks.forEach(function(b) { if (b.genre) genreSet[b.genre] = true; });
  var genres = Object.keys(genreSet).sort();

  container.innerHTML =
    '<div class="dis-filter-group">' +
      '<span class="dis-filter-label">状态</span>' +
      '<button class="dis-filter-btn' + (disFilter.status === 'all' ? ' active' : '') + '" onclick="setDisFilter(\'status\',\'all\')">全部</button>' +
      '<button class="dis-filter-btn' + (disFilter.status === 'analyzed' ? ' active' : '') + '" onclick="setDisFilter(\'status\',\'analyzed\')">已拆</button>' +
      '<button class="dis-filter-btn' + (disFilter.status === 'pending' ? ' active' : '') + '" onclick="setDisFilter(\'status\',\'pending\')">待拆</button>' +
    '</div>' +
    '<div class="dis-filter-group">' +
      '<span class="dis-filter-label">题材</span>' +
      '<button class="dis-filter-btn' + (disFilter.genre === 'all' ? ' active' : '') + '" onclick="setDisFilter(\'genre\',\'all\')">全部</button>' +
      genres.map(function(g) {
        return '<button class="dis-filter-btn' + (disFilter.genre === g ? ' active' : '') + '" onclick="setDisFilter(\'genre\',\'' + escapeHtml(g) + '\')">' + escapeHtml(g) + '</button>';
      }).join('') +
    '</div>';
}

function setDisFilter(key, value) {
  disFilter[key] = value;
  renderDisassemblyFilters();
  renderDisassemblyList();
}

// 统一书目列表：以 DATA.books 为主（包含已拆+待拆），用 stem 与 disassemblyData 匹配
function renderDisassemblyList() {
  var el = $('#disassembly-book-list');
  if (!el) return;

  var libBooks = (typeof DATA !== 'undefined' && DATA.books) ? DATA.books : [];
  
  // 构建已拆书的 stem -> rhythm数据 的索引
  var disMap = {};
  if (disassemblyData && disassemblyData.books) {
    disassemblyData.books.forEach(function(b) {
      if (b.key) disMap[b.key] = b;
    });
  }

  // 构建统一列表
  var items = [];
  libBooks.forEach(function(b) {
    // stem 是文件名去掉扩展名，用于与 rhythm CSV 匹配
    // 如果后端没返回 stem，从 file 字段提取
    var stem = b.stem || '';
    if (!stem && b.file) {
      stem = b.file.replace(/^rhythm_/, '').replace(/\.csv$/, '');
    }
    if (!stem) stem = b.title || '';
    var isAnalyzed = b.status === 'analyzed' || !!disMap[stem];
    var disBook = disMap[stem];
    var chapters = disBook ? (disBook.summary && disBook.summary.chapters || 0) : 0;
    var words = disBook ? (disBook.summary && disBook.summary.total_words || 0) : (b.wordCount || 0);
    items.push({
      stem: stem,
      title: b.title || stem,
      genre: b.genre || '未知',
      chapters: chapters,
      words: words,
      status: isAnalyzed ? 'analyzed' : 'pending',
      statusLabel: isAnalyzed ? '已拆' : '待拆',
      statusCls: isAnalyzed ? 'success' : 'pending'
    });
  });

  // 应用筛选
  var filtered = items.filter(function(item) {
    if (disFilter.status !== 'all' && item.status !== disFilter.status) return false;
    if (disFilter.genre !== 'all' && item.genre !== disFilter.genre) return false;
    return true;
  });

  // 更新计数（显示当前筛选结果数/总数）
  var countEl = $('#dis-list-count');
  if (countEl) countEl.textContent = filtered.length + '/' + items.length + ' 本';

  if (filtered.length === 0) {
    el.innerHTML = '<div class="text-muted" style="font-size:13px;padding:16px 8px;text-align:center;">无匹配书籍，试试调整筛选条件</div>';
    return;
  }

  el.innerHTML = filtered.map(function(item) {
    var isActive = disassemblySelectedBook === item.stem ? ' active' : '';
    var infoHtml = item.status === 'analyzed'
      ? '<span class="dis-list-info-item">' + item.chapters + ' 章</span>'
      : '<span class="dis-list-info-item">' + fmtNumber(item.words) + ' 字</span>';
    var genreTag = '<span class="dis-list-genre">' + escapeHtml(item.genre) + '</span>';
    var compareBtn = item.status === 'analyzed'
      ? '<button class="dis-list-compare-btn" onclick="event.stopPropagation();toggleCompareBook(\'' + escapeHtml(item.stem) + '\',\'' + escapeHtml(item.title) + '\')" title="加入对比">&#9878;</button>'
      : '';
    return '<div class="dis-list-item' + isActive + '" onclick="openDisassemblyDetail(\'' + escapeHtml(item.stem) + '\',\'' + item.status + '\',\'' + escapeHtml(item.title) + '\')">' +
      '<div class="dis-list-item-left">' +
        '<span class="dis-list-name">' + escapeHtml(item.title) + '</span>' +
        '<span class="dis-list-info">' + genreTag + infoHtml + '</span>' +
      '</div>' +
      compareBtn +
      '<span class="dis-list-badge ' + item.statusCls + '">' + item.statusLabel + '</span>' +
    '</div>';
  }).join('');
}

function renderDisassemblyStats(books) {
  var totalChapters = books.reduce(function(sum, b) { return sum + (b.summary && b.summary.chapters || 0); }, 0);
  setText('dis-stat-chapters', fmtNumber(totalChapters));

  var pleasureChapters = 0;
  var pleasureTotal = 0;
  books.forEach(function(b) {
    var dist = b.summary && b.summary.pleasure_dist || {};
    Object.keys(dist).forEach(function(k) {
      var v = dist[k] || 0;
      pleasureTotal += v;
      if (k !== 'none') pleasureChapters += v;
    });
  });
  var pleasureRate = pleasureTotal > 0 ? (pleasureChapters / pleasureTotal * 100).toFixed(1) + '%' : '-';
  setText('dis-stat-pleasure', pleasureRate);

  var paceTotal = 0;
  var fastCount = 0;
  books.forEach(function(b) {
    var dist = b.summary && b.summary.pace_dist || {};
    Object.keys(dist).forEach(function(k) {
      var v = dist[k] || 0;
      paceTotal += v;
      if (k === 'fast') fastCount += v;
    });
  });
  var fastRate = paceTotal > 0 ? (fastCount / paceTotal * 100).toFixed(1) + '%' : '-';
  setText('dis-stat-pace', fastRate);
}

// 在主区域展示拆书详情
async function openDisassemblyDetail(name, status, displayTitle) {
  disassemblySelectedBook = name;
  var titleForDisplay = displayTitle || name;

  var emptyState = $('#disassembly-empty-state');
  var detailArea = $('#disassembly-detail-area');
  if (emptyState) emptyState.style.display = 'none';
  if (detailArea) detailArea.style.display = 'block';

  // 重新渲染列表以更新选中态
  renderDisassemblyList();

  // 待拆书：不调用 API，直接显示提示
  if (status === 'pending') {
    if (detailArea) {
      detailArea.innerHTML = '<div class="dis-detail-pending">' +
        '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.3;margin-bottom:12px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' +
        '<div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:6px;">' + escapeHtml(titleForDisplay) + '</div>' +
        '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">该书尚未进行拆书分析</div>' +
        '<button class="btn btn-primary btn-sm" onclick="navigate(\'library\')">前往书库开始分析</button>' +
      '</div>';
    }
    return;
  }

  // 已拆书：加载详情
  if (detailArea) {
    detailArea.innerHTML = '<div class="dis-detail-loading">' +
      '<svg class="spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>' +
      '<span>加载 ' + escapeHtml(titleForDisplay) + ' 的拆书详情...</span>' +
    '</div>';
  }

  var { ok, data, error } = await apiGet('/api/disassembly/book?name=' + encodeURIComponent(name));
  if (ok && data) {
    renderDisassemblyDetail(data);
  } else {
    console.error('[Disassembly] 加载详情失败', error);
    if (detailArea) {
      detailArea.innerHTML = '<div class="dis-detail-error">' +
        '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.4;margin-bottom:8px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
        '<div style="font-size:14px;color:var(--text);margin-bottom:4px;">加载详情失败</div>' +
        '<div style="font-size:12px;color:var(--text-secondary);">' + escapeHtml(error || '未知错误') + '</div>' +
      '</div>';
    }
  }
}

function renderDisassemblyDetail(data) {
  currentDisDetail = data;
  var area = $('#disassembly-detail-area');
  if (!area) return;
  var summary = data.summary || {};
  var chapters = data.chapters || [];
  var total = summary.chapters || data.total || chapters.length || 0;
  var words = summary.total_words || 0;
  var avg = total > 0 ? Math.round(words / total) : 0;
  var name = disassemblySelectedBook || data.book || '未知';
  // 尝试从 disassemblyData 中查找更友好的书名
  var displayName = name;
  if (disassemblyData && disassemblyData.books) {
    for (var i = 0; i < disassemblyData.books.length; i++) {
      if (disassemblyData.books[i].key === name) {
        displayName = disassemblyData.books[i].title || name;
        break;
      }
    }
  }
  // 也从 DATA.books 查找
  if (typeof DATA !== 'undefined' && DATA && DATA.books) {
    for (var j = 0; j < DATA.books.length; j++) {
      if (DATA.books[j].stem === name) {
        displayName = DATA.books[j].title || displayName;
        break;
      }
    }
  }

  area.innerHTML =
    '<div class="dis-detail-header">' +
      '<div class="dis-detail-header-info">' +
        '<h3 class="dis-detail-title">' + escapeHtml(displayName) + '</h3>' +
        '<div class="dis-detail-meta-row">' +
          '<span class="dis-meta-chip"><b>题材</b> ' + escapeHtml(data.genre || '末世') + '</span>' +
          '<span class="dis-meta-chip"><b>章节</b> ' + total + '</span>' +
          '<span class="dis-meta-chip"><b>字数</b> ' + fmtNumber(words) + '</span>' +
          '<span class="dis-meta-chip"><b>均章</b> ' + fmtNumber(avg) + '</span>' +
        '</div>' +
      '</div>' +
      '<button class="btn btn-primary btn-sm dis-import-btn" onclick="applyDisassemblyToDesign(\'' + escapeHtml(name) + '\',\'' + escapeHtml(displayName) + '\')">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>' +
        '应用到设计页' +
      '</button>' +
    '</div>' +
    '<div class="dis-detail-body">' +
      renderEightStepNav(data) +
      renderThreeStepAnalysis(data) +
      renderChapterTable(chapters) +
      renderDistributionBars('情绪分布', summary.emotion_dist) +
      renderDistributionBars('节奏分布', summary.pace_dist) +
      renderDistributionBars('冲突分布', summary.conflict_dist) +
      renderDistributionBars('爽点分布', summary.pleasure_dist) +
      renderRhythmVisualization(chapters, total) +
    '</div>';
}

// ============================================================
// P0: 章节拆解表 — 把已有的逐章数据以表格形式展示
// ============================================================
function renderChapterTable(chapters) {
  if (!chapters || chapters.length === 0) return '';
  var showCount = Math.min(chapters.length, 15);
  var paceColors = { fast: '#ef4444', medium: '#f59e0b', slow: '#38bdf8' };
  var rows = chapters.slice(0, showCount).map(function(c, i) {
    var chNum = c.ch || (i + 1);
    var pace = c.pace || '-';
    var paceColor = paceColors[pace] || '#cbd5e1';
    var emotion = c.emotion || '-';
    var conflictHtml = c.conflict
      ? '<span class="ch-tag ch-tag-conflict">冲突</span>'
      : '<span class="ch-tag ch-tag-muted">-</span>';
    var pleasureHtml = (c.pleasure_type && c.pleasure_type !== 'none')
      ? '<span class="ch-tag ch-tag-pleasure">' + escapeHtml(c.pleasure_type) + '</span>'
      : '<span class="ch-tag ch-tag-muted">-</span>';
    return '<tr>' +
      '<td class="ch-col-num">第' + chNum + '章</td>' +
      '<td class="ch-col-pace"><span class="pace-dot" style="background:' + paceColor + '"></span>' + escapeHtml(pace) + '</td>' +
      '<td class="ch-col-emotion">' + escapeHtml(emotion) + '</td>' +
      '<td class="ch-col-conflict">' + conflictHtml + '</td>' +
      '<td class="ch-col-pleasure">' + pleasureHtml + '</td>' +
      '<td class="ch-col-wc">' + fmtNumber(c.wc || 0) + '</td>' +
    '</tr>';
  }).join('');
  return '<div class="dis-detail-section">' +
    '<div class="ch-table-header"><b>章节拆解表</b><span class="ch-table-hint">展示前 ' + showCount + ' 章 · 逐章拆解节奏/情绪/冲突/爽点</span></div>' +
    '<div class="ch-table-wrap">' +
      '<table class="ch-table">' +
        '<thead><tr><th>章节</th><th>节奏</th><th>情绪</th><th>冲突</th><th>爽点</th><th>字数</th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>' +
    '</div>' +
  '</div>';
}

// ============================================================
// P0: 节拍检测 — 从章节数据自动识别故事节拍
// ============================================================
function detectBeats(chapters) {
  if (!chapters || chapters.length === 0) return [];
  var beats = [];
  // 1. 开局
  beats.push({ ch: 1, label: '开局', color: '#22c55e' });
  // 2. 激励事件: 第3章后第一个冲突章
  for (var i = 3; i < chapters.length; i++) {
    if (chapters[i].conflict) {
      beats.push({ ch: i + 1, label: '激励事件', color: '#f59e0b' });
      break;
    }
  }
  // 3. 小高潮: 首个连续2+快节奏章
  for (var i = 0; i < chapters.length - 1; i++) {
    if (chapters[i].pace === 'fast' && chapters[i + 1] && chapters[i + 1].pace === 'fast') {
      beats.push({ ch: i + 1, label: '小高潮', color: '#ef4444' });
      break;
    }
  }
  // 4. 爽点爆发: 首个高爽点强度章
  for (var i = 0; i < chapters.length; i++) {
    if (chapters[i].pleasure_level === 'high' || chapters[i].pleasure_level === 'critical') {
      beats.push({ ch: i + 1, label: '爽点爆发', color: '#ec4899' });
      break;
    }
  }
  // 5. 阶段收束
  if (chapters.length > 8) {
    beats.push({ ch: chapters.length, label: '阶段收束', color: '#a78bfa' });
  }
  return beats;
}

// ============================================================
// P0: 生成节奏模板 — 从拆书数据生成可执行的大纲参考
// ============================================================
function generateRhythmTemplate(data) {
  var summary = data.summary || {};
  var chapters = data.chapters || [];
  var paceDist = summary.pace_dist || {};
  var totalPace = 0;
  Object.keys(paceDist).forEach(function(k) { totalPace += paceDist[k] || 0; });
  var fastRatio = totalPace > 0 ? Math.round((paceDist.fast || 0) / totalPace * 100) : 0;
  var mediumRatio = totalPace > 0 ? Math.round((paceDist.medium || 0) / totalPace * 100) : 0;
  var slowRatio = totalPace > 0 ? Math.round((paceDist.slow || 0) / totalPace * 100) : 0;
  var beats = detectBeats(chapters);
  var pleasureDist = summary.pleasure_dist || {};
  var pleasureTypes = Object.keys(pleasureDist).filter(function(k) { return k !== 'none'; });
  var advice = '';
  if (fastRatio > 50) {
    advice = '该书节奏偏快（快节奏' + fastRatio + '%），建议大纲保持高频冲突和爽点投放，每2-3章一个小高潮。';
  } else if (slowRatio > 40) {
    advice = '该书偏慢热（慢节奏' + slowRatio + '%），前期重视铺垫和人设，第5章后开始加速爆发。';
  } else {
    advice = '该书节奏均衡（快' + fastRatio + '%/中' + mediumRatio + '%/慢' + slowRatio + '%），快慢交替张弛有度。';
  }
  var pleasureAdvice = pleasureTypes.length > 0
    ? '主要爽点：' + pleasureTypes.join('、') + '。建议每3-5章安排一次爽点。'
    : '暂无爽点数据。';
  return {
    book: data.book || '',
    genre: data.genre || '',
    paceRatio: { fast: fastRatio, medium: mediumRatio, slow: slowRatio },
    beats: beats,
    advice: advice,
    pleasureAdvice: pleasureAdvice,
    pleasureTypes: pleasureTypes
  };
}

// ============================================================
// P0: 应用到设计页 — 替代旧的"导入写作参考"
// ============================================================
function applyDisassemblyToDesign(name, displayName) {
  var showName = displayName || name;
  var template = generateRhythmTemplate(currentDisDetail || {});
  template.book = showName;
  try {
    sessionStorage.setItem('disassembly_to_design', JSON.stringify(template));
  } catch (e) {}
  showToast('正在将《' + showName + '》的节奏模板应用到设计页...');
  setTimeout(function() {
    navigate('design');
    setTimeout(function() {
      var pending = null;
      try { pending = JSON.parse(sessionStorage.getItem('disassembly_to_design')); } catch (e) {}
      if (pending) {
        // 应用到设计页：设置卷节奏目标 + 添加场景参考
        if (typeof DESIGN_DATA !== 'undefined' && DESIGN_DATA && DESIGN_DATA.volumes && DESIGN_DATA.volumes.length > 0) {
          DESIGN_DATA.volumes.forEach(function(v) {
            if (!v.rhythm_goal) v.rhythm_goal = pending.advice;
          });
          if (DESIGN_DATA.chapters && DESIGN_DATA.chapters.length > 0) {
            var ch = DESIGN_DATA.chapters[0];
            if (!ch.scenes) ch.scenes = [];
            var refNote = '[节奏参考·' + showName + '] ' + pending.advice + ' ' + pending.pleasureAdvice;
            if (!ch.scenes.some(function(s) { return s.indexOf('节奏参考') >= 0; })) {
              ch.scenes.push(refNote);
            }
          }
          if (typeof currentProject !== 'undefined' && currentProject && currentProject.id) {
            ProjectAPI.updateSkeleton(currentProject.id, { volumes: DESIGN_DATA.volumes, chapters: DESIGN_DATA.chapters }).then(function() {
              showToast('已将节奏模板应用到卷节奏目标和细纲参考');
              if (typeof showDesign === 'function') showDesign('rough');
              if (typeof loadDesignData === 'function') loadDesignData();
            });
          } else {
            showToast('节奏建议：' + pending.advice);
          }
        } else {
          showToast('节奏建议：' + pending.advice + ' ' + pending.pleasureAdvice);
        }
        sessionStorage.removeItem('disassembly_to_design');
      }
    }, 500);
  }, 300);
}

function renderDistributionBars(title, dist) {
  if (!dist) return '';
  var keys = Object.keys(dist);
  if (keys.length === 0) return '';
  var total = keys.reduce(function(sum, k) { return sum + (dist[k] || 0); }, 0);
  if (total === 0) return '';
  var colors = ['#38bdf8', '#f59e0b', '#22c55e', '#ef4444', '#a78bfa', '#f97316', '#14b8a6', '#ec4899'];
  return '<div class="dis-detail-section"><b>' + escapeHtml(title) + '</b>' +
    '<div class="dis-detail-bars">' + keys.map(function(k, i) {
      var v = dist[k] || 0;
      var pct = (v / total * 100).toFixed(1);
      return '<div class="dis-detail-bar">' +
        '<div class="dis-detail-bar-label"><span>' + escapeHtml(k) + '</span><span>' + pct + '% (' + v + ')</span></div>' +
        '<div class="dis-detail-bar-track"><div class="dis-detail-bar-fill" style="width:' + pct + '%;background:' + colors[i % colors.length] + '"></div></div>' +
      '</div>';
    }).join('') + '</div></div>';
}

// ============================================================
// 拆书三步法
// ============================================================
function renderThreeStepAnalysis(data) {
  var summary = data.summary || {};
  var genre = data.genre || '';
  var step1Content = buildStep1Core(genre, summary);
  var step2Content = buildStep2Detail(summary, data.chapters || [], data.total || 0);
  var step3Content = buildStep3Character(summary, data.chapters || []);
  return '<div class="dis-three-step">' +
    '<div class="dis-three-step-title">拆书三步法</div>' +
    '<div class="dis-three-step-intro">拆核心（卖点与金手指）→ 拆细节（节奏与大纲）→ 拆人性（人设与动机）</div>' +
    buildStepCard(1, '拆核心', '卖点与金手指', '找出这本书"凭什么让读者追下去"', step1Content) +
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
  html += '<div class="dis-step-row"><span class="dis-step-label">题材</span><span>' + escapeHtml(genre || '未标注') + '</span></div>';
  var conflictDist = summary.conflict_dist || {};
  var conflictKeys = Object.keys(conflictDist);
  if (conflictKeys.length > 0) {
    var topConflict = conflictKeys.reduce(function(a, b) { return (conflictDist[a] || 0) > (conflictDist[b] || 0) ? a : b; });
    html += '<div class="dis-step-row"><span class="dis-step-label">核心冲突</span><span>' + escapeHtml(topConflict) + '</span></div>';
  }
  var pleasureDist = summary.pleasure_dist || {};
  var pleasureKeys = Object.keys(pleasureDist).filter(function(k) { return k !== 'none'; });
  if (pleasureKeys.length > 0) {
    html += '<div class="dis-step-row"><span class="dis-step-label">主爽点</span><span>' + pleasureKeys.join(' / ') + '</span></div>';
  }
  var emotionDist = summary.emotion_dist || {};
  var emotionKeys = Object.keys(emotionDist);
  if (emotionKeys.length > 0) {
    var topEmotion = emotionKeys.reduce(function(a, b) { return (emotionDist[a] || 0) > (emotionDist[b] || 0) ? a : b; });
    html += '<div class="dis-step-row"><span class="dis-step-label">情绪基调</span><span>' + escapeHtml(topEmotion) + '</span></div>';
  }
  html += '</div>';
  // P0: 可借鉴卖点公式
  if (genre && topConflict && pleasureKeys.length > 0) {
    html += '<div class="dis-step-insight">' +
      '<div class="dis-step-insight-label">可借鉴卖点公式</div>' +
      '<div class="dis-step-insight-formula">' + escapeHtml(genre) + ' + ' + escapeHtml(topConflict) + ' + ' + pleasureKeys.map(escapeHtml).join(' / ') + '</div>' +
      '<div class="dis-step-insight-advice">→ 在你的大纲中设置类似冲突，每3章安排一次' + escapeHtml(pleasureKeys[0]) + '作为爽点钩子。</div>' +
    '</div>';
  }
  html += '<div class="dis-step-tip">提示：拆核心回答"这本书凭什么让读者追下去"。卖点 = 题材 + 冲突 + 爽点 的组合；金手指 = 主角的独特优势。</div>';
  return html;
}

function buildStep2Detail(summary, chapters, totalChapters) {
  var html = '<div class="dis-step-table">';
  var paceDist = summary.pace_dist || {};
  var paceKeys = Object.keys(paceDist);
  if (paceKeys.length > 0) {
    html += '<div class="dis-step-row"><span class="dis-step-label">节奏分布</span><span>' +
      paceKeys.map(function(k) { return k + '(' + (paceDist[k] || 0) + ')'; }).join(' / ') +
    '</span></div>';
  }
  var total = totalChapters || summary.chapters || chapters.length || 0;
  html += '<div class="dis-step-row"><span class="dis-step-label">总章节</span><span>' + total + '</span></div>';
  var avgWC = total > 0 ? Math.round((summary.total_words || 0) / total) : 0;
  html += '<div class="dis-step-row"><span class="dis-step-label">平均章字数</span><span>' + fmtNumber(avgWC) + '</span></div>';
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
  // P0: 节奏模式分析（前15章）
  if (chapters.length > 0) {
    var first15 = chapters.slice(0, 15);
    var pattern = first15.map(function(c) {
      var p = c.pace || '?';
      return p === 'fast' ? '快' : p === 'medium' ? '中' : p === 'slow' ? '慢' : '?';
    }).join('');
    var fastStreaks = [];
    var curStreak = 0;
    first15.forEach(function(c) {
      if (c.pace === 'fast') curStreak++;
      else { if (curStreak > 0) fastStreaks.push(curStreak); curStreak = 0; }
    });
    if (curStreak > 0) fastStreaks.push(curStreak);
    var avgStreak = fastStreaks.length > 0 ? (fastStreaks.reduce(function(a, b) { return a + b; }, 0) / fastStreaks.length).toFixed(1) : '0';
    var patternAdvice = '';
    if (parseFloat(avgStreak) >= 2) {
      patternAdvice = '检测到连续快节奏模式（平均' + avgStreak + '章快推后放慢）。建议你的大纲也保持类似节奏交替。';
    } else if (first15.filter(function(c) { return c.pace === 'slow'; }).length > first15.length * 0.5) {
      patternAdvice = '前期偏慢热，重视铺垫。建议前5章以建立世界观和人设为主，第6章开始加速。';
    } else {
      patternAdvice = '快慢交替，张弛有度。建议你的大纲也保持类似节奏变化。';
    }
    html += '<div class="dis-step-insight">' +
      '<div class="dis-step-insight-label">前15章节奏模式</div>' +
      '<div class="dis-step-insight-pattern">' + escapeHtml(pattern) + '</div>' +
      '<div class="dis-step-insight-advice">→ ' + patternAdvice + '</div>' +
    '</div>';
  }
  html += '<div class="dis-step-tip">提示：拆细节回答"作者如何控制节奏"。关注爽点投放频率、章节长度规律、节奏快慢交替模式。</div>';
  return html;
}

function buildStep3Character(summary, chapters) {
  var html = '<div class="dis-step-table">';
  var characters = summary.characters || [];
  if (characters.length > 0) {
    html += '<div class="dis-step-row"><span class="dis-step-label">人物数量</span><span>' + characters.length + '</span></div>';
    characters.slice(0, 5).forEach(function(c) {
      html += '<div class="dis-step-row"><span class="dis-step-label-small">' + escapeHtml(c.name || '未知') + '</span><span>' + escapeHtml(c.role || '') + '</span></div>';
    });
  } else {
    html += '<div class="dis-step-row"><span class="dis-step-label">人物</span><span>暂无数据</span></div>';
  }
  var emotionDist = summary.emotion_dist || {};
  var emotionKeys = Object.keys(emotionDist);
  if (emotionKeys.length > 1) {
    html += '<div class="dis-step-row"><span class="dis-step-label">情绪多样性</span><span>' + emotionKeys.length + ' 种情绪</span></div>';
  }
  html += '</div>';
  // P0: 情绪弧光（前15章）
  if (chapters && chapters.length > 0) {
    var emotions = chapters.slice(0, 15).map(function(c) { return c.emotion; }).filter(Boolean);
    var uniqueEmotions = [];
    emotions.forEach(function(e) { if (uniqueEmotions.indexOf(e) === -1) uniqueEmotions.push(e); });
    if (uniqueEmotions.length > 1) {
      html += '<div class="dis-step-insight">' +
        '<div class="dis-step-insight-label">情绪弧光（前15章）</div>' +
        '<div class="dis-step-insight-pattern">' + escapeHtml(uniqueEmotions.join(' → ')) + '</div>' +
        '<div class="dis-step-insight-advice">→ 角色情绪呈波浪式起伏。建议你的主角情绪也经历"低谷→反弹→新高"的循环。</div>' +
      '</div>';
    }
  }
  html += '<div class="dis-step-tip">提示：拆人性回答"角色为什么这么做"。关注人物动机、行为一致性、核心欲望和恐惧。</div>';
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

// 节奏可视化（含节拍标注）
function renderRhythmVisualization(chapters, totalChapters) {
  if (!chapters || chapters.length === 0) return '';
  var colorMap = { fast: '#ef4444', medium: '#f59e0b', slow: '#38bdf8' };
  var bars = chapters.map(function(c, i) {
    var pace = c.pace || c.rhythm || '';
    var color = colorMap[pace] || '#cbd5e1';
    var emotion = c.emotion || '';
    var title = '第' + (c.ch || i + 1) + '章 · ' + (c.wc || 0) + '字 · 节奏:' + pace + ' · 情绪:' + emotion;
    return '<div class="rhythm-bar" style="background:' + color + '" title="' + escapeHtml(title) + '"></div>';
  }).join('');
  var fastCount = chapters.filter(function(c) { return (c.pace || c.rhythm) === 'fast'; }).length;
  var slowCount = chapters.filter(function(c) { return (c.pace || c.rhythm) === 'slow'; }).length;
  var conflictCount = chapters.filter(function(c) { return c.conflict === true; }).length;
  var displayTotal = totalChapters || chapters.length;
  var summary = '<div class="rhythm-summary">' +
    '<span>展示前 ' + chapters.length + ' / ' + displayTotal + ' 章</span>' +
    '<span style="color:#ef4444">快节奏 ' + fastCount + '</span>' +
    '<span style="color:#38bdf8">慢节奏 ' + slowCount + '</span>' +
    '<span style="color:#f59e0b">含冲突 ' + conflictCount + '</span>' +
  '</div>';
  // P0: 节拍标注
  var beats = detectBeats(chapters);
  var beatHtml = beats.length > 0
    ? '<div class="beat-annotations">' +
        beats.map(function(b) {
          return '<span class="beat-ann-item"><span class="beat-ann-ch">第' + b.ch + '章</span><span class="beat-ann-label" style="border-color:' + b.color + ';color:' + b.color + '">' + b.label + '</span></span>';
        }).join('') +
      '</div>'
    : '';
  return '<div class="dis-detail-section">' +
    '<b>节奏曲线</b>' +
    '<div class="rhythm-viz-container">' + bars + '</div>' +
    '<div class="rhythm-legend">' +
      '<span><span class="rhythm-dot" style="background:#ef4444"></span>快节奏</span>' +
      '<span><span class="rhythm-dot" style="background:#f59e0b"></span>中节奏</span>' +
      '<span><span class="rhythm-dot" style="background:#38bdf8"></span>慢节奏</span>' +
      '<span><span class="rhythm-dot" style="background:#cbd5e1"></span>未标注</span>' +
    '</div>' +
    summary +
    beatHtml +
  '</div>';
}

// ============================================================
// P1: 多书对比模式
// ============================================================
var compareBooks = []; // 选中的对比书籍列表 [{name, title, summary, chapters}]

function toggleCompareBook(name, title) {
  var idx = compareBooks.findIndex(function(b) { return b.name === name; });
  if (idx >= 0) {
    compareBooks.splice(idx, 1);
  } else {
    if (compareBooks.length >= 3) {
      showToast('最多对比 3 本书');
      return;
    }
    // 查找已加载的数据
    var bookData = null;
    if (disassemblyData && disassemblyData.books) {
      for (var i = 0; i < disassemblyData.books.length; i++) {
        if (disassemblyData.books[i].key === name) {
          bookData = disassemblyData.books[i];
          break;
        }
      }
    }
    compareBooks.push({ name: name, title: title, summary: (bookData && bookData.summary) || {}, chapters: [] });
  }
  renderCompareBar();
}

function renderCompareBar() {
  var bar = $('#dis-compare-bar');
  if (!bar) return;
  if (compareBooks.length === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  bar.innerHTML =
    '<div class="compare-bar-info">' +
      '<span class="compare-bar-label">对比栏（' + compareBooks.length + '/3）</span>' +
      compareBooks.map(function(b, i) {
        return '<span class="compare-bar-item">' + escapeHtml(b.title) + '<button class="compare-bar-remove" onclick="toggleCompareBook(\'' + escapeHtml(b.name) + '\',\'' + escapeHtml(b.title) + '\')">&times;</button></span>';
      }).join('') +
    '</div>' +
    '<button class="btn btn-primary btn-sm" onclick="showCompareResult()" ' + (compareBooks.length < 2 ? 'disabled' : '') + '>开始对比</button>' +
    '<button class="btn btn-secondary btn-sm" onclick="clearCompare()">清空</button>';
}

function clearCompare() {
  compareBooks = [];
  renderCompareBar();
}

async function showCompareResult() {
  if (compareBooks.length < 2) {
    showToast('请至少选择 2 本书进行对比');
    return;
  }
  var detailArea = $('#disassembly-detail-area');
  var emptyState = $('#disassembly-empty-state');
  if (emptyState) emptyState.style.display = 'none';
  if (detailArea) {
    detailArea.style.display = 'block';
    detailArea.innerHTML = '<div class="dis-detail-loading"><svg class="spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg><span>加载对比数据...</span></div>';
  }
  try {
    // 逐本加载详情
    var results = [];
    for (var i = 0; i < compareBooks.length; i++) {
      var b = compareBooks[i];
      var { ok, data } = await apiGet('/api/disassembly/book?name=' + encodeURIComponent(b.name));
      if (ok && data) {
        b.summary = data.summary || {};
        b.chapters = data.chapters || [];
        b.genre = data.genre || '';
        results.push(b);
      }
    }
    if (results.length < 2) {
      if (detailArea) detailArea.innerHTML = '<div class="dis-detail-error">对比数据加载不完整，请重试</div>';
      return;
    }
    // 渲染对比结果
    if (detailArea) {
      detailArea.innerHTML = renderCompareResult(results);
    }
  } catch (err) {
    console.error('对比数据加载失败:', err);
    if (detailArea) {
      detailArea.innerHTML = '<div class="dis-detail-error">对比数据加载失败：' + escapeHtml(err.message || String(err)) + '</div>';
    }
  }
}

function renderCompareResult(books) {
  // 节奏对比
  var paceRows = books.map(function(b) {
    var pd = b.summary.pace_dist || {};
    var total = Object.keys(pd).reduce(function(s, k) { return s + (pd[k] || 0); }, 0);
    var fastPct = total > 0 ? Math.round((pd.fast || 0) / total * 100) : 0;
    var medPct = total > 0 ? Math.round((pd.medium || 0) / total * 100) : 0;
    var slowPct = total > 0 ? Math.round((pd.slow || 0) / total * 100) : 0;
    return '<div class="compare-row">' +
      '<div class="compare-row-label">' + escapeHtml(b.title) + '</div>' +
      '<div class="compare-bar-stack">' +
        '<div class="compare-bar-seg" style="width:' + fastPct + '%;background:#ef4444" title="快节奏 ' + fastPct + '%"></div>' +
        '<div class="compare-bar-seg" style="width:' + medPct + '%;background:#f59e0b" title="中节奏 ' + medPct + '%"></div>' +
        '<div class="compare-bar-seg" style="width:' + slowPct + '%;background:#38bdf8" title="慢节奏 ' + slowPct + '%"></div>' +
      '</div>' +
      '<div class="compare-row-vals"><span style="color:#ef4444">' + fastPct + '%</span> <span style="color:#f59e0b">' + medPct + '%</span> <span style="color:#38bdf8">' + slowPct + '%</span></div>' +
    '</div>';
  }).join('');

  // 爽点对比
  var pleasureRows = books.map(function(b) {
    var pd = b.summary.pleasure_dist || {};
    var types = Object.keys(pd).filter(function(k) { return k !== 'none'; });
    var total = Object.keys(pd).reduce(function(s, k) { return s + (pd[k] || 0); }, 0);
    var hitCount = types.reduce(function(s, k) { return s + (pd[k] || 0); }, 0);
    var density = total > 0 ? Math.round(hitCount / total * 100) : 0;
    return '<div class="compare-row">' +
      '<div class="compare-row-label">' + escapeHtml(b.title) + '</div>' +
      '<div class="compare-row-val">爽点密度 ' + density + '% · 类型: ' + (types.length > 0 ? escapeHtml(types.join('、')) : '无') + '</div>' +
    '</div>';
  }).join('');

  // 基础数据对比
  var metaRows = books.map(function(b) {
    var s = b.summary || {};
    var avg = s.chapters > 0 ? Math.round((s.total_words || 0) / s.chapters) : 0;
    return '<div class="compare-meta-col">' +
      '<div class="compare-meta-title">' + escapeHtml(b.title) + '</div>' +
      '<div class="compare-meta-item"><span>题材</span><b>' + escapeHtml(b.genre || '-') + '</b></div>' +
      '<div class="compare-meta-item"><span>章节</span><b>' + (s.chapters || 0) + '</b></div>' +
      '<div class="compare-meta-item"><span>总字数</span><b>' + fmtNumber(s.total_words || 0) + '</b></div>' +
      '<div class="compare-meta-item"><span>均章</span><b>' + fmtNumber(avg) + '</b></div>' +
    '</div>';
  }).join('');

  // 节奏曲线叠加
  var overlayBars = books.map(function(b, bi) {
    var colors = ['#ef4444', '#38bdf8', '#22c55e'];
    var color = colors[bi % colors.length];
    if (!b.chapters || b.chapters.length === 0) return '';
    var maxCh = Math.min(b.chapters.length, 30);
    var bars = b.chapters.slice(0, maxCh).map(function(c, ci) {
      var pace = c.pace || '';
      var opacity = pace === 'fast' ? 1 : pace === 'medium' ? 0.6 : pace === 'slow' ? 0.3 : 0.15;
      return '<div class="rhythm-bar" style="background:' + color + ';opacity:' + opacity + '" title="' + escapeHtml(b.title + ' 第' + (c.ch || ci+1) + '章 ' + pace) + '"></div>';
    }).join('');
    return '<div class="compare-overlay-row"><span class="compare-overlay-label" style="color:' + color + '">' + escapeHtml(b.title) + '</span><div class="rhythm-viz-container" style="flex:1">' + bars + '</div></div>';
  }).join('');

  return '<div class="dis-detail-header">' +
    '<div class="dis-detail-header-info">' +
      '<h3 class="dis-detail-title">多书对比</h3>' +
      '<div class="dis-detail-meta-row">' +
        books.map(function(b) { return '<span class="dis-meta-chip">' + escapeHtml(b.title) + '</span>'; }).join('') +
      '</div>' +
    '</div>' +
    '<button class="btn btn-secondary btn-sm" onclick="clearCompare();loadDisassemblyData();">退出对比</button>' +
  '</div>' +
  '<div class="dis-detail-body">' +
    '<div class="dis-detail-section"><b>基础数据对比</b><div class="compare-meta-grid">' + metaRows + '</div></div>' +
    '<div class="dis-detail-section"><b>节奏分布对比</b>' +
      '<div class="compare-rows">' + paceRows + '</div>' +
      '<div class="rhythm-legend">' +
        '<span><span class="rhythm-dot" style="background:#ef4444"></span>快节奏</span>' +
        '<span><span class="rhythm-dot" style="background:#f59e0b"></span>中节奏</span>' +
        '<span><span class="rhythm-dot" style="background:#38bdf8"></span>慢节奏</span>' +
      '</div>' +
    '</div>' +
    '<div class="dis-detail-section"><b>节奏曲线叠加</b>' +
      '<div class="compare-overlay">' + overlayBars + '</div>' +
    '</div>' +
    '<div class="dis-detail-section"><b>爽点对比</b>' +
      '<div class="compare-rows">' + pleasureRows + '</div>' +
    '</div>' +
  '</div>';
}

// ============================================================
// P1: 拆书八步法导航
// ============================================================
var _disSteps = [
  { num: 1, name: '拆主线', desc: '一句话概括核心事件链', icon: '&#128202;' },
  { num: 2, name: '拆人设', desc: '主角性格、背景、成长弧光', icon: '&#128100;' },
  { num: 3, name: '拆爽点', desc: '爽点类型、频率、投放节奏', icon: '&#128293;' },
  { num: 4, name: '拆节奏', desc: '快慢交替、冲突分布、高潮位置', icon: '&#127911;' },
  { num: 5, name: '拆悬念', desc: '伏笔埋设、悬念回收、章末钩子', icon: '&#128269;' },
  { num: 6, name: '拆对话', desc: '对话风格、信息密度、推动力', icon: '&#128172;' },
  { num: 7, name: '拆场景', desc: '场景构建、环境渲染、氛围控制', icon: '&#127748;' },
  { num: 8, name: '拆伏笔', desc: '伏笔回收率、跨章伏笔、暗线', icon: '&#128274;' }
];

function renderEightStepNav(data) {
  var summary = data.summary || {};
  var chapters = data.chapters || [];
  // 自动填充各步骤的可用信息
  _disSteps[0].content = buildStep1Core(data.genre, summary); // 拆主线 = 拆核心
  _disSteps[1].content = buildStep3Character(summary, chapters); // 拆人设 = 拆人性
  _disSteps[2].content = buildStep2Detail(summary, chapters, data.total || 0); // 拆爽点/节奏 = 拆细节
  _disSteps[3].content = renderRhythmVisualization(chapters, data.total || 0); // 拆节奏 = 节奏曲线
  _disSteps[4].content = buildStep5Suspense(chapters); // 拆悬念
  _disSteps[5].content = buildStep6Dialogue(summary); // 拆对话
  _disSteps[6].content = buildStep7Scene(chapters); // 拆场景
  _disSteps[7].content = buildStep8Foreshadow(chapters); // 拆伏笔

  var navHtml = _disSteps.map(function(s) {
    return '<button class="dis-nav-btn" onclick="showDisStep(' + s.num + ')" id="dis-nav-' + s.num + '">' +
      '<span class="dis-nav-icon">' + s.icon + '</span>' +
      '<span class="dis-nav-name">' + s.name + '</span>' +
    '</button>';
  }).join('');

  return '<div class="dis-eight-step">' +
    '<div class="dis-eight-step-title">拆书八步法 <span class="dis-eight-step-hint">从宏观到微观逐层解剖</span></div>' +
    '<div class="dis-nav-row">' + navHtml + '</div>' +
    '<div class="dis-step-content" id="dis-step-content">' +
      '<div class="text-muted" style="padding:20px;text-align:center;">点击上方步骤查看拆解结果</div>' +
    '</div>' +
  '</div>';
}

function showDisStep(num) {
  $$('.dis-nav-btn').forEach(function(btn) { btn.classList.remove('active'); });
  var navBtn = $('#dis-nav-' + num);
  if (navBtn) navBtn.classList.add('active');
  var contentEl = $('#dis-step-content');
  if (!contentEl) return;
  var step = _disSteps.find(function(s) { return s.num === num; });
  if (!step) return;
  contentEl.innerHTML =
    '<div class="dis-step-detail">' +
      '<div class="dis-step-detail-header">' +
        '<span class="dis-step-detail-num">步' + step.num + '</span>' +
        '<div><div class="dis-step-detail-name">' + step.name + '</div><div class="dis-step-detail-desc">' + step.desc + '</div></div>' +
      '</div>' +
      '<div class="dis-step-detail-body">' + (step.content || '<div class="text-muted">暂无数据</div>') + '</div>' +
    '</div>';
}

// 步骤5: 拆悬念
function buildStep5Suspense(chapters) {
  if (!chapters || chapters.length === 0) return '<div class="text-muted">暂无章节数据</div>';
  var conflictChapters = chapters.filter(function(c) { return c.conflict; });
  var conflictRate = chapters.length > 0 ? Math.round(conflictChapters.length / chapters.length * 100) : 0;
  // 检测章末钩子（最后几章的快节奏）
  var lastChapters = chapters.slice(-5);
  var lastFast = lastChapters.filter(function(c) { return c.pace === 'fast'; }).length;
  var html = '<div class="dis-step-table">' +
    '<div class="dis-step-row"><span class="dis-step-label">含冲突章节</span><span>' + conflictChapters.length + ' / ' + chapters.length + ' (' + conflictRate + '%)</span></div>' +
    '<div class="dis-step-row"><span class="dis-step-label">末尾快节奏</span><span>' + lastFast + ' / ' + lastChapters.length + ' 章</span></div>' +
  '</div>';
  if (conflictRate > 40) {
    html += '<div class="dis-step-insight"><div class="dis-step-insight-label">悬念分析</div><div class="dis-step-insight-advice">→ 冲突密度较高（' + conflictRate + '%），悬念感强。建议你的大纲保持每3章至少1次冲突。</div></div>';
  } else {
    html += '<div class="dis-step-insight"><div class="dis-step-insight-label">悬念分析</div><div class="dis-step-insight-advice">→ 冲突密度偏低（' + conflictRate + '%），可能偏日常/铺垫型。建议适当增加冲突章节。</div></div>';
  }
  return html;
}

// 步骤6: 拆对话
function buildStep6Dialogue(summary) {
  var html = '<div class="dis-step-table">' +
    '<div class="dis-step-row"><span class="dis-step-label">数据来源</span><span>需文本级分析（当前管线仅统计节奏/情绪）</span></div>' +
  '</div>';
  html += '<div class="dis-step-insight"><div class="dis-step-insight-label">拆对话要点</div><div class="dis-step-insight-advice">→ 对话应推动剧情或塑造人物，避免无信息闲聊。关注：对话占比、角色语气差异、潜台词设计。</div></div>';
  return html;
}

// 步骤7: 拆场景
function buildStep7Scene(chapters) {
  if (!chapters || chapters.length === 0) return '<div class="text-muted">暂无章节数据</div>';
  var avgWc = chapters.length > 0 ? Math.round(chapters.reduce(function(s, c) { return s + (c.wc || 0); }, 0) / chapters.length) : 0;
  var wcVariance = 0;
  if (chapters.length > 1) {
    var deviations = chapters.map(function(c) { return Math.abs((c.wc || 0) - avgWc); });
    wcVariance = Math.round(deviations.reduce(function(a, b) { return a + b; }, 0) / deviations.length);
  }
  var html = '<div class="dis-step-table">' +
    '<div class="dis-step-row"><span class="dis-step-label">平均章字数</span><span>' + fmtNumber(avgWc) + '</span></div>' +
    '<div class="dis-step-row"><span class="dis-step-label">字数波动</span><span>±' + fmtNumber(wcVariance) + '</span></div>' +
  '</div>';
  if (wcVariance > avgWc * 0.3) {
    html += '<div class="dis-step-insight"><div class="dis-step-insight-label">场景分析</div><div class="dis-step-insight-advice">→ 章节长度波动大，说明作者会根据场景重要性调整篇幅。大场面用长章，过渡用短章。</div></div>';
  } else {
    html += '<div class="dis-step-insight"><div class="dis-step-insight-label">场景分析</div><div class="dis-step-insight-advice">→ 章节长度均匀，节奏稳定。建议你的大纲也保持一致的章长。</div></div>';
  }
  return html;
}

// 步骤8: 拆伏笔
function buildStep8Foreshadow(chapters) {
  var html = '<div class="dis-step-table">' +
    '<div class="dis-step-row"><span class="dis-step-label">数据来源</span><span>需文本级语义分析（当前管线暂不支持自动伏笔追踪）</span></div>' +
  '</div>';
  html += '<div class="dis-step-insight"><div class="dis-step-insight-label">拆伏笔要点</div><div class="dis-step-insight-advice">→ 关注：伏笔回收率（理想>80%）、跨章伏笔间隔（5-20章最佳）、暗线数量。手动拆书时可标注每章的伏笔埋设和回收。</div></div>';
  return html;
}
