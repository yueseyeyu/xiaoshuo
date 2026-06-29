"use strict";

// ============================================================
// 全局状态管理 — SSOT (Single Source of Truth)
// 所有组件通过此文件访问全局状态，禁止在其他文件中声明同名变量
// ============================================================

// ── 应用级全局变量 ──
let DATA = null;
let tasks = [];
let disassemblyData = null;
let currentTheme = 'midnight';
let currentGenre = '全部';
let taskFilter = 'all';
let selectedBookIndex = null;
let deAiEnabled = false;
let currentProject = null;
let currentLibraryView = 'list';
let librarySort = { key: 'score', dir: 'desc' };
let selectedBookIds = new Set();
let accentPresets = [];
let currentAccentId = null;

// ── 主题/品牌色预设 ──
const THEME_ORDER = ['midnight', 'light', 'obsidian'];
const ACCENT_PRESETS = [
  { id: 'serene',   name: '静谧蓝', accent: '#38BDF8', accentRgb: '56,189,248' },
  { id: 'arctic',   name: '极光青', accent: '#22D3EE', accentRgb: '34,211,238' },
  { id: 'lavender', name: '薰衣紫', accent: '#A78BFA', accentRgb: '167,139,250' },
  { id: 'aurora',   name: '极光靛', accent: '#818CF8', accentRgb: '129,140,248' },
];

// ── 内部状态（逐步迁移到此处） ──
const appState = {
  apiData: {
    stats: null,
    guidance: null,
    techniques: null,
    instructions: null,
    diagnosis: null,
    skeleton: null,
    ready: false,
  },
  hwMetrics: { gpu: 0, vram: 0, cpu: 0, ram: 0, power: 0 },
  hwInterval: null,
  logsCurrentPage: 0,
  logsTotalCount: 0,
  importedReportData: null,
  projectData: null,
  currentBook: null,
  writingCurrentChapter: 127,
  instructionsLoaded: false,
  editorHistory: [],
  editorHistoryIndex: -1,
  focusMode: false,
  aiCompareVisible: false,
  writingSidebarCollapsed: false,
  writingMoreOpen: false,
};

// ── 轮询/定时器注册表 ──
const appIntervals = new Set();
const appPolls = new Set();
function registerInterval(id) { appIntervals.add(id); return id; }
function clearAppIntervals() { appIntervals.forEach(clearInterval); appIntervals.clear(); }
function registerPoll(cancelFn) { appPolls.add(cancelFn); return cancelFn; }
function clearAppPolls() { appPolls.forEach((c) => c()); appPolls.clear(); }

window.addEventListener('beforeunload', () => {
  clearAppIntervals();
  clearAppPolls();
});