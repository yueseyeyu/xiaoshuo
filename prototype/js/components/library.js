"use strict";

async function loadLibraryData() {
  if (DATA) return DATA;
  const { ok, data, error } = await apiGet('/api/books', 60000);
  if (ok && data) {
    DATA = data;
    return DATA;
  }
  console.error('[Library] 加载失败，使用空数据', error);
  DATA = { books: [], genres: [], counts: [], tasks: [] };
  return DATA;
}
function renderGenreTabs(countsOverride) {
  const counts = countsOverride || DATA.counts || [];
  const tabs = $('#genre-tabs');
  if (!tabs) return;
  tabs.innerHTML = counts.map(([genre, count]) =>
    '<button class="genre-tab' + (genre === currentGenre ? ' active' : '') + '" data-genre="' + genre + '" onclick="filterLibrary(\'' + genre + '\')">' + genre + '(' + count + ')</button>'
  ).join('');
}
function renderGenreRank(countsMap, total) {
  const container = $('#genre-rank-list');
  if (!container) return;
  if (!total) {
    container.innerHTML = '<div class="genre-rank-empty">暂无数据</div>';
    return;
  }
  const entries = Object.entries(countsMap || {})
    .filter(([_, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  container.innerHTML = entries.map(([genre, count]) => {
    const width = Math.max(2, Math.round((count / total) * 100));
    const active = genre === currentGenre ? ' active' : '';
    const pct = ((count / total) * 100).toFixed(1) + '%';
    return '<button class="genre-rank-item' + active + '" onclick="filterLibrary(\'' + genre + '\')" title="' + genre + ' 占 ' + pct + ' · 点击筛选">' +
      '<span class="genre-rank-name">' + genre + '</span>' +
      '<div class="genre-rank-bar-track"><div class="genre-rank-fill" style="width:' + width + '%"></div></div>' +
      '<span class="genre-rank-count">' + count + '</span>' +
    '</button>';
  }).join('');
}
function filterLibrary(genre) {
  currentGenre = genre;
  renderLibrary();
}
function sortLibrary(key) {
  if (librarySort.key === key) {
    librarySort.dir = librarySort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    librarySort = { key: key, dir: 'asc' };
  }
  renderLibrary();
}
function toggleBookSelection(idx, event) {
  if (event) event.stopPropagation();
  if (selectedBookIds.has(idx)) selectedBookIds.delete(idx);
  else selectedBookIds.add(idx);
  renderLibrary();
}
function batchDisassemble() {
  const ids = Array.from(selectedBookIds);
  if (ids.length === 0) { showToast('请先选择要拆书的书籍'); return; }
  ids.forEach((idx) => {
    const b = DATA.books[idx];
    if (!b) return;
    tasks.push({
      id: 'task-' + Date.now() + '-' + idx,
      type: 'full',
      typeLabel: '拆书分析',
      books: ['《' + b.title + '》'],
      genre: b.genre,
      status: 'queued',
      progress: 0,
      message: '等待 GPU 资源...'
    });
  });
  selectedBookIds.clear();
  saveTasks();
  renderTasks();
  navigate('disassembly');
  showToast('已创建 ' + ids.length + ' 个拆书任务');
}
function getBookStatus(b) {
  if (b.status === 'analyzed') return { label: '已拆书', icon: '✅', cls: 'success' };
  if (b.status === 'analyzing') return { label: '分析中', icon: '🔄', cls: 'running' };
  if (b.status === 'failed') return { label: '失败', icon: '❌', cls: 'danger' };
  if (b.status === 'imported') return { label: '待分析', icon: '⏳', cls: 'pending' };
  return { label: '待分析', icon: '⏳', cls: 'pending' };
}
// v8.5: 不再伪造评分，仅返回后端真实数据
function getBookScore(b) {
  return b.score != null ? b.score : null;
}
function getBookCards(b) {
  return b.techniqueCards != null ? b.techniqueCards : null;
}
function importBook() {
  const input = $('#book-file-input');
  if (input) input.click();
}
function handleBookFileSelect(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(evt) {
    const text = evt.target.result || '';
    const sizeKb = Math.round(file.size / 1024);
    // 粗略估算中文字数：按 1.5 字节/字，并取文本实际 token 数参考
    const estimatedWords = Math.max(1, Math.round(file.size / 1.8));
    const rawName = file.name.replace(/\.txt$/i, '');
    // 简单解析 "《书名》作者：作者名" 或 "书名_作者"
    let title = rawName;
    let author = '本地导入';
    const authorMatch = rawName.match(/作者[：:]\s*(.+)$/);
    if (authorMatch) {
      title = rawName.split(/作者[：:]/)[0].trim();
      author = authorMatch[1].trim();
    } else if (rawName.includes('_')) {
      const parts = rawName.split('_');
      title = parts[0].trim();
      author = parts.slice(1).join('_').trim() || '本地导入';
    }
    // 默认题材：按书名关键词猜测，否则让用户后续在详情编辑
    const genreHints = { '末世': '末世', '末日': '末世', '丧尸': '末世', '无限': '无限流', '恐怖': '悬疑', '惊悚': '悬疑', '仙侠': '仙侠', '洪荒': '洪荒', '科幻': '科幻', '都市': '都市', '历史': '历史' };
    let genre = '都市';
    for (const [hint, g] of Object.entries(genreHints)) {
      if (title.includes(hint)) { genre = g; break; }
    }
    DATA.books.unshift({
      title: title,
      author: author,
      wordCount: estimatedWords,
      size_kb: sizeKb,
      genre: genre,
      file: file.name,
      rhythm_csv: 'rhythm_' + rawName + '.csv',
      status: 'imported'
    });
    currentGenre = '全部';
    $('#library-search').value = '';
    renderLibrary();
    showToast('已导入《' + title + '》(' + fmtNumber(estimatedWords) + ' 字)');
  };
  reader.onerror = function() {
    showToast('文件读取失败');
  };
  reader.readAsText(file, 'utf-8');
  e.target.value = '';
}
function renderLibrary() {
  const grid = $('#book-grid');
  if (!grid) return;
  const totalBooks = DATA.books.length;
  const genres = DATA.genres || [];
  const totalWords = DATA.books.reduce((sum, b) => sum + (b.wordCount || 0), 0);
  const totalChapters = Math.round(totalWords / 2000);
  // API 数据增强：优先使用后端统计
  const apiStats = (typeof appState !== 'undefined' && appState.apiData && appState.apiData.stats) || {};
  const displayBooks = apiStats.total_books || totalBooks;
  const displayGenres = apiStats.genres || genres.length;
  const libKpiCount = $('#lib-kpi-count');
  const libKpiChapters = $('#lib-kpi-chapters');
  const libKpiGenres = $('#lib-kpi-genres');
  const libKpiPending = $('#lib-kpi-pending');
  const pendingBooks = DATA.books.filter((b) => !b.status || b.status === 'imported' || b.status === 'pending').length;
  if (libKpiCount) libKpiCount.textContent = displayBooks;
  if (libKpiChapters) libKpiChapters.textContent = fmtNumber(totalChapters);
  if (libKpiGenres) libKpiGenres.textContent = displayGenres;
  if (libKpiPending) libKpiPending.textContent = pendingBooks;
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
  const baseForTabs = query ? DATA.books : (currentGenre === '全部' ? DATA.books : DATA.books.filter((b) => b.genre === currentGenre));
  const searched = query ? baseForTabs.filter((b) =>
    (b.title && b.title.toLowerCase().includes(query)) ||
    (b.author && b.author.toLowerCase().includes(query)) ||
    (b.genre && b.genre.toLowerCase().includes(query))
  ) : baseForTabs;
  const countsMap = {};
  searched.forEach((b) => { countsMap[b.genre] = (countsMap[b.genre] || 0) + 1; });
  const tabCounts = [['全部', searched.length]].concat((DATA.genres || []).map((g) => [g, countsMap[g] || 0]));
  renderGenreTabs(tabCounts);
  renderGenreRank(countsMap, searched.length);
  grid.className = 'library-content list-view';
  filtered = applyLibrarySort(filtered);
  const contentHtml = renderLibraryList(filtered);
  grid.innerHTML = contentHtml || '<div class="empty-state">' + (query ? '未找到含「' + escapeHtml(query) + '」的书籍' : '暂无该题材书籍') + '</div>';
  $$('#genre-tabs .genre-tab').forEach((t) => t.classList.toggle('active', t.dataset.genre === currentGenre));
}
function applyLibrarySort(books) {
  const key = librarySort.key;
  const dir = librarySort.dir === 'asc' ? 1 : -1;
  return [...books].sort((a, b) => {
    let va, vb;
    if (key === 'title') { va = a.title || ''; vb = b.title || ''; }
    else if (key === 'author') { va = a.author || ''; vb = b.author || ''; }
    else if (key === 'genre') { va = a.genre || ''; vb = b.genre || ''; }
    else if (key === 'wordCount') { va = a.wordCount || 0; vb = b.wordCount || 0; }
    else if (key === 'chapters') { va = (a.disassembly && a.disassembly.chapters) || a.totalChapters || 0; vb = (b.disassembly && b.disassembly.chapters) || b.totalChapters || 0; }
    else if (key === 'status') { va = a.status || ''; vb = b.status || ''; }
    else { va = a.title || ''; vb = b.title || ''; }
    if (typeof va === 'string') return dir * va.localeCompare(vb, 'zh-CN');
    return dir * (va - vb);
  });
}
function renderLibraryList(books) {
  const allFilteredIdx = books.map((b) => DATA.books.indexOf(b));
  const allSelected = allFilteredIdx.length > 0 && allFilteredIdx.every((idx) => selectedBookIds.has(idx));
  const someSelected = allFilteredIdx.some((idx) => selectedBookIds.has(idx));
  const headerCheckbox = '<label class="book-list-checkbox" onclick="event.stopPropagation();toggleSelectAllBooks()">' +
    '<input type="checkbox" ' + (allSelected ? 'checked' : '') + (someSelected && !allSelected ? ' indeterminate' : '') + '>' +
    '<span></span></label>';
  const headers = [
    { key: 'check', label: headerCheckbox, sortable: false },
    { key: 'title', label: '书名', sortable: true },
    { key: 'author', label: '作者', sortable: true },
    { key: 'genre', label: '题材', sortable: true },
    { key: 'tags', label: '标签', sortable: false },
    { key: 'wordCount', label: '字数', sortable: true },
    { key: 'chapters', label: '章节', sortable: true },
    { key: 'status', label: '状态', sortable: true },
  ];
  const headerHtml = '<div class="book-list-header">' + headers.map((h) => {
    if (!h.sortable) return '<div class="book-list-col col-' + h.key + '">' + h.label + '</div>';
    const active = librarySort.key === h.key ? ' active' : '';
    const arrow = librarySort.key === h.key ? (librarySort.dir === 'asc' ? ' ↑' : ' ↓') : '';
    return '<button class="book-list-col col-' + h.key + active + '" onclick="sortLibrary(\'' + h.key + '\')">' + h.label + arrow + '</button>';
  }).join('') + '</div>';
  const rows = books.map((b) => {
    const idx = DATA.books.indexOf(b);
    const status = getBookStatus(b);
    const genreColor = coverStyle(b.title, b.genre);
    const checked = selectedBookIds.has(idx) ? 'checked' : '';
    const selectedCls = selectedBookIds.has(idx) ? ' selected' : '';
    const checkbox = '<label class="book-list-checkbox" onclick="event.stopPropagation();toggleBookSelection(' + idx + ', event)">' +
      '<input type="checkbox" ' + checked + '>' +
      '<span></span></label>';
    const chapterCount = b.disassembly && b.disassembly.chapters ? b.disassembly.chapters : (b.totalChapters || 0);
    const chapterText = chapterCount > 0 ? fmtNumber(chapterCount) : '<span style="color:var(--text-muted)">-</span>';
    // 标签：优先用后端 tags，其次 tagPools，至少展示题材
    var tags = (b.tags && b.tags.length) ? b.tags : ((DATA.tagPools && DATA.tagPools[b.title]) || []);
    if (tags.length === 0 && b.genre) tags = [b.genre];
    // 第一个标签为大类，用不同的样式
    var tagHtml = tags.slice(0, 4).map(function(t, i) {
      var cls = i === 0 ? 'book-tag book-tag-primary' : 'book-tag';
      return '<span class="' + cls + '">' + escapeHtml(t) + '</span>';
    }).join('');
    return '<div class="book-list-row' + selectedCls + '" data-index="' + idx + '" onclick="selectBook(' + idx + ')">' +
      '<div class="book-list-col col-check">' + checkbox + '</div>' +
      '<div class="book-list-col col-title"><span class="book-list-title">' + escapeHtml(b.title) + '</span></div>' +
      '<div class="book-list-col col-author">' + escapeHtml(b.author || '') + '</div>' +
      '<div class="book-list-col col-genre"><span class="book-list-dot" style="background:' + genreColor + '"></span><span class="book-list-genre">' + escapeHtml(b.genre || '') + '</span></div>' +
      '<div class="book-list-col col-tags">' + tagHtml + '</div>' +
      '<div class="book-list-col col-wordCount">' + fmtNumber(b.wordCount || 0) + '</div>' +
      '<div class="book-list-col col-chapters">' + chapterText + '</div>' +
      '<div class="book-list-col col-status"><span class="book-list-status ' + status.cls + '">' + status.label + '</span></div>' +
    '</div>';
  }).join('');
  const batchBar = selectedBookIds.size > 0
    ? '<div class="book-list-batch-bar">' +
        '<span class="batch-count">已选 ' + selectedBookIds.size + ' 本</span>' +
        '<div class="batch-actions">' +
          '<button class="btn btn-secondary btn-sm" onclick="clearBookSelection()">取消选择</button>' +
          '<button class="btn btn-primary btn-sm" onclick="batchDisassemble()">批量拆书</button>' +
        '</div>' +
      '</div>'
    : '';
  return headerHtml + '<div class="book-list-body">' + rows + '</div>' + batchBar;
}
function renderBookDisassemblyTags(b) {
  const d = b.disassembly;
  if (!d) return '';
  const chapters = d.chapters;
  const emotion = d.emotion_dist || {};
  const pace = d.pace_dist || {};
  const tags = [];
  if (chapters) tags.push('<span class="tag-chapters">' + chapters + '章</span>');
  let totalEmotion = 0;
  let maxEmotion = '';
  let maxEmotionCount = 0;
  Object.keys(emotion).forEach(function(k) {
    const v = emotion[k] || 0;
    totalEmotion += v;
    if (v > maxEmotionCount) { maxEmotionCount = v; maxEmotion = k; }
  });
  if (maxEmotion && totalEmotion > 0) {
    tags.push('<span class="tag-emotion">' + escapeHtml(maxEmotion) + ' ' + (maxEmotionCount / totalEmotion * 100).toFixed(0) + '%</span>');
  }
  let totalPace = 0;
  let fastCount = 0;
  Object.keys(pace).forEach(function(k) {
    const v = pace[k] || 0;
    totalPace += v;
    if (k === 'fast') fastCount += v;
  });
  if (totalPace > 0) {
    tags.push('<span class="tag-pace">快节奏 ' + (fastCount / totalPace * 100).toFixed(0) + '%</span>');
  }
  return '<div class="book-disassembly-tags">' + tags.join('') + '</div>';
}
function selectBook(idx) {
  selectedBookIndex = idx;
  const b = DATA.books[idx];
  const tags = (b.tags && b.tags.length) ? b.tags : ((DATA.tagPools && DATA.tagPools[b.title]) || [b.genre].filter(Boolean));
  appShell.classList.remove('no-detail');
  appShell.classList.add('detail-open');
  $('#detail-empty').style.display = 'none';
  const content = $('#detail-content');
  content.style.display = 'block';
  const cover = coverText(b.title);
  const singleClass = cover.length === 1 ? 'cover-single' : '';
  $('#detail-cover').innerHTML = '<span class="cover-abbr ' + singleClass + '">' + cover + '</span>';
  $('#detail-cover').style.background = coverStyle(b.title, b.genre);
  $('#detail-title').textContent = b.title;
  $('#detail-meta').innerHTML = '<div>作者：' + escapeHtml(b.author || '') + '</div><div>题材：' + escapeHtml(b.genre || '') + '</div><div>字数：' + fmtNumber(b.wordCount || 0) + ' 字</div><div>大小：' + fmtSize(b.size_kb || 0) + '</div>';
  $('#detail-tags').innerHTML = tags.map((t, i) => '<span class="book-tag' + (i === 0 ? ' book-tag-primary' : '') + '">' + escapeHtml(t) + '</span>').join('');
  // 移除文件路径展示，改为操作按钮区
  var status = getBookStatus(b);
  var isAnalyzed = b.status === 'analyzed';
  var actionBtn = isAnalyzed
    ? '<button class="btn btn-secondary detail-action" style="margin-bottom:8px;" onclick="navigate(\'disassembly\')">查看拆书</button>'
    : '';
  actionBtn += '<button class="btn btn-primary detail-action" onclick="startAnalysisFromDetail()">' + (isAnalyzed ? '重新分析' : '开始分析') + '</button>';
  $('#detail-files').innerHTML = actionBtn;
}
function closeDetail() {
  appShell.classList.add('no-detail');
  appShell.classList.remove('detail-open');
  selectedBookIndex = null;
}
