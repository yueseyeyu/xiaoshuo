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
  } else if (badge) {
    badge.textContent = 'v?';
  }
}

async function init() {
  await loadAppVersion();
  await loadLibraryData();
  loadTasks();
  // 固定默认暗色主题，不再读取 localStorage 中的旧主题
  setTheme('midnight');
  loadAccentPresets();
  loadProject();
  updateTopbarProjectName();
  loadApiData();  // 异步加载 API 数据，不阻塞渲染
  renderGenreTabs();
  renderLibrary();
  renderTaskBookChecklist();
  renderTasks();
  renderPipelineStates();
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
  initHardwareMonitor();
  initDesignEditButtons();
  initTaskTypeHandler();
  restoreSettings();
  populateProjectSwitcher();
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
  checkModelStatus();
  registerInterval(setInterval(checkModelStatus, 30000));
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
  if (!pill || !text) return;
  const settingsBadge = $('#nav-badge-settings');
  function setStatus(cls, label, badgeClass) {
    pill.classList.remove('status-online', 'status-offline', 'status-error');
    pill.classList.add(cls);
    text.textContent = label;
    if (settingsBadge) {
      settingsBadge.className = 'nav-badge';
      if (badgeClass) settingsBadge.classList.add(badgeClass);
    }
  }
  const { ok, data } = await apiGet('/api/model-info');
  if (!ok || !data) {
    setStatus('status-offline', '本地模型未启用', 'warn');
    return;
  }
  if (data.status === 'running') {
    setStatus('status-online', data.name);
  } else {
    setStatus('status-offline', data.name + ' · 未连接', 'warn');
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
  if (page === 'writing') { renderWritingToc(); renderOutlinePanel(); renderImportedReport(); initInstructionsPanel(); }
  if (page === 'disassembly') { loadDisassemblyData(); }
  if (page === 'settings') { loadSettingsConfig(); }
  if (page === 'logs') { initLogsPage(); }
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
const THEME_ORDER = ['midnight', 'light', 'obsidian'];
const ACCENT_PRESETS = [
  { id: 'serene',   name: '静谧蓝', accent: '#38BDF8', accentRgb: '56,189,248' },
  { id: 'arctic',   name: '极光青', accent: '#22D3EE', accentRgb: '34,211,238' },
  { id: 'lavender', name: '薰衣紫', accent: '#A78BFA', accentRgb: '167,139,250' },
  { id: 'aurora',   name: '极光靛', accent: '#818CF8', accentRgb: '129,140,248' },
];
let accentPresets = [];
let currentAccentId = null;

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
