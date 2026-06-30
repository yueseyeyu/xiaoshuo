"use strict";

const HW_THRESHOLDS = {
  gpu: { warn: 75, danger: 85 },
  vram: { warn: 80, danger: 90 },
  cpu: { warn: 80, danger: 92 },
  ram: { warn: 85, danger: 94 },
  power: { warn: 80, danger: 95 },  // GPU 利用率
};
const HW_POLL_INTERVAL = 10000;  // 硬件轮询间隔 (ms)，降低频率避免多标签页压垮后端
let hwMetrics = { gpu: 0, vram: 0, cpu: 0, ram: 0, power: 0 };
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
  if (key === 'power') return value + '%';  // GPU 利用率
  if (key === 'vram' || key === 'ram') return value + '%';  // 显存/内存
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

}
function renderHardwarePageGauges() {
  const rootStyle = getComputedStyle(document.documentElement);
  const colorMap = {
    normal: rootStyle.getPropertyValue('--success').trim(),
    warn: rootStyle.getPropertyValue('--warning').trim(),
    danger: rootStyle.getPropertyValue('--danger').trim(),
  };
  const bgColor = rootStyle.getPropertyValue('--bg').trim();
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
    const color = colorMap[status];
    card.classList.remove('status-normal', 'status-warn', 'status-danger');
    card.classList.add('status-' + status);
    card.style.setProperty('--gauge-color', color);

    const valueEl = $('#gauge-' + key + '-value');
    if (valueEl) {
      valueEl.textContent = formatHwValue(key, value);
      valueEl.style.color = color;
    }

    if (conf.type === 'ring') {
      const ring = card.querySelector('.gauge');
      if (ring) {
        ring.style.setProperty('--p', pct);
        ring.style.background = 'conic-gradient(' + color + ' calc(var(--p) * 1%), ' + bgColor + ' 0)';
      }
      const statusEl = $('#gauge-' + key + '-status');
      if (statusEl) {
        statusEl.classList.remove('normal', 'warn', 'danger');
        statusEl.classList.add(status);
        statusEl.textContent = status === 'normal' ? '正常' : (status === 'warn' ? '注意' : '告警');
      }
    } else {
      const bar = $('#gauge-' + key + '-bar');
      if (bar) {
        bar.style.width = pct + '%';
        bar.style.backgroundColor = color;
      }
    }
  }
}
async function fetchHardwareMetrics() {
  const { ok, data, error } = await apiGet('/api/hardware');
  if (ok && data && data.gpu && data.cpu && data.ram) {
    hwMetrics.gpu = data.gpu.temp || 0;
    hwMetrics.vram = data.gpu.vram_pct || 0;
    hwMetrics.cpu = data.cpu.pct || 0;
    hwMetrics.ram = data.ram.pct || 0;
    hwMetrics.power = data.gpu.util || 0;  // 用GPU利用率替代功耗
    renderHardwareMonitor();
    renderHardwarePageGauges();
    renderVramBreakdown(data.gpu);  // 更新显存分配详情
  } else {
    console.warn('[HW] 硬件数据获取失败:', error);
  }
}
// v8.3: 模型状态由 main.js 全局状态统一管理，硬件页面仅触发一次渲染同步
function syncModelStatusToHardware() {
  if (typeof window.renderModelStatusUI === 'function') {
    window.renderModelStatusUI();
  }
}

function renderVramBreakdown(gpuData) {
  const usedMb = gpuData.vram_used_mb || 0;
  const totalMb = gpuData.vram_total_mb || 0;
  if (!totalMb) return;
  const freeMb = Math.max(0, totalMb - usedMb);
  const usedPct = (usedMb / totalMb * 100).toFixed(1);
  const freePct = (freeMb / totalMb * 100).toFixed(1);
  const usedGb = (usedMb / 1024).toFixed(1);
  const freeGb = (freeMb / 1024).toFixed(1);
  const totalGb = (totalMb / 1024).toFixed(1);

  const fillEl = $('#vram-progress-fill');
  if (fillEl) fillEl.style.width = Math.max(usedPct, 2) + '%';

  const usedLabel = $('#vram-progress-used');
  const freeLabel = $('#vram-progress-free');
  if (usedLabel) usedLabel.textContent = `已用 ${usedGb}GB`;
  if (freeLabel) freeLabel.textContent = `空闲 ${freeGb}GB`;

  const totalTop = $('#vram-stat-total');
  const totalCard = $('#vram-stat-total2');
  if (totalTop) totalTop.textContent = `${totalGb}GB`;
  if (totalCard) totalCard.textContent = `${totalGb}GB`;

  const usedValue = $('#vram-stat-used');
  const usedPctEl = $('#vram-stat-used-pct');
  if (usedValue) usedValue.textContent = `${usedGb}GB`;
  if (usedPctEl) usedPctEl.textContent = `${usedPct}%`;

  const freeValue = $('#vram-stat-free');
  const freePctEl = $('#vram-stat-free-pct');
  if (freeValue) freeValue.textContent = `${freeGb}GB`;
  if (freePctEl) freePctEl.textContent = `${freePct}%`;

  // 根据占用率调整颜色：>=90% 危险，>=80% 警告
  const grid = $('#vram-stats-grid');
  if (grid) {
    grid.classList.remove('danger', 'warn');
    if (usedPct >= 90) grid.classList.add('danger');
    else if (usedPct >= 80) grid.classList.add('warn');
  }
}

function initHardwareMonitor() {
  renderHardwareMonitor();
  renderHardwarePageGauges();
  syncModelStatusToHardware();             // v8.3: 从全局模型状态同步一次
  if (hwInterval) clearInterval(hwInterval);
  setTimeout(fetchHardwareMetrics, 300);  // 延迟避免初始化竞态
  hwInterval = setInterval(fetchHardwareMetrics, HW_POLL_INTERVAL);
  // 页面不可见时暂停轮询，减少多标签页压力
  if (!document._hwVisibilityBound) {
    document._hwVisibilityBound = true;
    document.addEventListener('visibilitychange', function() {
      if (document.hidden) {
        if (hwInterval) clearInterval(hwInterval);
        hwInterval = null;
      } else {
        fetchHardwareMetrics();
        if (!hwInterval) hwInterval = setInterval(fetchHardwareMetrics, HW_POLL_INTERVAL);
      }
    });
  }
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
function refreshHardware() {
  showToast('硬件状态已刷新');
  fetchHardwareMetrics();
}
