﻿
let DATA = null;
let tasks = [];
let currentTheme = 'midnight';
let currentGenre = '全部';
let taskFilter = 'all';
let selectedBookIndex = null;
let deAiEnabled = false;
let currentProject = null;

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const appShell = $('#app-shell');

async function loadLibraryData() {
  if (DATA) return DATA;
  try {
    const resp = await fetch(API_BASE + '/library_data.json?v=714');
    if (!resp.ok) throw new Error('status ' + resp.status);
    DATA = await resp.json();
    return DATA;
  } catch (e) {
    console.error('[Library] 加载 library_data.json 失败，使用空数据', e);
    DATA = { books: [], genres: [], counts: {}, tasks: [] };
    return DATA;
  }
}

const GENRE_HUES = {
  '末世': 0, '无限流': 270, '仙侠': 180, '历史': 35, '悬疑': 210,
  '奇幻': 300, '洪荒': 45, '科幻': 200, '都市': 160, '同人': 340
};

function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h) + str.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function coverText(title) {
  const skip = '《》:：,，.．!！?？[]【】""\'\' ';
  const chars = Array.from(title).filter((c) => !skip.includes(c));
  if (chars.length === 0) return '?';
  const first = chars[0];
  const second = chars.find((c, i) => i > 0 && c !== first);
  return second ? first + second : first;
}

function coverStyle(title, genre) {
  const h = hashString(title);
  const base = GENRE_HUES[genre] ?? 220;
  const hue = (base + ((h % 25) - 12) + 360) % 360;
  const sat = 65 + (h % 20);
  const light1 = 52 + ((h >> 4) % 15);
  const light2 = 34 + ((h >> 8) % 15);
  const angle = 100 + (h % 80);
  return 'background: linear-gradient(' + angle + 'deg, hsl(' + hue + ', ' + sat + '%, ' + light1 + '%), hsl(' + (hue - 5) + ', ' + sat + '%, ' + light2 + '%));';
}
// ============================================================
// API 数据层 — 从后端获取真实分析数据
// ============================================================
const apiData = {
  stats: null,
  guidance: null,
  techniques: null,
  instructions: null,
  diagnosis: null,
  skeleton: null,
  ready: false,
};

const API_BASE = '';

async function loadApiData() {
  const endpoints = [
    { key: 'stats', url: API_BASE + '/api/stats' },
    { key: 'guidance', url: API_BASE + '/api/guidance' },
    { key: 'techniques', url: API_BASE + '/api/techniques' },
    { key: 'diagnosis', url: API_BASE + '/api/diagnosis' },
  ];
  try {
    const results = await Promise.allSettled(
      endpoints.map((ep) =>
        fetch(ep.url).then((r) => r.json()).then((d) => { apiData[ep.key] = d; })
      )
    );
    const successCount = results.filter((r) => r.status === 'fulfilled').length;
    apiData.ready = successCount > 0;
    // 刷新可能受影响的渲染
    renderLibrary();
    renderDashboardProject();
    renderReports();
    console.log('[API] Loaded ' + successCount + '/' + endpoints.length + ' endpoints');
  } catch (e) {
    apiData.ready = false;
    console.log('[API] Not available, using embedded data');
  }
}

async function loadInstructions(bookName, chapter) {
  const url = API_BASE + '/api/instructions?book=' + encodeURIComponent(bookName) + '&ch=' + (chapter || 1);
  try {
    const resp = await fetch(url);
    const data = await resp.json();
    apiData.instructions = data;
    return data;
  } catch (e) {
    console.log('[API] Instructions not available');
    return null;
  }
}

async function loadSkeletonData() {
  const btn = $('#btn-load-skeleton');
  if (btn) { btn.textContent = '加载中...'; btn.disabled = true; }
  try {
    const resp = await fetch(API_BASE + '/api/skeleton');
    const data = await resp.json();
    if (data.volumes) {
      apiData.skeleton = data;
      renderDesignFromSkeleton(data);
      showToast('骨架数据已加载（5卷 + 节奏基准）');
    } else {
      showToast('骨架数据格式异常');
    }
  } catch (e) {
    console.log('[API] Skeleton not available');
    showToast('API 不可用，使用本地数据');
  } finally {
    if (btn) { btn.textContent = '从后端加载骨架'; btn.disabled = false; }
  }
}

function renderDesignFromSkeleton(data) {
  // 渲染粗纲（卷卡片）
  const roughPane = $('#design-rough');
  if (roughPane && data.volumes) {
    roughPane.innerHTML = '<div class="volume-grid">' + data.volumes.map(v => {
      return '<div class="volume-card">' +
        '<div class="volume-header"><span class="volume-title">' + v.title + '</span><span class="volume-range">' + v.range + '</span></div>' +
        '<div class="volume-subtitle">' + v.subtitle + '</div>' +
        '<p class="volume-summary">' + v.summary + '</p>' +
        (v.rhythm_goal ? '<div class="volume-rhythm" style="font-size:11px;color:var(--text-secondary);margin-top:4px;">节奏目标: ' + v.rhythm_goal + '</div>' : '') +
        '<div class="volume-tags">' + (v.tags || []).map(t => '<span class="tag">' + t + '</span>').join('') + '</div>' +
        '</div>';
    }).join('') + '</div>';
    DESIGN_DATA.volumes = data.volumes;
  }

  // 渲染细纲（章节列表）
  const detailedPane = $('#design-detailed');
  if (detailedPane && data.chapters) {
    detailedPane.innerHTML = '<div class="chapter-list">' + data.chapters.map(ch => {
      return '<div class="chapter-group">' +
        '<div class="chapter-header">' + ch.title + '</div>' +
        '<div class="chapter-grid">' +
          '<div><b>目标</b><p>' + ch.goal + '</p></div>' +
          '<div><b>冲突</b><p>' + ch.conflict + '</p></div>' +
          '<div><b>结果</b><p>' + ch.result + '</p></div>' +
        '</div>' +
        '<ul class="scene-list">' + (ch.scenes || []).map(s => '<li>' + s + '</li>').join('') + '</ul>' +
        '</div>';
    }).join('') + '</div>';
    DESIGN_DATA.chapters = data.chapters;
  }

  // 渲染世界观
  if (data.world) {
    DESIGN_DATA.world = data.world;
    const worldCore = document.querySelector('#design-world .world-core');
    if (worldCore) {
      worldCore.querySelector('h4').textContent = '世界观核心';
      worldCore.querySelector('p').textContent = data.world.core;
    }
    // 渲染势力
    renderFactionsFromData(data.world.factions || []);
  }

  // 渲染角色
  if (data.characters) {
    DESIGN_DATA.characters = data.characters;
    const charPane = $('#design-characters');
    if (charPane) {
      charPane.innerHTML = '<div class="character-grid">' + data.characters.map(c => {
        return '<div class="character-card">' +
          '<div class="character-avatar" style="background:var(--surface);width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--accent);">' + c.name[0] + '</div>' +
          '<div class="character-info"><b>' + c.name + '</b><span style="font-size:11px;color:var(--text-secondary);">' + c.role + '</span></div>' +
          '<p style="font-size:13px;margin-top:4px;">' + c.desc + '</p>' +
          '</div>';
      }).join('') + '</div>';
    }
  }

  // 更新编辑按钮绑定
  initDesignEditButtons();
  showToast('骨架已渲染到设计页');
}

function renderFactionsFromData(factions) {
  const factionsPane = $('#design-factions');
  if (!factionsPane) return;
  const existingCards = factionsPane.querySelectorAll('.design-card');
  existingCards.forEach(c => c.remove());
  const cardsHtml = factions.map(f => {
    return '<div class="design-card" style="margin-top:12px;"><h3>' + escapeHtml(f.name || '') + '</h3><p>' + escapeHtml(f.desc || '') + '</p></div>';
  }).join('');
  factionsPane.insertAdjacentHTML('beforeend', cardsHtml);
}

async function init() {
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
    updateSaveStatus('saving');
    scheduleSaveStatusSaved();
    try {
      localStorage.setItem('draft_content', $('#editor-textarea').value || '');
      localStorage.setItem('draft_title', $('#editor-title').value || '');
    } catch (e) {}
  });
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
  setInterval(checkModelStatus, 30000);
}

function updateTopbarProjectName() {
  const el = $('#topbar-project-name');
  if (!el) return;
  el.textContent = (currentProject && currentProject.title) ? currentProject.title : '';
}

function updateSaveStatus(state) {
  const el = $('#save-status');
  if (!el) return;
  if (state === 'saving') {
    el.textContent = '保存中...';
    el.style.opacity = '1';
  } else if (state === 'saved') {
    el.textContent = '已保存';
    el.style.opacity = '0.7';
  }
}

