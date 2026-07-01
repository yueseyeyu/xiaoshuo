"use strict";

let writingProjectChapters = [];

function updateWritingEmptyState() {
  const empty = $('#writing-empty-state');
  const toolbar = $('#writing-toolbar');
  const layout = $('#writing-layout');
  if (!currentProject || !currentProject.id) {
    if (empty) empty.style.display = 'flex';
    if (toolbar) toolbar.style.display = 'none';
    if (layout) layout.style.display = 'none';
  } else {
    if (empty) empty.style.display = 'none';
    if (toolbar) toolbar.style.display = '';
    if (layout) layout.style.display = '';
  }
}

async function loadWritingProjectData() {
  updateWritingEmptyState();
  if (!currentProject || !currentProject.id) return;
  try {
    const res = await ProjectAPI.getChapters(currentProject.id);
    writingProjectChapters = (res && res.chapters) || [];
    // 同步到 WRITING_CHAPTER_TITLES 供目录显示
    writingProjectChapters.forEach((ch) => {
      if (ch && ch.num && ch.title) {
        WRITING_CHAPTER_TITLES[ch.num] = ch.title;
      }
    });
  } catch (e) {
    console.error('loadWritingProjectData failed', e);
  }
}

async function loadWritingChapter(chapterNum) {
  if (!currentProject || !currentProject.id) {
    showToast('请先选择或创建一个项目');
    return;
  }
  // 先保存当前章节
  await saveWritingChapter();
  WRITING_CURRENT_CHAPTER = chapterNum;
  try {
    const chapter = await ProjectAPI.getChapter(currentProject.id, chapterNum);
    if (chapter) {
      $('#editor-title').value = chapter.title || getChapterTitle(chapterNum);
      $('#editor-textarea').value = chapter.content || '';
      if (chapter.title) WRITING_CHAPTER_TITLES[chapterNum] = chapter.title;
    } else {
      $('#editor-title').value = getChapterTitle(chapterNum);
      $('#editor-textarea').value = '';
    }
  } catch (e) {
    console.error('loadWritingChapter failed', e);
    $('#editor-title').value = getChapterTitle(chapterNum);
    $('#editor-textarea').value = '';
  }
  updateWordCount();
  markDraftSaved();
  renderWritingToc();
  renderOutlinePanel();
  updateWritingContext();
  renderSceneOutline();
}

function prevWritingChapter() {
  if (WRITING_CURRENT_CHAPTER > 1) {
    loadWritingChapter(WRITING_CURRENT_CHAPTER - 1);
  }
}

function nextWritingChapter() {
  var total = (currentProject && currentProject.totalChapters) || 300;
  if (WRITING_CURRENT_CHAPTER < total) {
    loadWritingChapter(WRITING_CURRENT_CHAPTER + 1);
  }
}

function updateWritingContext() {
  var bookEl = $('#context-book');
  var volEl = $('#context-vol');
  var chapEl = $('#context-chap');
  var breadcrumbVol = $('#editor-breadcrumb-vol');
  var breadcrumbChap = $('#editor-breadcrumb-chap');
  var tocCount = $('.toc-count');
  
  var title = (currentProject && currentProject.title) || '未命名作品';
  var totalChapters = (currentProject && currentProject.totalChapters) || 0;
  var volSize = 60;
  var volIndex = Math.floor((WRITING_CURRENT_CHAPTER - 1) / volSize);
  var volTitle = '第' + (volIndex + 1) + '卷';
  
  // 尝试从骨架数据获取卷标题
  if (typeof DESIGN_DATA !== 'undefined' && DESIGN_DATA.volumes && DESIGN_DATA.volumes[volIndex]) {
    volTitle = DESIGN_DATA.volumes[volIndex].title + '·' + (DESIGN_DATA.volumes[volIndex].subtitle || '');
  }
  
  if (bookEl) bookEl.textContent = title;
  if (volEl) volEl.textContent = volTitle;
  if (chapEl) chapEl.textContent = '第' + WRITING_CURRENT_CHAPTER + ' 章 / 第' + totalChapters + ' 章';
  if (breadcrumbVol) breadcrumbVol.textContent = '第' + (volIndex + 1) + '卷';
  if (breadcrumbChap) breadcrumbChap.textContent = '第' + WRITING_CURRENT_CHAPTER + ' 章';
  if (tocCount) tocCount.textContent = totalChapters + ' 章';
}

