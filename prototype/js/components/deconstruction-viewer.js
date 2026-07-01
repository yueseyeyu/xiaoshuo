"use strict";

// ============================================================
// 小说解构查看器 — 五段式结构化分析展示
// 对接后端: /api/creative/deconstruct
// ============================================================

let deconstructionData = null;
let deconstructableBooks = [];

async function loadDeconstructableBooks(genre) {
  genre = genre || currentGenre || '末世';
  const { ok, data } = await apiGet('/api/creative/deconstruct/books?genre=' + encodeURIComponent(genre));
  if (ok && data) {
    deconstructableBooks = data.books || [];
  }
  return deconstructableBooks;
}

async function runDeconstruction(text, filePath, maxChapters) {
  const body = { text: text || '', file_path: filePath || '', max_chapters: maxChapters || null };
  const { ok, data, error } = await apiPost('/api/creative/deconstruct', body, 120000);
  if (ok && data) {
    deconstructionData = data;
    return data;
  }
  console.error('[Deconstruct] 解构失败', error);
  return null;
}

function renderDeconstructionResult(data) {
  if (!data) return '<div class="text-muted" style="padding:16px;">暂无解构数据</div>';

  var html = '<div class="deconstruct-result">';

  // 1. 题材标签
  var gt = data.genre_tags || {};
  html += '<div class="deconstruct-section">' +
    '<div class="deconstruct-section-title">' +
      '<span class="deconstruct-icon">1</span>题材标签' +
    '</div>' +
    '<div class="deconstruct-grid-2">' +
      renderTagRow('主题材', gt.main_genre) +
      renderTagRow('副题材', gt.sub_genres) +
      renderTagRow('爽点类型', gt.pleasure_type) +
      renderTagRow('情绪基调', gt.mood) +
      renderTagRow('通用标签', gt.tags) +
      renderTagRow('开头Hook', gt.opening_hook) +
      renderTagRow('首个高潮', gt.first_climax && gt.first_climax.desc ? '第' + gt.first_climax.chapter + '章: ' + gt.first_climax.desc : '') +
      renderTagRow('主高潮', gt.major_climax && gt.major_climax.desc ? '第' + gt.major_climax.chapter + '章: ' + gt.major_climax.desc : '') +
      renderTagRow('节奏曲线', gt.rhythm_curve) +
    '</div>' +
  '</div>';

  // 2. 结构拆解
  var st = data.structure || {};
  html += '<div class="deconstruct-section">' +
    '<div class="deconstruct-section-title">' +
      '<span class="deconstruct-icon">2</span>结构拆解' +
    '</div>' +
    '<div class="deconstruct-grid-2">' +
      renderTagRow('主角人设', st.protagonist_design) +
      renderTagRow('反派模板', st.antagonist_template) +
      renderTagRow('配角', st.supporting_roles) +
      renderTagRow('情节结构', st.plot_structure) +
      renderTagRow('总章数', st.total_chapters) +
      renderTagRow('总字数', st.total_chars ? fmtNumber(st.total_chars) : '') +
      renderTagRow('平均章字数', st.avg_chapter_chars ? fmtNumber(st.avg_chapter_chars) : '') +
    '</div>' +
  '</div>';

  // 3. 人物拆解
  var ch = data.characters || {};
  var chars = ch.characters || [];
  var arcs = ch.character_arcs || [];
  var relations = ch.relationship_network || [];
  var motivations = ch.motivation_chain || [];
  html += '<div class="deconstruct-section">' +
    '<div class="deconstruct-section-title">' +
      '<span class="deconstruct-icon">3</span>人物拆解' +
    '</div>' +
    (chars.length ? '<div class="deconstruct-subsection"><b>角色列表 (' + chars.length + ')</b><div class="deconstruct-list">' +
      chars.slice(0, 10).map(function(c) { return '<div class="deconstruct-list-item">' + escapeHtml(typeof c === 'string' ? c : (c.name || JSON.stringify(c))) + '</div>'; }).join('') + '</div></div>' : '') +
    (arcs.length ? '<div class="deconstruct-subsection"><b>角色弧光</b><div class="deconstruct-list">' +
      arcs.map(function(a) { return '<div class="deconstruct-list-item">' + escapeHtml(typeof a === 'string' ? a : (a.name || '') + '：' + (a.arc || a.summary || JSON.stringify(a))) + '</div>'; }).join('') + '</div></div>' : '') +
    (relations.length ? '<div class="deconstruct-subsection"><b>关系网</b><div class="deconstruct-list">' +
      relations.map(function(r) { return '<div class="deconstruct-list-item">' + escapeHtml(typeof r === 'string' ? r : ((r.from || r.a || '') + ' → ' + (r.to || r.b || '') + '：' + (r.relation || r.type || ''))) + '</div>'; }).join('') + '</div></div>' : '') +
    (motivations.length ? '<div class="deconstruct-subsection"><b>动机链</b><div class="deconstruct-list">' +
      motivations.map(function(m) { return '<div class="deconstruct-list-item">' + escapeHtml(typeof m === 'string' ? m : JSON.stringify(m)) + '</div>'; }).join('') + '</div></div>' : '') +
  '</div>';

  // 4. 可借鉴元素
  var br = data.borrowable || {};
  html += '<div class="deconstruct-section">' +
    '<div class="deconstruct-section-title">' +
      '<span class="deconstruct-icon">4</span>可借鉴元素' +
    '</div>' +
    '<div class="deconstruct-grid-2">' +
      renderTagRow('结构借鉴', br.structure_borrow) +
      renderTagRow('情绪借鉴', br.emotion_borrow) +
      renderTagRow('台词借鉴', br.dialogue_borrow) +
    '</div>' +
  '</div>';

  // 5. 避雷清单
  var wn = data.warnings || {};
  var complaints = wn.reader_complaints || [];
  var collapses = wn.collapse_risks || [];
  var qualityWarns = wn.quality_warnings || [];
  html += '<div class="deconstruct-section deconstruct-warnings">' +
    '<div class="deconstruct-section-title">' +
      '<span class="deconstruct-icon warn">5</span>避雷清单' +
    '</div>' +
    (complaints.length ? '<div class="deconstruct-subsection"><b>读者吐槽点</b><div class="deconstruct-list">' +
      complaints.map(function(c) { return '<div class="deconstruct-list-item warn">' + escapeHtml(typeof c === 'string' ? c : (c.point || JSON.stringify(c))) + '</div>'; }).join('') + '</div></div>' : '') +
    (collapses.length ? '<div class="deconstruct-subsection"><b>后期崩坏风险</b><div class="deconstruct-list">' +
      collapses.map(function(c) { return '<div class="deconstruct-list-item warn">' + escapeHtml(typeof c === 'string' ? c : (c.reason || c.risk || JSON.stringify(c))) + '</div>'; }).join('') + '</div></div>' : '') +
    (qualityWarns.length ? '<div class="deconstruct-subsection"><b>质量警告</b><div class="deconstruct-list">' +
      qualityWarns.map(function(c) { return '<div class="deconstruct-list-item warn">' + escapeHtml(typeof c === 'string' ? c : JSON.stringify(c)) + '</div>'; }).join('') + '</div></div>' : '') +
  '</div>';

  // 元数据
  var meta = data.metadata || {};
  var st = data.structure || {};
  if (st.total_chapters || st.total_chars) {
    html += '<div class="deconstruct-meta">' +
      (st.total_chapters ? '共 ' + st.total_chapters + ' 章 · ' : '') +
      (st.total_chars ? fmtNumber(st.total_chars) + ' 字' : '') +
    '</div>';
  }

  html += '</div>';
  return html;
}