let saveStatusTimeout = null;
function scheduleSaveStatusSaved() {
  if (saveStatusTimeout) clearTimeout(saveStatusTimeout);
  saveStatusTimeout = setTimeout(() => updateSaveStatus('saved'), 800);
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
  try {
    const res = await fetch('/api/config');
    if (!res.ok) throw new Error('fetch failed');
    const cfg = await res.json();
    const localModel = cfg.local_model || '';
    const localEndpoint = cfg.local_endpoint || '';
    if (!localModel || !localEndpoint) {
      setStatus('status-offline', '本地模型未启用', 'warn');
      return;
    }
    // 尝试 ping 本地模型端点
    try {
      const ping = await fetch(localEndpoint.replace(/\/$/, '') + '/v1/models', { method: 'GET', signal: AbortSignal.timeout(5000) });
      if (!ping.ok) throw new Error('ping failed');
      setStatus('status-online', localModel);
    } catch (err) {
      setStatus('status-offline', localModel + ' · 未连接', 'warn');
    }
  } catch (e) {
    setStatus('status-error', '配置获取失败', 'danger');
  }
}

function restoreRoute() {
  const page = (window.location.hash || '').replace('#', '') || 'dashboard';
  const valid = ['dashboard','library','disassembly','writing','design','reports','tasks','hardware','settings'];
  if (valid.includes(page)) {
    navigate(page);
  } else {
    navigate('dashboard');
    showToast('页面不存在，已返回工作台');
  }
}

function loadProject() {
  currentProject = null;
  try {
    const saved = localStorage.getItem('current_project');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed && typeof parsed === 'object' && parsed.title) {
        currentProject = parsed;
      } else {
        localStorage.removeItem('current_project');
      }
    }
  } catch (e) {
    currentProject = null;
    try { localStorage.removeItem('current_project'); } catch (err) {}
  }
  renderDashboardProject();
  updateTopbarProjectName();
}
function saveProject(project) {
  currentProject = project;
  try { localStorage.setItem('current_project', JSON.stringify(project)); } catch (e) {}
  renderDashboardProject();
  updateTopbarProjectName();
}
function renderDashboardProject() {
  const hasProject = !!currentProject;
  const hero = $('#hero-has-project');
  const empty = $('#hero-empty-state');
  const sidebar = $('.dashboard-sidebar');
  const pipeline = $('.pipeline-station');
  const section = $('.dashboard-section');
  const kpiRow = $('.library-kpi-row');
  const workstation = $('#dashboard-workstation');
  if (hero) hero.style.display = hasProject ? '' : 'none';
  if (empty) empty.style.display = hasProject ? 'none' : '';
  if (sidebar) sidebar.style.display = hasProject ? '' : 'none';
  if (pipeline) pipeline.style.display = hasProject ? '' : 'none';
  if (section) section.style.display = hasProject ? '' : 'none';
  if (kpiRow) kpiRow.style.display = hasProject ? '' : 'none';
  if (workstation) workstation.style.gridTemplateColumns = hasProject ? '' : '1fr';
  if (hasProject) {
    $('#hero-title').textContent = currentProject.title || '未命名作品';
    $('#hero-greeting').textContent = greetingByHour() + '，' + (currentProject.author || '作者');
    $('#hero-volumes').textContent = currentProject.volumes || 0;
    $('#hero-chapters').textContent = currentProject.totalChapters || 0;
    $('#hero-genre').textContent = currentProject.genre || '未设置';
    $('#hero-stat-chapters').textContent = currentProject.writtenChapters || 0;
    const progress = currentProject.totalChapters ? Math.round((currentProject.writtenChapters || 0) / currentProject.totalChapters * 100) : 0;
    $('#hero-stat-progress').textContent = progress + '%';
    $('#hero-stat-cards').textContent = currentProject.cards || 0;
    $('#dashboard-subtitle').textContent = currentProject.genre ? (currentProject.genre + ' · ' + (currentProject.writtenChapters || 0) + '/' + (currentProject.totalChapters || 0) + ' 章') : '项目信息待完善';
  } else {
    $('#dashboard-subtitle').textContent = '当前无进行中的项目';
  }
}
function greetingByHour() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}
function createProject() {
  $('#cp-title').value = '';
  $('#cp-genre').value = '末世';
  $('#cp-volumes').value = 5;
  $('#cp-chapters').value = 300;
  $('#cp-desc').value = '';
  $('#create-project-modal').classList.add('open');
}
function closeCreateProjectModal() {
  $('#create-project-modal').classList.remove('open');
}
function confirmCreateProject() {
  const title = $('#cp-title').value.trim();
  if (!title) { showToast('请输入作品名称'); return; }
  const genre = $('#cp-genre').value || '末世';
  const volumes = parseInt($('#cp-volumes').value) || 5;
  const chapters = parseInt($('#cp-chapters').value) || 300;
  saveProject({
    title: '《' + title.replace(/《|》/g, '') + '》',
    author: '作者',
    genre: genre,
    volumes: volumes,
    totalChapters: chapters,
    writtenChapters: 0,
    cards: 0,
    createdAt: new Date().toISOString()
  });
  closeCreateProjectModal();
  showToast('已创建作品 ' + title);
  renderDashboardProject();
  // 创建后引导
  setTimeout(() => {
    showToast('下一步：在书库中导入参考书，或在设计页规划粗纲');
  }, 2800);
}
function loadDemoProject() {
  saveProject({
    title: '《末日模拟器》',
    author: '作者',
    genre: '末世',
    volumes: 5,
    totalChapters: 300,
    writtenChapters: 127,
    cards: 156,
    createdAt: new Date().toISOString()
  });
  showToast('已加载示例项目');
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
  if (page === 'writing') { renderOutlinePanel(); renderImportedReport(); initInstructionsPanel(); }
  if (page === 'settings') { loadSettingsConfig(); }
}

const THEME_ORDER = ['midnight', 'light', 'obsidian'];
const ACCENT_PRESETS = [
  { id: 'sky',    name: '天蓝', accent: '#38BDF8', accentRgb: '56,189,248' },
  { id: 'tomato', name: '番茄', accent: '#F86840', accentRgb: '248,104,64' },
];
let currentAccentId = null;
let accentPresets = [];

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
  const root = document.documentElement.style;
  root.setProperty('--accent', preset.accent);
  root.setProperty('--accent-rgb', preset.accentRgb);
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
  try {
    const resp = await fetch(API_BASE + '/api/config');
    const cfg = await resp.json();
    if (Array.isArray(cfg.theme_presets) && cfg.theme_presets.length) {
      accentPresets = cfg.theme_presets.map((p) => ({
        id: p.id,
        name: p.name,
        accent: p.accent,
        accentRgb: p.accent_rgb,
      }));
    }
  } catch (e) {}
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

const HW_THRESHOLDS = {
  gpu: { warn: 75, danger: 85 },
  vram: { warn: 80, danger: 90 },
  cpu: { warn: 80, danger: 92 },
  ram: { warn: 85, danger: 94 },
  power: { warn: 220, danger: 260 },
};

let hwMetrics = { gpu: 68, vram: 72, cpu: 41, ram: 55, power: 188 };
let hwInterval = null;

function getHwStatus(key, value) {
  const t = HW_THRESHOLDS[key];
  if (value >= t.danger) return 'danger';
  if (value >= t.warn) return 'warn';
  return 'normal';
}

function getOverallHwStatus() {
  let status = 'normal';
  for (const key of Object.keys(hwMetrics)) {
    const s = getHwStatus(key, hwMetrics[key]);
    if (s === 'danger') return 'danger';
    if (s === 'warn') status = 'warn';
  }
  return status;
}

function formatHwValue(key, value) {
  if (key === 'gpu') return value + '°C';
  if (key === 'power') return value + 'W';
  return value + '%';
}

function renderHardwareMonitor() {
  const pill = $('#hw-status-pill');
  const text = $('#hw-status-text');
  const subtitle = $('#hw-dropdown-subtitle');
  if (!pill) return;

  const overall = getOverallHwStatus();
  pill.classList.remove('status-warn', 'status-danger');
  if (overall !== 'normal') pill.classList.add('status-' + overall);

  const labelMap = {
    normal: '系统正常',
    warn: '硬件注意',
    danger: '硬件告警',
  };
  text.textContent = labelMap[overall];
  if (subtitle) subtitle.textContent = labelMap[overall];

  const hwBadge = $('#nav-badge-hardware');
  if (hwBadge) {
    hwBadge.className = 'nav-badge';
    if (overall !== 'normal') hwBadge.classList.add(overall);
  }

  for (const key of Object.keys(hwMetrics)) {
    const valueEl = $('#hw-' + key + '-value');
    const statusEl = $('#hw-' + key + '-status');
    if (valueEl) valueEl.textContent = formatHwValue(key, hwMetrics[key]);
    if (statusEl) {
      const s = getHwStatus(key, hwMetrics[key]);
      statusEl.classList.remove('status-warn', 'status-danger');
      statusEl.textContent = s === 'normal' ? '正常' : (s === 'warn' ? '注意' : '告警');
      if (s !== 'normal') statusEl.classList.add('status-' + s);
    }

    const dashBar = $('#dash-' + key + '-bar');
    const dashValue = $('#dash-' + key + '-value');
    const dashRow = document.querySelector('.health-row[data-key="' + key + '"]');
    if (dashBar) {
      const s = getHwStatus(key, hwMetrics[key]);
      const max = key === 'power' ? 300 : 100;
      const pct = Math.min(100, Math.round((hwMetrics[key] / max) * 100));
      dashBar.style.width = pct + '%';
      if (dashRow) {
        dashRow.classList.remove('status-normal', 'status-warn', 'status-danger');
        dashRow.classList.add('status-' + s);
      }
    }
    if (dashValue) {
      dashValue.textContent = formatHwValue(key, hwMetrics[key]);
      if (key === 'vram') dashValue.textContent = hwMetrics[key] + '%';
    }
  }

  const dashModel = $('#dash-model-status');
  const dashModelName = $('#dash-model-name');
  if (dashModel && dashModelName) {
    const overallStatus = getOverallHwStatus();
    const modelEl = dashModel.parentElement;
    if (modelEl) {
      modelEl.classList.remove('warn', 'danger');
      if (overallStatus !== 'normal') modelEl.classList.add(overallStatus);
    }
    dashModel.textContent = overallStatus === 'normal' ? '在线' : (overallStatus === 'warn' ? '注意' : '告警');
  }
}

