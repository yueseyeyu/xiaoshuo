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
  if (today) today.textContent = '今日 1,240 字';
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
function toggleDeAi() {
  deAiEnabled = !deAiEnabled;
  updateDeaiHintVisibility();
  if (deAiEnabled) {
    const text = $('#editor-textarea').value || '';
    const aiPatterns = [/首先.*其次.*最后/, /不得不说/, /众所周知/, /总而言之/, /综上所述/];
    const found = aiPatterns.filter(p => p.test(text));
    const msg = found.length > 0 ? 'AI指纹检测已开启 - 检测到 ' + found.length + ' 处疑似AI痕迹' : 'AI指纹检测已开启 - 未检测到明显AI痕迹';
    showToast(msg);
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
function importDisassemblyToWriting() {
  if (selectedBookIndex == null) {
    showToast('请先在书库中选择一本书');
    return;
  }
  const b = DATA.books[selectedBookIndex];
  showLoading();
  setTimeout(() => {
    hideLoading();
    importedReportData = {
      title: '拆书分析 - ' + b.title,
      insight: '节奏分析：开篇紧凑，中段平稳，高潮密集。建议第127章参考此节奏模式。',
      detail: '来自书库 ' + b.title + ' 的拆书数据',
      importedAt: new Date().toLocaleString()
    };
    renderImportedReport();
    navigate('writing');
    showToast('已导入拆书数据到写作辅助');
  }, 600);
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

  const recent = [WRITING_CURRENT_CHAPTER, WRITING_CURRENT_CHAPTER - 1, WRITING_CURRENT_CHAPTER - 7].filter(function(c) { return c > 0; });
  recentContainer.innerHTML = '<div class="toc-recent-title">最近修改</div>' +
    recent.map(function(c) { return '<div class="toc-recent-item" onclick="jumpToChapter(' + c + ')">' + c + ' ' + escapeHtml(getChapterTitle(c)) + '</div>'; }).join('');

  const volSize = 60;
  const currentVol = Math.min(DESIGN_DATA.volumes.length - 1, Math.floor((WRITING_CURRENT_CHAPTER - 1) / volSize));
  volumesContainer.innerHTML = DESIGN_DATA.volumes.map(function(vol, idx) {
    const start = idx * volSize + 1;
    const end = Math.min((idx + 1) * volSize, 300);
    const isCurrent = idx === currentVol;
    const chapters = [];
    for (let c = start; c <= end; c++) {
      const isCurCh = c === WRITING_CURRENT_CHAPTER;
      chapters.push('<div class="toc-chapter' + (isCurCh ? ' current' : '') + '" onclick="jumpToChapter(' + c + ')">' + c + ' ' + escapeHtml(getChapterTitle(c)) + '</div>');
    }
    return '<div class="toc-volume ' + (isCurrent ? 'active' : 'collapsed') + '">' +
      '<div class="toc-volume-title" onclick="toggleTocVolume(this)"><span class="toc-chevron">' + (isCurrent ? '▾' : '▸') + '</span>' + escapeHtml(vol.title) + ' ' + escapeHtml(vol.subtitle) + '</div>' +
      '<div class="toc-chapters">' + chapters.join('') + '</div>' +
      '</div>';
  }).join('');

  setTimeout(function() { initWritingTocScroll(); }, 0);
}
function renderOutlinePanel() {
  const body = document.getElementById('outline-panel-body');
  if (!body) return;
  const currentChapter = WRITING_CURRENT_CHAPTER;
  const volIndex = Math.min(DESIGN_DATA.volumes.length - 1, Math.floor((currentChapter - 1) / 60));
  const vol = DESIGN_DATA.volumes[volIndex];
  const segmentStart = Math.floor((currentChapter - 1) / 10) * 10 + 1;
  const segmentEnd = Math.min(segmentStart + 9, 300);
  const segmentTitle = '第 ' + segmentStart + '-' + segmentEnd + ' 章';
  const chars = DESIGN_DATA.characters.slice(0, 3).map(function(c) { return c.name; }).join(' / ') || '暂无角色';
  const scene = DESIGN_DATA.chapters[0];
  body.innerHTML = '<div class="outline-section"><b>当前卷</b><p>' + escapeHtml(vol ? (vol.title + '：' + vol.subtitle) : '暂无卷纲') + '</p></div>' +
    '<div class="outline-section"><b>当前段</b><p>' + escapeHtml(segmentTitle + '：' + (vol ? vol.summary : '暂无段纲')) + '</p></div>' +
    '<div class="outline-section"><b>角色</b><div>' + escapeHtml(chars) + '</div></div>' +
    '<div class="outline-section"><b>场景目标</b><p>' + escapeHtml(scene ? scene.goal : '暂无场景目标') + '</p></div>';
}
