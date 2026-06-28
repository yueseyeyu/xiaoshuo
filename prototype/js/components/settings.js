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
  const { ok, data: cfg } = await apiGet('/api/config');
  if (!ok || !cfg) {
    console.log('[Settings] 无法加载后端配置');
    return;
  }
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