function renderHardwarePageGauges() {
  const cards = {
    gpu: { type: 'ring', max: 100 },
    vram: { type: 'bar', max: 100 },
    ram: { type: 'bar', max: 100 },
    cpu: { type: 'bar', max: 100 },
    power: { type: 'bar', max: 300 },
  };
  for (const key of Object.keys(cards)) {
    const card = $('#gauge-' + key);
    if (!card) continue;
    const value = hwMetrics[key];
    const status = getHwStatus(key, value);
    const conf = cards[key];
    const pct = Math.round((value / conf.max) * 100);
    card.classList.remove('status-normal', 'status-warn', 'status-danger');
    card.classList.add('status-' + status);

    const valueEl = $('#gauge-' + key + '-value');
    if (valueEl) valueEl.textContent = formatHwValue(key, value);

    if (conf.type === 'ring') {
      const ring = card.querySelector('.gauge');
      if (ring) ring.style.setProperty('--p', pct);
      const statusEl = $('#gauge-' + key + '-status');
      if (statusEl) {
        statusEl.classList.remove('normal', 'warn', 'danger');
        statusEl.classList.add(status);
        statusEl.textContent = status === 'normal' ? '正常' : (status === 'warn' ? '注意' : '告警');
      }
    } else {
      const bar = $('#gauge-' + key + '-bar');
      if (bar) bar.style.width = pct + '%';
    }
  }
}

function simulateHardwareMetrics() {
  hwMetrics.gpu = Math.min(95, Math.max(40, hwMetrics.gpu + Math.floor(Math.random() * 5) - 2));
  hwMetrics.vram = Math.min(98, Math.max(20, hwMetrics.vram + Math.floor(Math.random() * 5) - 2));
  hwMetrics.cpu = Math.min(99, Math.max(5, hwMetrics.cpu + Math.floor(Math.random() * 7) - 3));
  hwMetrics.ram = Math.min(99, Math.max(20, hwMetrics.ram + Math.floor(Math.random() * 5) - 2));
  hwMetrics.power = Math.min(320, Math.max(100, hwMetrics.power + Math.floor(Math.random() * 13) - 6));
  renderHardwareMonitor();
  renderHardwarePageGauges();
}

function initHardwareMonitor() {
  renderHardwareMonitor();
  renderHardwarePageGauges();
  if (hwInterval) clearInterval(hwInterval);
  hwInterval = setInterval(simulateHardwareMetrics, 3000);
}

function renderPipelineStates() {
  document.querySelectorAll('.pipeline-stage').forEach((stage) => {
    const dot = stage.querySelector('.stage-dot');
    const name = stage.querySelector('.stage-name');
    const icon = stage.querySelector('.stage-icon');
    if (!dot) return;
    const state = dot.classList.contains('completed') ? 'completed' : (dot.classList.contains('running') ? 'running' : 'pending');
    stage.classList.remove('completed', 'running', 'pending');
    stage.classList.add(state);
    if (name) {
      name.classList.remove('completed', 'running', 'pending');
      name.classList.add(state);
    }
    if (icon) {
      icon.classList.remove('completed', 'running', 'pending');
      icon.classList.add(state);
    }
  });
}

function toggleHardwareDropdown(e) {
  if (e) e.stopPropagation();
  const dropdown = $('#hw-dropdown');
  const pill = $('#hw-status-pill');
  if (!dropdown || !pill) return;
  const isOpen = dropdown.classList.toggle('open');
  pill.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  dropdown.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
}

function closeHardwareDropdown() {
  const dropdown = $('#hw-dropdown');
  const pill = $('#hw-status-pill');
  if (dropdown) dropdown.classList.remove('open');
  if (pill) {
    pill.setAttribute('aria-expanded', 'false');
  }
  if (dropdown) dropdown.setAttribute('aria-hidden', 'true');
}

// 点击页面其他地方关闭硬件下拉和写作页更多菜单
document.addEventListener('click', function(e) {
  const monitor = $('#hw-monitor');
  if (monitor && !monitor.contains(e.target)) closeHardwareDropdown();
  const more = $('.writing-more-dropdown.open');
  if (more && !more.contains(e.target)) more.classList.remove('open');
});

function applyHwMonitorVisibility() {
  const monitor = $('#hw-monitor');
  if (!monitor) return;
  let show = true;
  try { show = localStorage.getItem('setting_show-hw-monitor') !== '0'; } catch (e) {}
  monitor.style.display = show ? '' : 'none';
}

function toggleSetting(key) {
  const input = $('input[data-setting="' + key + '"]');
  if (input) {
    try { localStorage.setItem('setting_' + key, input.checked ? '1' : '0'); } catch (e) {}
    showToast((input.checked ? '已开启 ' : '已关闭 ') + key);
    if (key === 'show-hw-monitor') applyHwMonitorVisibility();
  }
}

function saveSetting(key, value) {
  try { localStorage.setItem('setting_' + key, value); } catch (e) {}
  showToast('已保存 ' + key);
}

async function loadSettingsConfig() {
  try {
    const resp = await fetch(API_BASE + '/api/config');
    const cfg = await resp.json();
    const localInput = $('#settings-local-model');
    const cloudInput = $('#settings-cloud-model');
    if (localInput && cfg.local_model) {
      // 仅当用户未手动覆盖时才更新
      if (!localStorage.getItem('setting_localModel')) {
        localInput.value = cfg.local_model;
      }
    }
    if (cloudInput && cfg.cloud_model) {
      if (!localStorage.getItem('setting_cloudModel')) {
        cloudInput.value = cfg.cloud_model + (cfg.cloud_provider ? ' (' + cfg.cloud_provider + ')' : '');
      }
    }
  } catch (e) {
    console.log('[Settings] 无法加载后端配置', e);
  }
}

function restoreSettings() {
  try {
    const localModel = localStorage.getItem('setting_localModel');
    if (localModel !== null) $('#settings-local-model').value = localModel;
    const localEndpoint = localStorage.getItem('setting_localEndpoint');
    if (localEndpoint !== null) $('#settings-local-endpoint').value = localEndpoint;
    const cloudModel = localStorage.getItem('setting_cloudModel');
    if (cloudModel !== null) $('#settings-cloud-model').value = cloudModel;
    const dataDir = localStorage.getItem('setting_dataDir');
    if (dataDir !== null) $('#settings-data-dir').value = dataDir;
    ['auto-import', 'auto-rhythm', 'show-hw-monitor'].forEach((k) => {
      const v = localStorage.getItem('setting_' + k);
      const input = $('input[data-setting="' + k + '"]');
      if (input && v !== null) input.checked = v === '1';
    });
    applyHwMonitorVisibility();
  } catch (e) {}
}

function exportSettings() {
  try {
    const data = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith('setting_')) data[k] = localStorage.getItem(k);
    }
    data['theme'] = currentTheme;
    data['draft_title'] = localStorage.getItem('draft_title') || '';
    data['draft_content'] = localStorage.getItem('draft_content') || '';
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'fanqie-settings-' + new Date().toISOString().slice(0, 10) + '.json';
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('配置已导出');
  } catch (e) {
    showToast('导出失败');
  }
}

function resetSettings() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && (k.startsWith('setting_') || k === 'theme')) keys.push(k);
    }
    keys.forEach((k) => localStorage.removeItem(k));
    setTheme('midnight');
    restoreSettings();
    showToast('偏好已重置');
  } catch (e) {
    showToast('重置失败');
  }
}

