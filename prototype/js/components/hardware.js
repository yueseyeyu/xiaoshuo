const HW_THRESHOLDS = {
  gpu: { warn: 75, danger: 85 },
  vram: { warn: 80, danger: 90 },
  cpu: { warn: 80, danger: 92 },
  ram: { warn: 85, danger: 94 },
  power: { warn: 80, danger: 95 },  // GPU 利用率
};
const HW_POLL_INTERVAL = 5000;  // 硬件轮询间隔 (ms)
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
  } else {
    console.warn('[HW] 硬件数据获取失败:', error);
  }
}
async function fetchModelInfo() {
  const { ok, data, error } = await apiGet('/api/model-info');
  if (!ok || !data) {
    console.warn('[HW] 模型信息获取失败:', error);
    return;
  }
  const dashName = $('#dash-model-name');
  const dashStatus = $('#dash-model-status');
  const modelName = $('#model-name');
  const modelMeta = $('#model-meta');
  if (dashName) dashName.textContent = data.name;
  if (dashStatus) {
    dashStatus.textContent = data.status === 'running' ? '在线' : '离线';
    const modelEl = dashStatus.parentElement;
    if (modelEl) {
      modelEl.classList.remove('warn', 'danger');
      if (data.status !== 'running') modelEl.classList.add('danger');
    }
  }
  if (modelName) modelName.textContent = data.name;
  if (modelMeta) {
    modelMeta.textContent = `ctx ${data.n_ctx} · ${data.quant} · localhost:${data.port}`;
  }
}

function initHardwareMonitor() {
  renderHardwareMonitor();
  renderHardwarePageGauges();
  if (hwInterval) clearInterval(hwInterval);
  fetchHardwareMetrics();  // 立即获取一次
  fetchModelInfo();        // 获取模型信息
  hwInterval = setInterval(fetchHardwareMetrics, HW_POLL_INTERVAL);
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