function renderTagRow(label, value) {
  if (!value) return '';
  if (Array.isArray(value)) value = value.join('、');
  if (typeof value === 'object') value = JSON.stringify(value);
  return '<div class="deconstruct-tag-row">' +
    '<span class="deconstruct-tag-label">' + escapeHtml(label) + '</span>' +
    '<span class="deconstruct-tag-value">' + escapeHtml(String(value)) + '</span>' +
  '</div>';
}

async function openDeconstructModal(bookTitle, filePath) {
  var modal = $('#deconstruct-modal');
  var body = $('#deconstruct-modal-body');
  var title = $('#deconstruct-modal-title');
  if (!modal || !body) return;
  if (title) title.textContent = '小说解构' + (bookTitle ? ' - ' + bookTitle : '');
  body.innerHTML = '<div class="deconstruct-loading"><div class="spinner"></div><p>正在解构，请稍候 (大文件可能需要 30-60 秒)...</p></div>';
  modal.classList.add('open');

  var data = await runDeconstruction('', filePath, null);
  if (data) {
    body.innerHTML = renderDeconstructionResult(data);
  } else {
    body.innerHTML = '<div class="text-muted" style="padding:16px;">解构失败，请确认文件存在且后端正常</div>';
  }
}

function closeDeconstructModal() {
  var modal = $('#deconstruct-modal');
  if (modal) modal.classList.remove('open');
}

async function initDeconstructionTab() {
  // 在拆书页面初始化解构标签页
  var container = $('#deconstruct-tab-content');
  if (!container) return;
  var genre = (currentProject && currentProject.genre) || '末世';
  await loadDeconstructableBooks(genre);
  if (deconstructableBooks.length === 0) {
    container.innerHTML = '<div class="empty-state">暂无可解构的小说文件<br><span class="text-muted">请将 .txt 小说放入 data/raw/novels/' + escapeHtml(genre) + '/ 目录</span></div>';
    return;
  }
  container.innerHTML = '<div class="deconstruct-book-list">' +
    deconstructableBooks.map(function(b) {
      return '<div class="deconstruct-book-card" onclick="openDeconstructModal(\'' + escapeHtml(b.title) + '\', \'' + escapeHtml(b.file_path) + '\')">' +
        '<div class="deconstruct-book-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></div>' +
        '<div class="deconstruct-book-info">' +
          '<div class="deconstruct-book-title">' + escapeHtml(b.title) + '</div>' +
          '<div class="deconstruct-book-meta">' + fmtSize(b.size_kb) + ' · ' + escapeHtml(b.genre) + '</div>' +
        '</div>' +
        '<button class="btn btn-primary btn-sm">解构</button>' +
      '</div>';
    }).join('') +
  '</div>';
}
