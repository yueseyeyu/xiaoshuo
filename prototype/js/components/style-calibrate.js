"use strict";

// ============================================================
// 风格校准面板 — 调用后端风格规则 API
// ============================================================
async function calibrateStyle() {
  const status = $('#style-calibrate-status');
  if (status) status.textContent = '校准中...';
  const editor = $('#editor-textarea');
  const body = {
    chapter_id: WRITING_CURRENT_CHAPTER || 127,
    text: editor ? editor.value : '',
    version: ''
  };
  const { ok, data } = await apiPost('/api/style/calibrate', body);
  if (ok && data && data.ok) {
    if (status) status.textContent = '累积 ' + (data.rule_count || 0) + ' 条风格规则';
    renderStyleRules(data.rules || []);
  } else {
    const msg = (data && data.error) ? data.error : '未知错误';
    if (status) status.textContent = '校准失败: ' + msg;
    console.error('[StyleCalibrate] 校准失败', msg);
  }
}

async function loadStyleRules() {
  const status = $('#style-calibrate-status');
  const { ok, data, error } = await apiGet('/api/style/rules');
  if (ok && data && data.ok) {
    if (status) status.textContent = '累积 ' + (data.rule_count || 0) + ' 条风格规则';
    renderStyleRules(data.rules || []);
  } else {
    console.error('[StyleCalibrate] 加载规则失败', error);
    if (status) status.textContent = '后端未连接';
  }
}

function renderStyleRules(rules) {
  const container = $('#style-calibrate-rules');
  if (!container) return;
  if (!rules || rules.length === 0) {
    container.innerHTML = '<div class="style-calibrate-empty">暂无规则，完成 S3 评审后自动积累</div>';
    return;
  }
  container.innerHTML = rules.map(function(r) {
    return '<div class="style-rule-item">' +
      '<span class="style-rule-dim">[' + escapeHtml(r.dimension || '') + ']</span> ' +
      '<span class="style-rule-text">' + escapeHtml(r.rule || '') + '</span>' +
      '<span class="style-rule-weight">x' + (r.weight || 0) + '</span>' +
    '</div>';
  }).join('');
}
