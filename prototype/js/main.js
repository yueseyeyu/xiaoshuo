"use strict";

// ============================================================
// 错误边界 — v8.1
// ============================================================
function safeRender(fn, name) {
  try {
    fn();
  } catch (e) {
    console.error('[ErrorBoundary] ' + name + ': ' + e.message, e);
    const el = document.getElementById(name) || document.getElementById('section-' + name);
    if (el) {
      el.innerHTML = '<div class="error-boundary"><p>[FAIL] ' + name + ' 渲染失败</p><p class="text-muted">' + e.message + '</p></div>';
    }
  }
}

// ============================================================
// 应用生命周期与导航
// ============================================================
async function loadAppVersion() {
  const badge = $('#version-badge');
  const title = document.querySelector('title');
  const { ok, data } = await apiGet('/api/config');
  if (ok && data && data.version) {
    if (badge) badge.textContent = 'v' + data.version;
    if (title) title.textContent = '番茄小说 AI 辅助创作系统 v' + data.version;
    // v8.1: 动态更新 CSS 版本号
    const cssLink = document.querySelector('link[href*="styles.css"]');
    if (cssLink) {
      cssLink.href = cssLink.href.replace(/v=\d+/, 'v=' + data.version);
    }
  } else if (badge) {
    badge.textContent = 'v?';
  }
}

async function init() {
  try {
    await loadAppVersion();
    await loadLibraryData();
    loadTasks();
    // 固定默认暗色主题，不再读取 localStorage 中的旧主题
    setTheme('midnight');
    loadAccentPresets();
    await loadProject();
    updateTopbarProjectName();
    loadApiData();  // 异步加载 API 数据，不阻塞渲染
    safeRender(renderGenreTabs, 'genre-tabs');
    safeRender(renderLibrary, 'library');
    safeRender(renderTaskBookChecklist, 'task-checklist');
    safeRender(renderTasks, 'tasks');
    safeRender(renderPipelineStates, 'pipeline');
    updateWordCount();
    $('#editor-textarea').addEventListener('input', () => {
      updateWordCount();
      updateSelectionCount();
      updateSaveStatus('saving');
      scheduleSaveStatusSaved();
      try {
        localStorage.setItem('draft_content', $('#editor-textarea').value || '');
        localStorage.setItem('draft_title', $('#editor-title').value || '');
      } catch (e) {}
    });
    $('#editor-textarea').addEventListener('mouseup', updateSelectionCount);
    $('#editor-textarea').addEventListener('keyup', updateSelectionCount);
    $('#editor-textarea').addEventListener('select', updateSelectionCount);
    $('#editor-title').addEventListener('input', () => {
      updateWordCount();
      updateSaveStatus('saving');
      scheduleSaveStatusSaved();
      try {
        localStorage.setItem('draft_title', $('#editor-title').value || '');
      } catch (e) {}
    });
    safeRender(initHardwareMonitor, 'hardware');
    initDesignEditButtons();
    initTaskTypeHandler();
    restoreSettings();
    await populateProjectSwitcher();
    restoreDraft();
    restoreRoute();
    window.addEventListener('hashchange', restoreRoute);
    $$('.theme-dot').forEach((d) => {
      d.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setTheme(d.dataset.theme);
      }
    });
  });
  setTimeout(checkModelStatus, 500);
  registerInterval(setInterval(checkModelStatus, 10000));  // 每 10 秒轮询，提升状态更新实时性
  } catch (e) {
    console.error('[FATAL] init failed: ' + e.message, e);
    const app = document.getElementById('app');
    if (app) {
      app.innerHTML = '<div class="error-boundary fatal"><h2>应用初始化失败</h2><p>' + e.message + '</p><button onclick="location.reload()">重新加载</button></div>';
    }
  }
}

function updateTopbarProjectName() {
  const el = $('#topbar-project-name');
  if (!el) return;
  el.textContent = (currentProject && currentProject.title) ? currentProject.title : '';
}

async function checkModelStatus() {
  const pill = $('#model-status-pill');
  const dot = $('#model-status-dot');
  const text = $('#model-status-text');
  const btn = $('#model-toggle-btn');
  if (!pill || !text) return;
  const settingsBadge = $('#nav-badge-settings');
  function setStatus(cls, label, running, badgeClass) {
    pill.classList.remove('status-online', 'status-offline', 'status-error');
    pill.classList.add(cls);
    text.textContent = label;
    if (settingsBadge) {
      settingsBadge.className = 'nav-badge';
      if (badgeClass) settingsBadge.classList.add(badgeClass);
    }
    if (btn) {
      btn.classList.toggle('running', running);
      btn.title = running ? '停止模型' : '启动模型';
    }
  }
  // v8.2: 使用新的 /api/model/status 端点
  const { ok, data } = await apiGet('/api/model/status');
  if (!ok || !data || data.error) {
    setStatus('status-offline', '模型状态未知', false, 'warn');
    return;
  }
  // 检查主模型是否在线
  const mainModel = data.models && data.models.main_model;
  if (mainModel && (mainModel.running || mainModel.healthy)) {
    setStatus('status-online', mainModel.name || '模型运行中', true);
  } else {
    setStatus('status-offline', '模型未运行', false, 'warn');
  }
}

