"use strict";

// ============================================================
// 工具函数
// ============================================================

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const GENRE_PALETTES = {
  '末世': ['#7F1D1D', '#991B1B', '#B91C1C'],
  '仙侠': ['#064E3B', '#065F46', '#047857'],
  '科幻': ['#1E3A8A', '#1E40AF', '#1D4ED8'],
  '无限流': ['#581C87', '#6B21A8', '#7E22CE'],
  '历史': ['#78350F', '#92400E', '#B45309'],
  '悬疑': ['#1E293B', '#273649', '#334155'],
  '奇幻': ['#701A75', '#86198F', '#A21CAF'],
  '洪荒': ['#713F12', '#854D0E', '#A16207'],
  '都市': ['#1E3A5F', '#1E4A70', '#1E5B80'],
  '同人': ['#4C1D95', '#5B21B6', '#6D28D9'],
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
  const palette = GENRE_PALETTES[genre] || ['#1F2937'];
  const idx = title ? (hashString(title) % palette.length) : 0;
  return palette[idx];
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
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

function timeAgo(date) {
  const now = new Date();
  const diff = Math.floor((now - date) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
  const hours = Math.floor(diff / 3600);
  if (hours < 24) return hours + '小时前';
  const target = new Date(date);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetDay = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const dayDiff = Math.floor((today - targetDay) / (24 * 3600 * 1000));
  const hh = String(target.getHours()).padStart(2, '0');
  const mm = String(target.getMinutes()).padStart(2, '0');
  if (dayDiff === 1) return '昨天 ' + hh + ':' + mm;
  if (dayDiff === 2) return '前天 ' + hh + ':' + mm;
  return (target.getMonth() + 1) + '月' + target.getDate() + '日 ' + hh + ':' + mm;
}

function greetingByHour() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

function showToast(msg) {
  const container = $('#toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => { t.remove(); }, 2500);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