async function renderSceneOutline() {
  var panel = $('#scene-outline-panel');
  if (!panel) return;
  var body = panel.querySelector('.panel-body');
  if (!body) return;
  if (!currentProject || !currentProject.id) {
    body.innerHTML = '<div style="padding:12px;color:var(--text-secondary);font-size:13px;">请先选择项目</div>';
    return;
  }
  try {
    var skeleton = await ProjectAPI.getSkeleton(currentProject.id);
    var chapters = (skeleton && skeleton.chapters) || [];
    // 尝试找到当前章节对应的细纲
    var currentCh = WRITING_CURRENT_CHAPTER;
    var matchedCh = null;
    // chapters 可能是按段分组的，尝试匹配
    for (var i = 0; i < chapters.length; i++) {
      var ch = chapters[i];
      // 如果有 ch_num 字段直接匹配
      if (ch.num === currentCh || ch.chapter_num === currentCh) {
        matchedCh = ch;
        break;
      }
      // 如果标题包含章号
      if (ch.title && ch.title.indexOf(String(currentCh)) >= 0) {
        matchedCh = ch;
        break;
      }
    }
    // 如果没找到精确匹配，尝试用段索引
    if (!matchedCh && chapters.length > 0) {
      var segIndex = Math.floor((currentCh - 1) / 10);
      if (segIndex < chapters.length) {
        matchedCh = chapters[segIndex];
      }
    }
    
    if (matchedCh) {
      body.innerHTML = 
        '<div class="scene-outline-item"><b>目标</b><p>' + escapeHtml(matchedCh.goal || '暂无') + '</p></div>' +
        '<div class="scene-outline-item"><b>冲突</b><p>' + escapeHtml(matchedCh.conflict || '暂无') + '</p></div>' +
        '<div class="scene-outline-item"><b>结果</b><p>' + escapeHtml(matchedCh.result || '暂无') + '</p></div>' +
        (matchedCh.scenes && matchedCh.scenes.length > 0 ?
          '<div class="scene-outline-item"><b>场景</b><ul style="margin-top:4px;">' +
          matchedCh.scenes.map(function(s) { return '<li>' + escapeHtml(s) + '</li>'; }).join('') + '</ul></div>' : '');
    } else {
      body.innerHTML = '<div style="padding:12px;color:var(--text-secondary);font-size:13px;">当前章节暂无细纲，请先在设计页填写章节细纲</div>';
    }
  } catch (e) {
    body.innerHTML = '<div style="padding:12px;color:var(--text-secondary);font-size:13px;">细纲加载失败</div>';
  }
}

async function saveWritingChapter() {
  if (!currentProject || !currentProject.id) return false;
  const title = $('#editor-title').value || getChapterTitle(WRITING_CURRENT_CHAPTER);
  const content = $('#editor-textarea').value || '';
  const wordCount = content.replace(/\s/g, '').length;
  try {
    await ProjectAPI.updateChapter(currentProject.id, WRITING_CURRENT_CHAPTER, {
      title: title,
      content: content,
      word_count: wordCount,
      status: wordCount > 0 ? 'writing' : 'planned',
      updated_at: new Date().toISOString(),
    });
    WRITING_CHAPTER_TITLES[WRITING_CURRENT_CHAPTER] = title;
    // v8.6: 追踪今日写作量
    var todayKey = 'writing_today_' + new Date().toDateString();
    var prevCount = parseInt(localStorage.getItem(todayKey) || '0', 10);
    // 只增加差值（避免重复计数）
    var lastSavedKey = 'writing_last_saved_' + currentProject.id + '_' + WRITING_CURRENT_CHAPTER;
    var lastSaved = parseInt(localStorage.getItem(lastSavedKey) || '0', 10);
    var diff = wordCount - lastSaved;
    if (diff > 0) {
      localStorage.setItem(todayKey, String(prevCount + diff));
    }
    localStorage.setItem(lastSavedKey, String(wordCount));
    return true;
  } catch (e) {
    console.error('saveWritingChapter failed', e);
    return false;
  }
}