async function toggleModel() {
  const btn = $('#model-toggle-btn');
  const text = $('#model-status-text');
  if (!btn || !text) return;
  const isRunning = btn.classList.contains('running');
  btn.disabled = true;
  try {
    if (isRunning) {
      text.textContent = '正在停止...';
      await apiPost('/api/model/stop', {});
    } else {
      text.textContent = '正在启动...';
      await apiPost('/api/model/start', {});
    }
  } catch (e) {
    console.error('[ModelToggle] failed:', e);
    showToast('模型操作失败: ' + e.message);
  } finally {
    btn.disabled = false;
    // 等 8 秒后刷新状态（模型加载通常需要 15-30 秒，避免过早显示"未启动"）
    setTimeout(checkModelStatus, 8000);
  }
}

function restoreRoute() {
  const page = (window.location.hash || '').replace('#', '') || 'dashboard';
  const valid = ['dashboard','library','disassembly','writing','design','reports','tasks','hardware','settings','logs'];
  if (valid.includes(page)) {
    navigate(page);
  } else {
    navigate('dashboard');
    showToast('页面不存在，已返回工作台');
  }
}

function navigate(page) {
  closeDesignEdit();
  closeReportDetail();
  closeTaskModal();
  closeCreateProjectModal();
  closeDetail();
  closeFocusAiPanel();
  $$('.page').forEach((p) => p.classList.remove('active'));
  const target = $('#page-' + page);
  if (target) target.classList.add('active');
  $$('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.page === page));
  window.scrollTo({ top: 0, behavior: 'auto' });
  if (window.innerWidth <= 768) closeMobileSidebar();
  try {
    if (window.location.hash !== '#' + page) {
      window.history.replaceState(null, '', '#' + page);
    }
  } catch (e) {}
  if (page === 'dashboard') { updateActivityTimes(); }
  if (page === 'writing') { loadWritingProjectData(); loadWritingChapter(WRITING_CURRENT_CHAPTER); renderImportedReport(); initInstructionsPanel(); }
  if (page === 'disassembly') { loadDisassemblyData(); }
  if (page === 'settings') { loadSettingsConfig(); }
  if (page === 'logs') { initLogsPage(); }
  if (page === 'design') { loadDesignData(); }
  updateDeaiHintVisibility();
  reportOperation('navigate', { page: page });
}

function updateDeaiHintVisibility() {
  const hint = $('#deai-hint');
  if (!hint) return;
  const isWriting = $('#page-writing') && $('#page-writing').classList.contains('active');
  hint.classList.toggle('show', deAiEnabled && isWriting);
}

// ============================================================
// 主题与品牌色
// ============================================================
function setTheme(theme) {
  currentTheme = theme;
  document.body.setAttribute('data-theme', theme);
  $$('.theme-dot').forEach((d) => d.classList.toggle('active', d.dataset.theme === theme));
  const label = theme[0].toUpperCase() + theme.slice(1);
  const st = $('#settings-theme-name');
  const sd = $('#settings-theme-dot');
  if (st) st.textContent = label;
  if (sd) {
    const colors = { midnight: '#38BDF8', light: '#0ea5e9', obsidian: '#A1A1AA' };
    sd.style.background = colors[theme];
  }
  try { localStorage.setItem('theme', theme); } catch (e) {}
}

function cycleTheme() {
  const idx = THEME_ORDER.indexOf(currentTheme);
  const next = THEME_ORDER[(idx + 1) % THEME_ORDER.length];
  setTheme(next);
}

function applyAccent(preset) {
  if (!preset) return;
  currentAccentId = preset.id;
  document.body.setAttribute('data-accent', preset.id);
  // 颜色由 styles.css 中 [data-accent="..."] 映射控制，不强制覆盖内联变量
  $$('.preset-dot').forEach((d) => d.classList.toggle('active', d.dataset.preset === preset.id));
  const labelEl = $('#settings-preset-name');
  if (labelEl) labelEl.textContent = preset.name;
  const dot = $('#settings-theme-dot');
  if (dot) dot.style.background = preset.accent;
  try { localStorage.setItem('accent_id', preset.id); } catch (e) {}
}

function setAccentPreset(id) {
  const preset = (accentPresets.length ? accentPresets : ACCENT_PRESETS).find((p) => p.id === id);
  if (preset) applyAccent(preset);
}

function cycleAccentPreset() {
  const list = accentPresets.length ? accentPresets : ACCENT_PRESETS;
  const idx = list.findIndex((p) => p.id === currentAccentId);
  const next = list[(idx + 1 + list.length) % list.length];
  applyAccent(next);
  showToast('品牌色：' + next.name);
}

async function loadAccentPresets() {
  const { ok, data: cfg } = await apiGet('/api/config');
  if (ok && cfg && Array.isArray(cfg.theme_presets) && cfg.theme_presets.length) {
    accentPresets = cfg.theme_presets.map((p) => ({
      id: p.id,
      name: p.name,
      accent: p.accent,
      accentRgb: p.accent_rgb,
    }));
  }
  if (!accentPresets.length) accentPresets = ACCENT_PRESETS.slice();
  // 同步 settings 页的按钮
  const switcher = $('#preset-switcher');
  if (switcher) {
    switcher.innerHTML = '';
    accentPresets.forEach((p) => {
      const btn = document.createElement('button');
      btn.className = 'preset-dot';
      btn.dataset.preset = p.id;
      btn.setAttribute('aria-label', p.name);
      btn.style.background = p.accent;
      btn.onclick = () => setAccentPreset(p.id);
      switcher.appendChild(btn);
    });
  }
  // 恢复用户上次选择
  let saved = null;
  try { saved = localStorage.getItem('accent_id'); } catch (e) {}
  if (saved && accentPresets.find((p) => p.id === saved)) {
    applyAccent(accentPresets.find((p) => p.id === saved));
  } else {
    applyAccent(accentPresets[0]);
  }
}