function renderGenreTabs(countsOverride) {
  const counts = countsOverride || DATA.counts || [];
  const tabs = $('#genre-tabs');
  if (!tabs) return;
  tabs.innerHTML = counts.map(([genre, count]) =>
    '<button class="genre-tab' + (genre === currentGenre ? ' active' : '') + '" data-genre="' + genre + '" onclick="filterLibrary(\'' + genre + '\')">' + genre + '(' + count + ')</button>'
  ).join('');
}

function filterLibrary(genre) {
  currentGenre = genre;
  renderLibrary();
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

function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function renderLibrary() {
  const grid = $('#book-grid');
  if (!grid) return;
  const totalBooks = DATA.books.length;
  const genres = DATA.genres || [];
  const totalWords = DATA.books.reduce((sum, b) => sum + (b.wordCount || 0), 0);
  // API 数据增强：优先使用后端统计
  const apiStats = apiData.stats || {};
  const displayBooks = apiStats.total_books || totalBooks;
  const displayGenres = apiStats.genres || genres.length;
  const libKpiCount = $('#lib-kpi-count');
  const libKpiImported = $('#lib-kpi-imported');
  const libKpiGenres = $('#lib-kpi-genres');
  if (libKpiCount) libKpiCount.textContent = displayBooks;
  if (libKpiImported) libKpiImported.textContent = totalBooks;
  if (libKpiGenres) libKpiGenres.textContent = displayGenres;
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
  const cards = filtered.map((b) => {
    const idx = DATA.books.indexOf(b);
    const tags = (DATA.tagPools && DATA.tagPools[b.title]) || [b.genre];
    const cover = coverText(b.title);
    const singleClass = cover.length === 1 ? 'cover-single' : '';
    const tagsHtml = tags.map((t) => '<span class="tag">' + escapeHtml(t) + '</span>').join('');
    return '<article class="book-card" data-genre="' + escapeHtml(b.genre || '') + '" data-index="' + idx + '" onclick="selectBook(' + idx + ')">' +
      '<div class="cover-block" style="' + coverStyle(b.title, b.genre) + '"><span class="cover-abbr ' + singleClass + '">' + escapeHtml(cover) + '</span></div>' +
      '<div class="book-meta">' +
        '<h4 class="book-title">' + escapeHtml(b.title) + '</h4>' +
        '<div class="book-author">' + escapeHtml(b.author) + '</div>' +
        '<div class="book-stats"><span>' + fmtNumber(b.wordCount) + '字</span><span>' + fmtSize(b.size_kb) + '</span></div>' +
        '<div class="book-tags">' + tagsHtml + '</div>' +
      '</div></article>';
  }).join('');
  grid.innerHTML = cards || '<div class="empty-state">' + (query ? '未找到含「' + escapeHtml(query) + '」的书籍' : '暂无该题材书籍') + '</div>';
  $$('#genre-tabs .genre-tab').forEach((t) => t.classList.toggle('active', t.dataset.genre === currentGenre));
  const countEl = $('#lib-kpi-count');
  if (countEl) countEl.textContent = String(filtered.length);
  const importedEl = $('#lib-kpi-imported');
  if (importedEl) importedEl.textContent = String(filtered.length);
}

function selectBook(idx) {
  selectedBookIndex = idx;
  const b = DATA.books[idx];
  const tags = (DATA.tagPools && DATA.tagPools[b.title]) || [b.genre];
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
  $('#detail-tags').innerHTML = tags.map((t) => '<span class="tag">' + escapeHtml(t) + '</span>').join('');
  $('#detail-files').innerHTML = '<div>TXT: ' + escapeHtml(b.file || '') + '</div><div>Rhythm: ' + escapeHtml(b.rhythm_csv || '') + '</div>';
}

function closeDetail() {
  appShell.classList.add('no-detail');
  appShell.classList.remove('detail-open');
  selectedBookIndex = null;
}

function renderReports() {
  const grid = $('#report-grid');
  if (!grid) return;
  const guidance = apiData.guidance || {};
  const techniques = apiData.techniques || {};
  const diagnosis = apiData.diagnosis || {};
  const stats = apiData.stats || {};

  // 动态生成报告卡片：优先使用 API 数据，否则用静态数据
  const reports = [];

  // 1. 创作指导摘要（来自 API）
  if (guidance.guidance) {
    const firstGuidance = guidance.guidance ? guidance.guidance[0] : '';
    reports.push({
      type: 'writing',
      dotClass: 'green',
      title: '创作指导摘要',
      category: '写作指导',
      insight: (firstGuidance || '').substring(0, 100) || '从 ' + (stats.analyzed_books || 30) + ' 本末世小说中提炼的创作指导',
      meta: (stats.genre_focus || '末世') + '题材 · ' + (stats.analyzed_chapters || 0) + ' 章分析',
      tags: ['写作', '指导'],
      detail: (guidance.guidance || []).join('\n\n'),
    });
  } else {
    reports.push(REPORT_DATA[0]);
  }

  // 2. 跨书合成发现
  if (guidance.dominant_conflicts) {
    const topConflict = guidance.dominant_conflicts[0];
    reports.push({
      type: 'market',
      dotClass: 'blue',
      title: '跨书合成发现', category: '跨书对比',
      insight: '末世题材中"' + topConflict.type + '"类冲突占比 ' + topConflict.pct + '%，是主要叙事驱动力',
      meta: '覆盖 ' + (stats.analyzed_books || 30) + ' 本书 · ' + (guidance.arc_distribution ? '已分析弧线分布' : ''),
      tags: ['市场', '末世'],
      detail: '主导冲突类型：\n' + (guidance.dominant_conflicts || []).map(c => '- ' + c.type + ': ' + c.pct + '%').join('\n'),
    });
  } else {
    reports.push(REPORT_DATA[1]);
  }

  // 3. 技法卡片库
  if (techniques.sections) {
    reports.push({
      type: 'tech',
      dotClass: 'amber',
      title: '写作技法总纲', category: '技法提炼',
      insight: '包含 ' + techniques.sections.length + ' 个技法模块：' + techniques.sections.slice(0, 3).join('、') + '等',
      meta: techniques.sections.length + ' 个模块',
      tags: ['技法', '卡片'],
      detail: '技法模块列表：\n' + techniques.sections.map(s => '- ' + s).join('\n'),
    });
  } else {
    reports.push(REPORT_DATA[2]);
  }

  // 4. 深度诊断
  if (diagnosis && !diagnosis.error && Object.keys(diagnosis).length > 0) {
    reports.push({
      type: 'rhythm',
      dotClass: 'purple',
      title: '深度诊断对比', category: '节奏拆解',
      insight: 'Top vs Bottom 作品对比分析，揭示商业成功的关键因素',
      meta: '诊断数据已就绪',
      tags: ['诊断', '对比'],
      detail: formatDiagnosisReport(diagnosis),
    });
  } else {
    reports.push(REPORT_DATA[3]);
  }

  // 5. 角色指导
  if (guidance.character_guidance) {
    reports.push({
      type: 'character',
      dotClass: 'green',
      title: '角色创作指导', category: '人物分析',
      insight: (guidance.character_guidance || '').substring(0, 100),
      meta: stats.genre_focus || '末世',
      tags: ['人物', '角色'],
      detail: guidance.character_guidance || '',
    });
  } else {
    reports.push(REPORT_DATA[4]);
  }

  // 6. 钩子基准
  const hookBenchmark = guidance.opening_hook_benchmark;
  if (hookBenchmark != null) {
    reports.push({
      type: 'market',
      dotClass: 'blue',
      title: '开篇钩子基准',
      insight: '末世题材开篇平均钩子密度 ' + hookBenchmark + ' 个/千字，作为写作参考基准',
      meta: (stats.analyzed_books || 30) + ' 本样本',
      tags: ['市场', '趋势'],
      detail: '开篇钩子基准：' + hookBenchmark + ' 个/千字\n' + (guidance.hook_rule || ''),
    });
  } else {
    reports.push(REPORT_DATA[5]);
  }

  // 渲染报告卡片
  grid.innerHTML = reports.map((r, idx) => {
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
  if (countEl) countEl.textContent = '共 ' + reports.length + ' 份报告';

  // 同步更新 REPORT_DATA 以支持详情弹窗
  window._DYNAMIC_REPORTS = reports;

  // 更新侧边栏统计
  const sidebarStats = $('#report-sidebar-stats');
  if (sidebarStats) {
    sidebarStats.innerHTML = reports.map(r => {
      return '<div class="summary-row"><span>' + escapeHtml(r.title || '') + '</span><span class="summary-row-value">' + escapeHtml(r.meta || '') + '</span></div>';
    }).join('');
  }

  // 更新后端数据统计
  const apiStats = apiData.stats;
  if (apiStats && apiStats.analyzed_books) {
    const apiPanel = $('#report-api-stats');
    if (apiPanel) apiPanel.style.display = '';
    const rsBooks = $('#rs-api-books');
    if (rsBooks) rsBooks.textContent = apiStats.analyzed_books;
    const rsChapters = $('#rs-api-chapters');
    if (rsChapters) rsChapters.textContent = apiStats.analyzed_chapters;
    const rsGenre = $('#rs-api-genre');
    if (rsGenre) rsGenre.textContent = apiStats.genre_focus;
    const rsHook = $('#rs-api-hook');
    if (rsHook) rsHook.textContent = apiStats.hook_benchmark;
  }
}

function startAnalysisFromDetail() {
  if (selectedBookIndex === null) return;
  const b = DATA.books[selectedBookIndex];
  createTask('full_pipeline', '全部', [b.title]);
  navigate('disassembly');
  showToast('已创建分析任务');
}

const REPORT_DATA = [
  {
    title: '创作指导摘要',
    category: '写作指导',
    meta: '写作指导',
    insight: '当前卷需要强化主角动机转折，建议在第三章加入外部压力事件，以提升节奏张力。',
    detail: '通过对已写 127 章的节奏曲线分析，发现第 3 章、第 11 章和第 22 章的爽点密度偏低。\n\n建议：\n1. 在第 3 章末尾加入“黑塔提前降临”的伏笔；\n2. 让主角在资源分配上与队友产生冲突；\n3. 每章结尾保留一个未解答的悬念。'
  },
  {
    title: '跨书合成发现',
    category: '跨书对比',
    meta: '跨书对比',
    insight: '末世题材中“团体生存”与“种田”组合出现频率最高，可作为下一卷世界观锚点。',
    detail: '对 33 本末世/无限流头部作品进行标签共现分析后发现：\n\n- 高商业分作品中，76% 包含“团体生存”标签；\n- 其中又有 58% 同时包含“种田/囤货”标签；\n- 该组合在 30-60 万字区间表现最佳。\n\n结论：第二卷可围绕“据点建设 + 资源管理”展开。'
  },
  {
    title: '技法卡片库',
    category: '技法提炼',
    meta: '技法提炼',
    insight: '已提炼 156 张技法卡片，其中“悬念铺设”类占比 23%，可直接插入写作指导。',
    detail: '技法卡片分类统计：\n\n- 悬念铺设：36 张\n- 情绪渲染：28 张\n- 节奏控制：24 张\n- 人物塑造：31 张\n- 世界观揭示：22 张\n- 对话技巧：15 张\n\n推荐在下一卷优先使用“悬念铺设”类卡片。'
  },
  {
    title: '第127章节奏分析',
    category: '节奏拆解',
    meta: '节奏拆解',
    insight: '本章爽点密度偏低，结尾悬念不足。建议增加一个突发事件或情绪反转。',
    detail: '节奏曲线显示本章前 70% 推进平缓，高潮出现在 85% 位置但收尾过快。\n\n建议：\n1. 在 60% 处加入一次小型冲突；\n2. 结尾保留一个未解悬念；\n3. 减少环境描写，增加动作与对话。'
  },
  {
    title: '主角成长弧线',
    category: '人物分析',
    meta: '人物分析',
    insight: '主角从被动求生到主动领导过渡自然，但中期缺乏一次重大失败来加深人物厚度。',
    detail: '主角动机转变分析：\n\n- 第一阶段（1-60章）：被动求生，以自保为主；\n- 第二阶段（61-120章）：开始承担责任，但决策仍偏保守；\n- 第三阶段（121-180章）：需要一次信任崩塌来推动成熟。\n\n建议在第 140 章左右设计一次“误判导致队友牺牲”的情节。'
  },
  {
    title: '末世题材热度趋势',
    category: '市场分析',
    meta: '市场分析',
    insight: '“丧尸+种田”“异能+团队”两类开篇完读率最高，可作为新书开篇参考。',
    detail: '基于 28 本末世题材头部作品的开篇分析：\n\n- 丧尸+种田：完读率均值 18.3%；\n- 异能+团队：完读率均值 16.7%；\n- 重生囤货：完读率均值 14.2%；\n- 独行求生：完读率均值 11.5%。\n\n结论：新书开篇优先考虑“危机+团队建设”双线并进。'
  }
];
let currentReportIndex = null;

function openReportDetail(idx) {
  currentReportIndex = idx;
  const reports = getCurrentReports();
  const r = reports[idx];
  if (!r) return;
  $('#report-detail-title').textContent = r.title;
  let extraContent = '';
  if (r.category === '节奏拆解') {
    extraContent = '<div class="report-detail-field"><label>节奏曲线</label><div class="rhythm-curve" id="rhythm-curve-' + idx + '"><canvas id="rhythm-canvas-' + idx + '"></canvas></div></div>';
  }
  if (r.category === '技法提炼') {
    extraContent = '<div class="report-detail-field"><label>技法卡片</label><div class="technique-grid" id="technique-grid-' + idx + '"></div></div>';
  }
  if (r.category === '跨书对比') {
    extraContent = '<div class="report-detail-field"><label>对比数据</label><div class="cross-book-data" id="cross-book-data-' + idx + '"></div></div>';
  }
  $('#report-detail-body').innerHTML =
    '<div class="report-detail-field"><label>核心洞察</label><textarea id="report-insight-edit">' + escapeHtml(r.insight || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>详细分析</label><textarea id="report-detail-edit">' + escapeHtml(r.detail || '') + '</textarea></div>' +
    extraContent +
    '<div class="report-ai-suggestions" id="report-ai-box" style="display:none"></div>';
  $('#report-detail').classList.add('open');
  $('#report-detail-overlay').classList.add('open');
  // 延迟渲染图表
  setTimeout(() => {
    if (r.category === '节奏拆解') drawRhythmCurve(idx);
    if (r.category === '技法提炼') renderTechniqueCards(idx);
    if (r.category === '跨书对比') renderCrossBookData(idx);
  }, 100);
}

function closeReportDetail() {
  $('#report-detail').classList.remove('open');
  $('#report-detail-overlay').classList.remove('open');
  currentReportIndex = null;
}

function aiSuggestReport() {
  const box = $('#report-ai-box');
  if (!box) return;
  box.style.display = 'block';
  box.innerHTML = '<h4>AI 建议</h4><ul>' +
    '<li>在第三章加入“黑塔提前出现”的伏笔，强化外部压力。</li>' +
    '<li>让主角在资源分配上与队友产生冲突，制造内在张力。</li>' +
    '<li>每章结尾保留一个未解答的悬念，提升追读率。</li>' +
    '</ul>';
}

function getCurrentReports() {
  return window._DYNAMIC_REPORTS && window._DYNAMIC_REPORTS.length ? window._DYNAMIC_REPORTS : REPORT_DATA;
}

function saveReportEdit() {
  if (currentReportIndex === null) return;
  const reports = getCurrentReports();
  reports[currentReportIndex].insight = $('#report-insight-edit').value;
  reports[currentReportIndex].detail = $('#report-detail-edit').value;
  showToast('报告已保存');
  closeReportDetail();
}

let importedReportData = null;
function showLoading() {
  const overlay = $('#loading-overlay');
  if (overlay) overlay.classList.add('show');
}

function hideLoading() {
  const overlay = $('#loading-overlay');
  if (overlay) overlay.classList.remove('show');
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

function drawRhythmCurve(idx) {
  const canvas = document.getElementById('rhythm-canvas-' + idx);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 200 * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = '200px';
  ctx.scale(dpr, dpr);
  const w = rect.width, h = 200, pad = 20;
  const points = [];
  for (let i = 0; i < 30; i++) {
    points.push(0.3 + 0.4 * Math.sin(i * 0.4) + 0.2 * Math.cos(i * 0.25) + 0.1 * Math.random());
  }
  ctx.strokeStyle = 'var(--accent)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((v, i) => {
    const x = pad + (w - 2 * pad) * i / (points.length - 1);
    const y = h - pad - v * (h - 2 * pad);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = 'rgba(245,158,11,0.1)';
  ctx.lineTo(w - pad, h - pad);
  ctx.lineTo(pad, h - pad);
  ctx.closePath();
  ctx.fill();
}

function renderTechniqueCards(idx) {
  const grid = document.getElementById('technique-grid-' + idx);
  if (!grid) return;
  const techniques = [
    { name: '悬念锚定', from: '《末日蟑螂》', excerpt: '每章结尾制造1个未解答的问题，读者留存率提升37%' },
    { name: '时间压缩', from: '《黑暗血时代》', excerpt: '关键场景使用短句+短段落，制造紧迫感' },
    { name: '反转预埋', from: '《末日轮盘》', excerpt: '在第3章就埋下第15章的反转线索' },
    { name: '对话张力', from: '《废土》', excerpt: '角色对话中隐含权力博弈，每句对话推进情节' },
  ];
  grid.innerHTML = techniques.map(t =>
    '<div class="technique-card">' +
    '<h4>' + t.name + '</h4>' +
    '<div class="tech-from">来源：' + t.from + '</div>' +
    '<div class="tech-excerpt">' + t.excerpt + '</div>' +
    '</div>'
  ).join('');
}

function renderCrossBookData(idx) {
  const container = document.getElementById('cross-book-data-' + idx);
  if (!container) return;
  container.innerHTML =
    '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
    '<tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:6px">维度</th><th style="text-align:left;padding:6px">《末日蟑螂》</th><th style="text-align:left;padding:6px">《黑暗血时代》</th><th style="text-align:left;padding:6px">你的作品</th></tr>' +
    '<tr style="border-bottom:1px solid var(--border)"><td style="padding:6px">节奏密度</td><td style="padding:6px">高</td><td style="padding:6px">中</td><td style="padding:6px;color:var(--accent)">中高</td></tr>' +
    '<tr style="border-bottom:1px solid var(--border)"><td style="padding:6px">悬念频率</td><td style="padding:6px">3.2/章</td><td style="padding:6px">2.1/章</td><td style="padding:6px;color:var(--accent)">2.8/章</td></tr>' +
    '<tr style="border-bottom:1px solid var(--border)"><td style="padding:6px">战斗占比</td><td style="padding:6px">35%</td><td style="padding:6px">28%</td><td style="padding:6px;color:var(--accent)">31%</td></tr>' +
    '</table>';
}
function importReportToWriting() {
  if (currentReportIndex == null) return;
  const reports = getCurrentReports();
  const r = reports[currentReportIndex];
  importedReportData = { title: r.title, insight: r.insight, detail: r.detail, importedAt: new Date().toLocaleString() };
  closeReportDetail();
  showToast('已导入写作辅助');
  renderImportedReport();
}

function formatDiagnosisReport(data) {
  const lines = [];
  lines.push('深度诊断数据概览：');
  lines.push('');
  if (data.summary) {
    lines.push('【摘要】');
    lines.push(data.summary);
    lines.push('');
  }
  if (data.top_vs_bottom && typeof data.top_vs_bottom === 'object') {
    lines.push('【Top vs Bottom 对比】');
    Object.entries(data.top_vs_bottom).forEach(([k, v]) => {
      lines.push('- ' + k + ': ' + v);
    });
    lines.push('');
  }
  if (data.insights && Array.isArray(data.insights)) {
    lines.push('【关键洞察】');
    data.insights.forEach(item => lines.push('- ' + item));
    lines.push('');
  }
  if (data.recommendations && Array.isArray(data.recommendations)) {
    lines.push('【优化建议】');
    data.recommendations.forEach(item => lines.push('- ' + item));
    lines.push('');
  }
  return lines.join('\n') || '诊断数据已加载，暂无结构化摘要。';
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

function renderOutlinePanel() {
  const body = document.getElementById('outline-panel-body');
  if (!body) return;
  const vol = DESIGN_DATA.volumes[0];
  const chars = DESIGN_DATA.characters.slice(0, 3).map((c) => c.name).join(' / ') || '暂无角色';
  const scene = DESIGN_DATA.chapters[0];
  body.innerHTML = '<div class="outline-section"><b>当前卷</b><p>' + escapeHtml(vol ? (vol.title + '：' + vol.subtitle) : '暂无卷纲') + '</p></div>' +
    '<div class="outline-section"><b>角色</b><div>' + escapeHtml(chars) + '</div></div>' +
    '<div class="outline-section"><b>场景目标</b><p>' + escapeHtml(scene ? scene.goal : '暂无场景目标') + '</p></div>';
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

const DESIGN_DATA = {
  volumes: [
    { title: '第一卷', range: '1-60章', subtitle: '灾变初临', summary: '主角在高考考场遭遇末日降临，被迫在混乱中保护同学并觉醒模拟器能力。', tags: ['觉醒','逃亡','校园'] },
    { title: '第二卷', range: '61-120章', subtitle: '废墟秩序', summary: '幸存者小队在废弃商场建立据点，主角通过模拟预判危险，逐步确立领导地位。', tags: ['据点','团体','资源'] },
    { title: '第三卷', range: '121-180章', subtitle: '暗流涌动', summary: '外界势力觊觎据点资源，内部出现分歧，主角面临信任与利益的考验。', tags: ['内讧','权谋','冲突'] },
    { title: '第四卷', range: '181-240章', subtitle: '进化之路', summary: '病毒二次变异，人类与怪物同步进化，主角团队被迫向更危险的城市核心进发。', tags: ['进化','副本','Boss'] },
    { title: '第五卷', range: '241-300章', subtitle: '新纪元', summary: '真相揭露，末日竟是高等文明的筛选试验，主角必须做出拯救还是逃离的抉择。', tags: ['真相','决战','终章'] }
  ],
  chapters: [
    { title: '第一章', goal: '建立末日氛围', conflict: '主角与监考老师对峙', result: '觉醒模拟器，逃离考场', scenes: ['考场混乱','首次模拟','能力觉醒'] },
    { title: '第二章', goal: '展示世界规则', conflict: '如何保护同学突围', result: '组建临时小队', scenes: ['丧尸出现','路线选择','救人'] },
    { title: '第三章', goal: '引入外部压力', conflict: '食物与信任危机', result: '占领小卖部作为据点', scenes: ['物资搜寻','冲突爆发','决策'] }
  ],
  world: {
    core: '末日模拟器：全球进入72小时轮回，每次死亡保留记忆碎片。',
    powers: '模拟点、天赋树、死亡惩罚、情报熵。',
    factions: [
      { name: '黑塔', desc: '神秘组织，掌控轮回核心。' },
      { name: '避难所', desc: '官方幸存者聚集地。' },
      { name: '拾荒者', desc: '游离于秩序之外的幸存者。' },
      { name: '清理人', desc: '黑塔下属的执行部队。' }
    ]
  },
  characters: [
    { name: '林默', role: '主角', desc: '冷静果断，拥有末日模拟器，能在梦中预演未来4小时。' },
    { name: '苏婉', role: '女主', desc: '医学生，擅长急救与毒理分析，团队医疗核心。' },
    { name: '老K', role: '导师', desc: '退役特种兵，传授生存技巧，是主角初期的武力依靠。' }
  ]
};

let designEditType = null;
let designEditIndex = null;

function initDesignEditButtons() {
  $$('.volume-card').forEach((card, idx) => {
    card.onclick = () => openVolumeEdit(idx);
  });
  $$('.chapter-group').forEach((group, idx) => {
    group.onclick = () => openChapterEdit(idx);
  });
  $$('.character-card').forEach((card, idx) => {
    card.onclick = () => openCharacterEdit(idx);
  });
  const worldCore = $('.world-core');
  if (worldCore) worldCore.onclick = () => openWorldEdit();
  renderFactions();
}

function openDesignDrawer(title, bodyHtml) {
  $('#design-edit-title').textContent = title;
  $('#design-edit-body').innerHTML = bodyHtml + '<div class="report-ai-suggestions" id="design-ai-box" style="display:none"></div>';
  $('#design-edit-modal').classList.add('open');
  $('#design-edit-overlay').classList.add('open');
}

function closeDesignEdit() {
  $('#design-edit-modal').classList.remove('open');
  $('#design-edit-overlay').classList.remove('open');
  designEditType = null;
  designEditIndex = null;
}

function openVolumeEdit(idx) {
  designEditType = 'volume';
  designEditIndex = idx;
  const v = DESIGN_DATA.volumes[idx];
  openDesignDrawer('编辑 ' + v.title,
    '<div class="report-detail-field"><label>卷标题</label><input type="text" id="design-edit-title-input" value="' + escapeHtml(v.title || '') + '"></div>' +
    '<div class="report-detail-field"><label>章节范围</label><input type="text" id="design-edit-range" value="' + escapeHtml(v.range || '') + '"></div>' +
    '<div class="report-detail-field"><label>副标题</label><input type="text" id="design-edit-subtitle" value="' + escapeHtml(v.subtitle || '') + '"></div>' +
    '<div class="report-detail-field"><label>摘要</label><textarea id="design-edit-summary">' + escapeHtml(v.summary || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>标签（逗号分隔）</label><input type="text" id="design-edit-tags" value="' + escapeHtml((v.tags || []).join(',')) + '"></div>'
  );
}

function openChapterEdit(idx) {
  designEditType = 'chapter';
  designEditIndex = idx;
  const c = DESIGN_DATA.chapters[idx];
  openDesignDrawer('编辑 ' + c.title,
    '<div class="report-detail-field"><label>目标</label><textarea id="design-edit-goal">' + escapeHtml(c.goal || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>冲突</label><textarea id="design-edit-conflict">' + escapeHtml(c.conflict || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>结果</label><textarea id="design-edit-result">' + escapeHtml(c.result || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>场景（每行一个）</label><textarea id="design-edit-scenes">' + escapeHtml((c.scenes || []).join('\n')) + '</textarea></div>'
  );
}

function openCharacterEdit(idx) {
  designEditType = 'character';
  designEditIndex = idx;
  const c = DESIGN_DATA.characters[idx];
  openDesignDrawer('编辑角色：' + c.name,
    '<div class="report-detail-field"><label>姓名</label><input type="text" id="design-edit-name" value="' + escapeHtml(c.name || '') + '"></div>' +
    '<div class="report-detail-field"><label>身份</label><input type="text" id="design-edit-role" value="' + escapeHtml(c.role || '') + '"></div>' +
    '<div class="report-detail-field"><label>人物小传</label><textarea id="design-edit-desc">' + escapeHtml(c.desc || '') + '</textarea></div>'
  );
}

function openWorldEdit() {
  designEditType = 'world';
  designEditIndex = null;
  const w = DESIGN_DATA.world;
  openDesignDrawer('编辑世界观',
    '<div class="report-detail-field"><label>核心设定</label><textarea id="design-edit-core">' + escapeHtml(w.core || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>能力体系</label><textarea id="design-edit-powers">' + escapeHtml(w.powers || '') + '</textarea></div>'
  );
}

function aiSuggestDesign() {
  const box = $('#design-ai-box');
  if (!box) return;
  box.style.display = 'block';
  let text = '';
  if (designEditType === 'volume') text = '<h4>AI 粗纲建议</h4><ul><li>本卷结尾建议设置一个重大反转，提升追读率。</li><li>每 10 章安排一次小高潮，保持节奏。</li><li>标签可补充“囤货”以贴合末世热门组合。</li></ul>';
  else if (designEditType === 'chapter') text = '<h4>AI 细纲建议</h4><ul><li>冲突部分增加主角与反派的直接对话，提升张力。</li><li>场景切换不要过于频繁，建议控制在 3 个以内。</li><li>结尾留一个未解答的悬念。</li></ul>';
  else if (designEditType === 'character') text = '<h4>AI 角色建议</h4><ul><li>为角色添加一个明显缺陷，使其更立体。</li><li>让角色的过去经历影响当前决策。</li><li>通过对话习惯区分不同角色。</li></ul>';
  else text = '<h4>AI 世界观建议</h4><ul><li>为能力体系设置清晰的限制条件，避免无敌感。</li><li>势力之间应有明确的利益冲突。</li><li>世界观揭示应分阶段放出，保持神秘感。</li></ul>';
  box.innerHTML = text;
}

function saveDesignEdit() {
  if (designEditType === 'volume') {
    const v = DESIGN_DATA.volumes[designEditIndex];
    v.title = $('#design-edit-title-input').value;
    v.range = $('#design-edit-range').value;
    v.subtitle = $('#design-edit-subtitle').value;
    v.summary = $('#design-edit-summary').value;
    v.tags = $('#design-edit-tags').value.split(',').map(t => t.trim()).filter(Boolean);
  } else if (designEditType === 'chapter') {
    const c = DESIGN_DATA.chapters[designEditIndex];
    c.goal = $('#design-edit-goal').value;
    c.conflict = $('#design-edit-conflict').value;
    c.result = $('#design-edit-result').value;
    c.scenes = $('#design-edit-scenes').value.split('\n').map(t => t.trim()).filter(Boolean);
  } else if (designEditType === 'character') {
    const c = DESIGN_DATA.characters[designEditIndex];
    c.name = $('#design-edit-name').value;
    c.role = $('#design-edit-role').value;
    c.desc = $('#design-edit-desc').value;
  } else if (designEditType === 'world') {
    DESIGN_DATA.world.core = $('#design-edit-core').value;
    DESIGN_DATA.world.powers = $('#design-edit-powers').value;
  } else if (designEditType === 'faction') {
    const f = DESIGN_DATA.world.factions[designEditIndex];
    f.name = $('#design-edit-faction-name').value;
    f.desc = $('#design-edit-faction-desc').value;
  }
  renderDesign();
  showToast('已保存');
  closeDesignEdit();
}

function renderFactions() {
  const list = $('#faction-list');
  if (!list) return;
  list.innerHTML = DESIGN_DATA.world.factions.map((f, idx) =>
    '<div class="faction-item" onclick="openFactionEdit(' + idx + ')"><div><b>' + escapeHtml(f.name || '') + '</b><p>' + escapeHtml(f.desc || '') + '</p></div></div>'
  ).join('');
}

function openFactionEdit(idx) {
  designEditType = 'faction';
  designEditIndex = idx;
  const f = DESIGN_DATA.world.factions[idx];
  openDesignDrawer('编辑势力：' + f.name,
    '<div class="report-detail-field"><label>势力名称</label><input type="text" id="design-edit-faction-name" value="' + escapeHtml(f.name || '') + '"></div>' +
    '<div class="report-detail-field"><label>势力描述</label><textarea id="design-edit-faction-desc">' + escapeHtml(f.desc || '') + '</textarea></div>'
  );
}

function renderDesign() {
  $$('.volume-card').forEach((card, idx) => {
    const v = DESIGN_DATA.volumes[idx];
    if (!v) return;
    card.querySelector('.volume-title').textContent = v.title;
    card.querySelector('.volume-range').textContent = v.range;
    card.querySelector('.volume-subtitle').textContent = v.subtitle;
    card.querySelector('.volume-summary').textContent = v.summary;
    card.querySelector('.volume-tags').innerHTML = v.tags.map(t => '<span class="tag">' + t + '</span>').join('');
  });
  $$('.chapter-group').forEach((group, idx) => {
    const c = DESIGN_DATA.chapters[idx];
    if (!c) return;
    group.querySelector('.chapter-header').childNodes[0].textContent = c.title;
    const grid = group.querySelector('.chapter-grid');
    grid.children[0].querySelector('p').textContent = c.goal;
    grid.children[1].querySelector('p').textContent = c.conflict;
    grid.children[2].querySelector('p').textContent = c.result;
    group.querySelector('.scene-list').innerHTML = c.scenes.map(s => '<li>' + s + '</li>').join('');
  });
  $$('.character-card').forEach((card, idx) => {
    const c = DESIGN_DATA.characters[idx];
    if (!c) return;
    card.querySelector('h4').textContent = c.name;
    card.querySelector('.char-role').textContent = c.role;
    card.querySelector('p').textContent = c.desc;
  });
  renderFactions();
  renderOutlinePanel();
}

function fmtNumber(n) {
  if (n >= 100000) return (n / 10000).toFixed(1) + '万';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

function fmtSize(n) {
  if (n >= 1024) return (n / 1024).toFixed(1) + ' MB';
  return n + ' KB';
}

function filterTasks(filter) {
  taskFilter = filter;
  renderTasks();
}

function saveTasks() {
  try {
    localStorage.setItem('xiaoshuo_tasks', JSON.stringify(tasks));
  } catch (e) {}
}

function loadTasks() {
  try {
    const raw = localStorage.getItem('xiaoshuo_tasks');
    if (raw) {
      const saved = JSON.parse(raw);
      if (Array.isArray(saved) && saved.length) {
        tasks = saved;
        // 对未完成的任务恢复轮询
        tasks.forEach((t) => {
          if (t.backendId && t.status !== 'completed' && t.status !== 'failed') {
            pollTaskStatus(t);
          }
        });
        return;
      }
    }
  } catch (e) {}
  tasks = (DATA.tasks || []).slice();
}

function renderTasks() {
  const grid = $('#task-grid');
  if (!grid) return;
  saveTasks();
  const filtered = taskFilter === 'all' ? tasks : tasks.filter((t) => t.status === taskFilter);
  if (filtered.length === 0) {
    grid.innerHTML = '<div class="empty-state">暂无任务</div>';
  } else {
    grid.innerHTML = filtered.map((t) => {
      const retryBtn = t.status === 'failed' ? '<button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();retryTask(\'' + t.id + '\')" style="margin-left:auto">重试</button>' : '';
      return '<div class="task-card">' +
        '<div class="task-header"><span class="task-type">' + t.typeLabel + '</span><span class="task-badge ' + t.status + '">' + statusLabel(t.status) + '</span>' + retryBtn + '</div>' +
        '<div class="task-meta">书籍：' + t.books.slice(0, 2).join('、') + (t.books.length > 2 ? ' 等' + t.books.length + '本' : '') + '</div>' +
        '<div class="task-progress"><div style="width:' + t.progress + '%"></div></div>' +
        '<div class="task-msg">' + t.message + '</div>' +
        '</div>';
    }).join('');
  }
  $$('#task-filter-tabs .filter-tab').forEach((t) => t.classList.toggle('active', t.dataset.filter === taskFilter));
}

function statusLabel(s) {
  return { queued: '排队中', running: '进行中', completed: '已完成', failed: '失败' }[s] || s;
}

function openTaskModal() {
  $('#task-modal').classList.add('open');
  filterTaskBooks();
}

function closeTaskModal() {
  $('#task-modal').classList.remove('open');
}

function closeModalOnOverlay(e) {
  if (e.target === e.currentTarget) closeTaskModal();
}

function renderTaskBookChecklist() {
  const container = $('#task-book-checklist');
  if (!container || !DATA || !DATA.books) return;
  container.innerHTML = DATA.books.map((b, idx) => {
    return '<label class="book-checkbox"><input type="checkbox" class="task-book-check" value="' + idx + '"><span>' + escapeHtml(b.title) + '</span></label>';
  }).join('');
}

function filterTaskBooks() {
  const genre = $('#task-genre').value;
  $$('.book-checkbox').forEach((label) => {
    const input = label.querySelector('input');
    if (!input) return;
    const idx = Number(input.value);
    const book = DATA.books[idx];
    if (!book) { label.style.display = 'none'; return; }
    const show = genre === 'all' || book.genre === genre;
    label.style.display = show ? 'flex' : 'none';
  });
}

function initTaskTypeHandler() {
  const typeSelect = $('#task-type');
  if (!typeSelect) return;
  typeSelect.addEventListener('change', () => {
    const rangeRow = $('#task-range-row');
    if (!rangeRow) return;
    rangeRow.style.display = typeSelect.value === 'rhythm' ? '' : 'none';
  });
}

const TASK_TYPE_LABELS = {
  full_pipeline: '完整管线',
  rhythm: '节奏分析',
  technique: '技法提炼',
  summary: '全文摘要',
  cross: '跨书对比',
  cards: '技法卡片',
  instructions: '逐章指令',
};

function startTask() {
  const type = $('#task-type').value;
  const checked = $$('.task-book-check:checked');
  const selectedBooks = checked.map((c) => DATA.books[Number(c.value)]).filter(Boolean);
  const titles = selectedBooks.map((b) => b.title);
  const files = selectedBooks.map((b) => b.file).filter(Boolean);
  if (selectedBooks.length === 0) {
    showToast('请至少选择一本书');
    return;
  }
  const rangeStart = $('#task-range-start').value || null;
  const rangeEnd = $('#task-range-end').value || null;
  createTask(type, titles, files, rangeStart, rangeEnd);
  closeTaskModal();
  navigate('disassembly');
  showToast('任务已创建');
}

async function createTask(type, titles, files, rangeStart, rangeEnd) {
  const label = TASK_TYPE_LABELS[type] || type;
  const rangeInfo = rangeStart ? ' (第' + rangeStart + '-' + (rangeEnd || '末') + '章)' : '';
  const localTask = {
    id: 'local-' + Date.now(),
    backendId: null,
    type: type,
    typeLabel: label + rangeInfo,
    books: titles,
    _files: files,
    status: 'queued',
    progress: 0,
    message: '排队中...',
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
  };
  tasks.unshift(localTask);
  renderTasks();

  try {
    const resp = await fetch(API_BASE + '/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: type, books: files }),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    localTask.backendId = data.id;
    localTask.status = data.status || 'queued';
    pollTaskStatus(localTask);
  } catch (e) {
    localTask.status = 'failed';
    localTask.message = '提交失败：' + e.message;
    renderTasks();
  }
}

function pollTaskStatus(task) {
  if (!task || !task.backendId) return;
  const interval = setInterval(async () => {
    try {
      const resp = await fetch(API_BASE + '/api/task?id=' + task.backendId);
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      task.status = data.status;
      task.progress = data.progress || 0;
      task.message = data.message || '';
      renderTasks();
      if (data.status === 'completed' || data.status === 'failed') {
        clearInterval(interval);
        if (data.status === 'completed') {
          showToast('任务完成：' + task.typeLabel);
          loadApiData();
        }
      }
    } catch (e) {
      task.status = 'failed';
      task.message = '轮询失败：' + e.message;
      renderTasks();
      clearInterval(interval);
    }
  }, 1500);
}

function updateWordCount() {
  const text = $('#editor-textarea').value || '';
  const count = text.replace(/\s/g, '').length;
  const target = 2000;
  $('#editor-word-count').textContent = count + ' / ' + target + ' 字';
  markDraftUnsaved();
}

function markDraftUnsaved() {
  const el = $('#writing-save-status');
  if (el) el.textContent = '未保存';
}

function markDraftSaved() {
  const el = $('#writing-save-status');
  if (el) el.textContent = '已保存';
}

function retryTask(taskId) {
  const task = tasks.find(t => t.id === taskId);
  if (!task) return;
  task.status = 'queued';
  task.progress = 0;
  task.message = '排队中...';
  task.backendId = null;
  renderTasks();
  createTask(task.type, task.books, task._files || [], null, null);
  showToast('任务已重新排队');
}

function navigateTo(page) {
  navigate(page);
}

function refreshReports() {
  showToast('报告已刷新');
  loadApiData();
}

let projects = [];

function loadProjects() {
  try {
    const raw = localStorage.getItem('projects');
    projects = raw ? JSON.parse(raw) : [];
  } catch (e) { projects = []; }
}

function switchProject(index) {
  const idx = parseInt(index);
  if (isNaN(idx) || idx < 0 || idx >= projects.length) return;
  currentProject = projects[idx];
  localStorage.setItem('current_project', JSON.stringify(currentProject));
  showToast('已切换到 ' + currentProject.title);
  renderDashboardProject();
  populateProjectSwitcher();
}

function populateProjectSwitcher() {
  loadProjects();
  const select = $('#project-select');
  if (!select) return;
  select.innerHTML = '<option value="">切换作品</option>' +
    projects.map((p, i) => '<option value="' + i + '"' + (currentProject && p.title === currentProject.title ? ' selected' : '') + '>' + p.title + '</option>').join('');
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
  const hint = $('#deai-hint');
  if (hint) hint.classList.toggle('show', deAiEnabled);
  if (deAiEnabled) {
    const text = $('#editor-textarea').value || '';
    const aiPatterns = [/首先.*其次.*最后/, /不得不说/, /众所周知/, /总而言之/, /综上所述/];
    const found = aiPatterns.filter(p => p.test(text));
    const msg = found.length > 0 ? '去AI味已开启 - 检测到 ' + found.length + ' 处疑似AI痕迹' : '去AI味已开启 - 未检测到明显AI痕迹';
    showToast(msg);
  } else {
    showToast('去AI味已关闭');
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
  $('#focus-ai-panel').classList.remove('open');
}

function togglePanel(id) {
  const panel = $('#' + id + '-panel');
  if (panel) panel.classList.toggle('collapsed');
}

// ============================================================
// 逐章指令面板 — 加载真实后端指令数据
// ============================================================
let instructionsLoaded = false;

async function initInstructionsPanel() {
  if (instructionsLoaded) return;
  const panel = $('#instructions-panel');
  if (!panel) return;
  panel.style.display = '';

  // 填充可选参考书列表
  try {
    const resp = await fetch(API_BASE + '/api/instructions');
    const data = await resp.json();
    const select = $('#instr-book-select');
    if (select && data.books && data.books.length) {
      select.innerHTML = '<option value="">选择参考书</option>' +
        data.books.map(b => '<option value="' + escapeHtml(b.name || '') + '">' + escapeHtml(b.name || '') + '</option>').join('');
      instructionsLoaded = true;
    } else if (select) {
      select.innerHTML = '<option value="">暂无参考书指令</option>';
    }
  } catch (e) {
    // 无 API 可用，保持面板隐藏
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

function saveDraft() {
  const title = $('#editor-title').value || '';
  const content = $('#editor-textarea').value || '';
  try {
    localStorage.setItem('draft_title', title);
    localStorage.setItem('draft_content', content);
    localStorage.setItem('draft_saved_at', new Date().toISOString());
  } catch (e) {}
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

function showToast(msg) {
  const container = $('#toast-container');
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => { t.remove(); }, 2500);
}

function showDesign(name) {
  $$('.design-pane').forEach((p) => p.classList.remove('active'));
  const target = $('#design-' + name);
  if (target) target.classList.add('active');
  $$('.subnav-item').forEach((s) => s.classList.toggle('active', s.dataset.sub === name));
}

function toggleMobileSidebar() {
  appShell.classList.toggle('mobile-sidebar-open');
}

function closeMobileSidebar() {
  appShell.classList.remove('mobile-sidebar-open');
}

document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && document.body.classList.contains('focus-mode')) {
    document.body.classList.remove('focus-mode');
    const btn = $('#focus-toggle');
    if (btn) btn.textContent = '专注模式';
    closeFocusAiPanel();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if ($('#focus-ai-panel').classList.contains('open')) {
      closeFocusAiPanel();
      return;
    }
    if (document.body.classList.contains('focus-mode')) {
      toggleFocus();
      return;
    }
    if ($('#create-project-modal').classList.contains('open')) {
      closeCreateProjectModal();
      return;
    }
    closeReportDetail();
    closeTaskModal();
    closeDetail();
    closeMobileSidebar();
  }
  if (e.ctrlKey && e.key.toLowerCase() === 's') {
    e.preventDefault();
    saveDraft();
  }
  if (e.ctrlKey && e.key.toLowerCase() === 'b') {
    e.preventDefault();
    toggleFocus();
  }
  if (e.ctrlKey && e.shiftKey && e.key === 'C') {
    e.preventDefault();
    togglePanel('self-check');
  }
});

init();