async function loadInstructions(bookName, chapter) {
  const path = '/api/instructions?book=' + encodeURIComponent(bookName) + '&ch=' + (chapter || 1);
  const { ok, data } = await apiGet(path);
  if (ok) {
    if (typeof appState !== 'undefined' && appState.apiData) appState.apiData.instructions = data;
    return data;
  }
  console.log('[API] Instructions not available');
  return null;
}
function updateSelectionCount() {
  const el = $('#editor-textarea');
  const label = $('#editor-selection-count');
  if (!el || !label) return;
  const start = el.selectionStart || 0;
  const end = el.selectionEnd || 0;
  if (start === end) {
    label.textContent = '选中 0 字';
    return;
  }
  const selected = (el.value || '').slice(start, end);
  const count = selected.replace(/\s/g, '').length;
  label.textContent = '选中 ' + count + ' 字';
}
function updateWordCount() {
  const text = $('#editor-textarea').value || '';
  const count = text.replace(/\s/g, '').length;
  const target = 2000;
  const pct = Math.min(100, Math.round((count / target) * 100));
  $('#editor-word-count').textContent = count + ' / ' + target + ' 字';
  const progressText = $('#chapter-progress-text');
  const progressBar = $('#chapter-progress-bar');
  if (progressText) progressText.textContent = '本章 ' + count + ' / ' + target + ' 字 · ' + pct + '%';
  if (progressBar) progressBar.style.width = pct + '%';
  const paraCount = $('#editor-para-count');
  if (paraCount) {
    const paras = text.split(/\n\s*\n/).filter(Boolean);
    const currentPara = paras[paras.length - 1] || '';
    paraCount.textContent = '本段 ' + currentPara.replace(/\s/g, '').length + ' 字';
  }
  const eta = $('#editor-eta');
  if (eta) {
    const remain = Math.max(0, target - count);
    const minutes = Math.ceil(remain / 30);
    eta.textContent = '预计 ' + (minutes >= 60 ? Math.floor(minutes / 60) + 'h ' + (minutes % 60) + 'm' : minutes + 'm');
  }
const today = $('#editor-today-count');
if (today) {
  // v8.6: 动态计算今日字数（从 localStorage 读取今日写作量）
  var todayKey = 'writing_today_' + new Date().toDateString();
  var todayCount = parseInt(localStorage.getItem(todayKey) || '0', 10);
  today.textContent = '今日 ' + todayCount.toLocaleString() + ' 字';
}
markDraftUnsaved();
}
function switchSidebarTab(tab) {
  const sidebar = $('#writing-sidebar');
  if (!sidebar) return;
  sidebar.querySelectorAll('.sidebar-tab').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  sidebar.querySelectorAll('.sidebar-tab-content').forEach((content) => {
    content.classList.toggle('active', content.dataset.tab === tab);
  });
}
function toggleTocVolume(titleEl) {
  const volume = titleEl.closest('.toc-volume');
  if (!volume) return;
  volume.classList.toggle('collapsed');
  const chevron = titleEl.querySelector('.toc-chevron');
  if (chevron) chevron.textContent = volume.classList.contains('collapsed') ? '▸' : '▾';
}
async function jumpToChapter(chapter) {
  await loadWritingChapter(chapter);
}
function toggleFocus() {
  const isFocus = document.body.classList.toggle('focus-mode');
  const btn = $('#focus-toggle');
  if (btn) btn.textContent = isFocus ? '退出专注' : '专注模式';
  if (isFocus) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    closeFocusAiPanel();
    if (document.fullscreenElement) document.exitFullscreen();
  }
}
async function toggleDeAi() {
  deAiEnabled = !deAiEnabled;
  updateDeaiHintVisibility();
  if (deAiEnabled) {
    const text = $('#editor-textarea').value || '';
    if (!text.trim()) { showToast('AI指纹检测已开启 - 编辑器无内容'); return; }
    showToast('AI指纹检测中...');
    try {
      const resp = await fetch(API_BASE + '/api/compliance/scan?text=' + encodeURIComponent(text));
      const data = await resp.json();
      if (data.ok) {
        const aiRate = (data.ai_rate || 0).toFixed(1);
        const level = data.risk_level || 'unknown';
        const hits = data.total_count || 0;
        const highRisk = data.high_risk_count || 0;
        let msg = 'AI指纹检测 - AI率 ' + aiRate + '% (' + level + ')';
        if (highRisk > 0) msg += ' · 高风险词 ' + highRisk + ' 个';
        else if (hits > 0) msg += ' · 指纹词 ' + hits + ' 个';
        else msg += ' · 未检测到明显AI痕迹';
        if (data.ai_rate_recommendation) msg += '\n' + data.ai_rate_recommendation;
        showToast(msg, 5000);
      } else {
        showToast('AI指纹检测失败: ' + (data.error || '未知错误'));
      }
    } catch (e) {
      showToast('AI指纹检测请求失败: ' + e.message);
    }
  } else {
    showToast('AI指纹检测已关闭');
  }
}
function toggleInstructionsPanel() {
  const panel = $('#instructions-panel');
  if (panel) panel.classList.toggle('collapsed');
}
function toggleWritingSidebar() {
  const layout = $('#writing-layout');
  const btn = $('#writing-sidebar-toggle');
  if (!layout || !btn) return;
  const collapsed = layout.classList.toggle('sidebar-collapsed');
  btn.setAttribute('aria-expanded', String(!collapsed));
  btn.setAttribute('aria-label', collapsed ? '展开参考面板' : '收起参考面板');
}
function toggleWritingMore(btn) {
  const dd = btn.closest('.writing-more-dropdown');
  if (dd) dd.classList.toggle('open');
}
function closeWritingMore() {
  const dd = $('.writing-more-dropdown.open');
  if (dd) dd.classList.remove('open');
}
function toggleAiCompare() {
  if (document.body.classList.contains('focus-mode')) {
    $('#focus-ai-panel').classList.toggle('open');
  } else {
    const panel = $('#ai-compare-panel');
    if (panel) panel.classList.toggle('collapsed');
  }
}
function closeFocusAiPanel() {
  const panel = $('#focus-ai-panel');
  if (panel) panel.classList.remove('open');
}
function togglePanel(id) {
  const panel = $('#' + id + '-panel');
  if (panel) panel.classList.toggle('collapsed');
}
async function initInstructionsPanel() {
  if (instructionsLoaded) return;
  const panel = $('#instructions-panel');
  if (!panel) return;
  panel.style.display = '';

  // 填充可选参考书列表
  const { ok, data } = await apiGet('/api/instructions');
  const select = $('#instr-book-select');
  if (ok && data && data.books && data.books.length) {
    select.innerHTML = '<option value="">选择参考书</option>' +
      data.books.map(b => '<option value="' + escapeHtml(b.name || '') + '">' + escapeHtml(b.name || '') + '</option>').join('');
    instructionsLoaded = true;
  } else if (select) {
    select.innerHTML = '<option value="">暂无参考书指令</option>';
  }
  if (!ok) {
    $('#instr-loading').textContent = 'API 不可用，请启动服务器';
  }
}
async function loadInstructionsForBook() {
  const book = $('#instr-book-select').value;
  const chapter = parseInt($('#instr-chapter-input').value) || 1;
  const loading = $('#instr-loading');
  const list = $('#instr-list');
  const bookName = $('#instr-book-name');

  if (!book) {
    loading.style.display = '';
    list.style.display = 'none';
    loading.textContent = '请先选择参考书';
    return;
  }

  loading.style.display = '';
  list.style.display = 'none';
  loading.textContent = '正在加载第 ' + chapter + ' 章指令...';
  bookName.textContent = '';

  const result = await loadInstructions(book, chapter);
  if (!result || !result.instructions) {
    loading.textContent = '加载失败或未找到指令';
    return;
  }

  const instr = result.instructions;
  bookName.textContent = '| ' + book + ' 第' + chapter + '章';

  const items = instr.items || [];
  if (items.length === 0) {
    loading.style.display = 'none';
    list.style.display = '';
    list.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;padding:8px 0;">本章无指令建议</div>';
    return;
  }

  loading.style.display = 'none';
  list.style.display = '';

  const levelLabels = { critical: '[!!] 严重', warning: '[!] 建议', info: '[~] 提示', minor: '[-] 参考' };
  const levelColors = { critical: 'var(--danger)', warning: 'var(--warning)', info: 'var(--primary)', minor: 'var(--text-secondary)' };

  list.innerHTML = items.map(item => {
    const color = levelColors[item.level] || 'var(--text-secondary)';
    const label = levelLabels[item.level] || escapeHtml(item.level || '');
    return '<div class="ch-instr-item" style="margin-bottom:10px;padding:8px;background:var(--surface);border-radius:6px;border-left:3px solid ' + escapeHtml(color) + ';">' +
      '<div style="font-size:11px;color:' + escapeHtml(color) + ';margin-bottom:4px;font-weight:600;">' + escapeHtml(label) + '</div>' +
      '<div style="font-size:13px;line-height:1.5;">' + escapeHtml(item.text || '') + '</div>' +
      '</div>';
  }).join('');
}
async function saveDraft() {
  const title = $('#editor-title').value || '';
  const content = $('#editor-textarea').value || '';
  try {
    localStorage.setItem('draft_title', title);
    localStorage.setItem('draft_content', content);
    localStorage.setItem('draft_saved_at', new Date().toISOString());
  } catch (e) {}
  if (currentProject && currentProject.id) {
    const ok = await saveWritingChapter();
    if (ok) {
      markDraftSaved();
      showToast('已保存到项目');
      return;
    }
  }
  markDraftSaved();
  showToast('草稿已保存');
}
function restoreDraft() {
  try {
    const title = localStorage.getItem('draft_title');
    const content = localStorage.getItem('draft_content');
    if (title !== null) $('#editor-title').value = title;
    if (content !== null) $('#editor-textarea').value = content;
    updateWordCount();
    markDraftSaved();
  } catch (e) {}
}
async function searchScene() {
  const input = $('#scene-search-input');
  const status = $('#scene-search-status');
  const results = $('#scene-search-results');
  const query = input.value.trim();
  if (!query) return;

  status.textContent = '搜索中...';
  results.innerHTML = '';

  try {
    const params = new URLSearchParams({ q: query, genre: '末世', top: 5 });
    const { ok, data, error } = await apiFetch('/api/search?' + params);
    if (!ok) {
      status.textContent = '搜索失败: ' + error;
      return;
    }

    if (!data.results || data.results.length === 0) {
      status.textContent = '无结果，换个关键词试试';
      return;
    }

    status.textContent = data.total_scenes + ' 个场景中匹配 ' + data.results.length + ' 个';
    results.innerHTML = data.results.map(function(r, i) {
      return '<div class="scene-card">' +
        '<div class="scene-card-header">' +
          '<span class="scene-similarity">' + (r.similarity * 100).toFixed(0) + '%</span>' +
          '<span class="scene-book">' + escapeHtml(r.book_name || '') + '</span>' +
          '<span class="scene-chapter">第' + (r.chapter || 0) + '章</span>' +
        '</div>' +
        '<div class="scene-tags">' +
          '<span class="scene-tag tag-emotion">' + escapeHtml(r.emotion || '') + '</span>' +
          '<span class="scene-tag tag-pace">' + escapeHtml(r.pace || '') + '</span>' +
          '<span class="scene-tag tag-conflict">冲突:' + escapeHtml(String(r.conflict_level || '')) + '</span>' +
          (r.pleasure_type ? '<span class="scene-tag tag-pleasure">' + escapeHtml(r.pleasure_type) + '</span>' : '') +
        '</div>' +
        '<div class="scene-technique">' + escapeHtml(r.technique_summary || '') + '</div>' +
        '<details class="scene-preview">' +
          '<summary>原文预览</summary>' +
          '<p>' + escapeHtml(r.text_preview || '') + '</p>' +
        '</details>' +
      '</div>';
    }).join('');
  } catch (e) {
    status.textContent = '连接失败，请确认后端已启动(python -m xiaoshuo.api.server --port 8089)';
    console.error(e);
  }
}
async function importDisassemblyToWriting() {
  if (selectedBookIndex == null) {
    showToast('请先在书库中选择一本书');
    return;
  }
  const b = DATA.books[selectedBookIndex];
  showLoading();
  try {
    const genre = b.genre || '末世';
    const name = b.title || b.file.replace('rhythm_', '').replace('.csv', '');
    const { ok, data } = await apiGet('/api/disassembly/book?name=' + encodeURIComponent(name) + '&genre=' + encodeURIComponent(genre));
    hideLoading();
    if (ok && data && data.chapters && data.chapters.length > 0) {
      // 从真实拆书数据中提炼节奏洞察
      const chapters = data.chapters;
      const fastCount = chapters.filter(c => (c.pace || c.rhythm) === 'fast').length;
      const slowCount = chapters.filter(c => (c.pace || c.rhythm) === 'slow').length;
      const totalWords = chapters.reduce((s, c) => s + (parseInt(c.wc) || 0), 0);
      let insight = '共 ' + data.total + ' 章，约 ' + fmtNumber(totalWords) + ' 字。';
      if (fastCount > chapters.length * 0.4) insight += '节奏偏快，建议在紧张情节参考。';
      else if (slowCount > chapters.length * 0.4) insight += '节奏偏慢，适合铺垫和过渡参考。';
      else insight += '节奏均衡，整体可参考。';
      importedReportData = {
        title: '拆书分析 - ' + b.title,
        insight: insight,
        detail: '来自书库《' + b.title + '》的拆书数据',
        importedAt: new Date().toLocaleString()
      };
      renderImportedReport();
      navigate('writing');
      showToast('已导入拆书数据到写作辅助');
    } else {
      showToast('该书籍暂无拆书数据，请先执行拆书分析');
    }
  } catch (e) {
    hideLoading();
    showToast('导入拆书数据失败: ' + e.message);
  }
}
function renderImportedReport() {
  const el = document.getElementById('imported-report-panel');
  if (!el) return;
  if (!importedReportData) {
    el.style.display = 'none';
    return;
  }
  el.style.display = '';
  document.getElementById('imported-report-title').textContent = importedReportData.title;
  document.getElementById('imported-report-insight').textContent = importedReportData.insight;
  document.getElementById('imported-report-time').textContent = importedReportData.importedAt;
}
function renderWritingToc() {
  const recentContainer = $('#toc-recent');
  const volumesContainer = $('#toc-volumes');
  if (!recentContainer || !volumesContainer) return;

  // v8.5: 从项目真实章节数据构建目录
  const totalChapters = (currentProject && currentProject.totalChapters) || 0;
  const recent = [WRITING_CURRENT_CHAPTER, WRITING_CURRENT_CHAPTER - 1, WRITING_CURRENT_CHAPTER - 7].filter(function(c) { return c > 0; });
  recentContainer.innerHTML = '<div class="toc-recent-title">最近修改</div>' +
    recent.map(function(c) { return '<div class="toc-recent-item" onclick="jumpToChapter(' + c + ')">' + c + ' ' + escapeHtml(getChapterTitle(c)) + '</div>'; }).join('');

  if (!currentProject || !totalChapters) {
    volumesContainer.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px;">请先创建项目并设置总章节数</div>';
    return;
  }

  // 按卷组织：每60章一卷
  const volSize = 60;
  const numVols = Math.ceil(totalChapters / volSize);
  const currentVol = Math.floor((WRITING_CURRENT_CHAPTER - 1) / volSize);
  let html = '';
  for (let idx = 0; idx < numVols; idx++) {
    const start = idx * volSize + 1;
    const end = Math.min((idx + 1) * volSize, totalChapters);
    const isCurrent = idx === currentVol;
    const chapters = [];
    for (let c = start; c <= end; c++) {
      const isCurCh = c === WRITING_CURRENT_CHAPTER;
      chapters.push('<div class="toc-chapter' + (isCurCh ? ' current' : '') + '" onclick="jumpToChapter(' + c + ')">' + c + ' ' + escapeHtml(getChapterTitle(c)) + '</div>');
    }
    html += '<div class="toc-volume ' + (isCurrent ? 'active' : 'collapsed') + '">' +
      '<div class="toc-volume-title" onclick="toggleTocVolume(this)"><span class="toc-chevron">' + (isCurrent ? '▾' : '▸') + '</span>第' + (idx + 1) + '卷 (' + start + '-' + end + '章)</div>' +
      '<div class="toc-chapters">' + chapters.join('') + '</div>' +
      '</div>';
  }
  volumesContainer.innerHTML = html;
  setTimeout(function() { initWritingTocScroll(); }, 0);
}

async function renderOutlinePanel() {
  const body = document.getElementById('outline-panel-body');
  if (!body) return;
  if (!currentProject || !currentProject.id) {
    body.innerHTML = '<div style="padding:16px;color:var(--text-muted);font-size:13px;">请先选择项目</div>';
    return;
  }
  // v8.5: 从后端加载真实项目大纲数据
  try {
    const [skeleton, characters] = await Promise.all([
      ProjectAPI.getSkeleton(currentProject.id),
      ProjectAPI.getCharacters(currentProject.id)
    ]);
    const currentChapter = WRITING_CURRENT_CHAPTER;
    const totalChapters = (currentProject && currentProject.totalChapters) || 0;
    const volSize = 60;
    const volIndex = Math.floor((currentChapter - 1) / volSize);
    const segmentStart = Math.floor((currentChapter - 1) / 10) * 10 + 1;
    const segmentEnd = Math.min(segmentStart + 9, totalChapters || 300);
    // 骨架数据
    const volumes = (skeleton && skeleton.volumes) || [];
    const vol = volumes[volIndex];
    const chars = (characters && characters.characters) || [];
    const charNames = chars.slice(0, 3).map(function(c) { return c.name; }).join(' / ') || '暂无角色';
    const volText = vol ? (vol.title + '：' + (vol.subtitle || vol.summary || '')) : '第' + (volIndex + 1) + '卷';
    const segSummary = vol ? (vol.summary || '暂无段纲') : '暂无段纲';
    body.innerHTML = '<div class="outline-section"><b>当前卷</b><p>' + escapeHtml(volText) + '</p></div>' +
      '<div class="outline-section"><b>当前段</b><p>第 ' + segmentStart + '-' + segmentEnd + ' 章：' + escapeHtml(segSummary) + '</p></div>' +
      '<div class="outline-section"><b>角色</b><div>' + escapeHtml(charNames) + '</div></div>' +
      '<div class="outline-section"><b>场景目标</b><p>请在设计页填写章节场景</p></div>';
  } catch (e) {
    body.innerHTML = '<div class="outline-section"><b>当前卷</b><p>数据加载失败</p></div>';
  }
}
