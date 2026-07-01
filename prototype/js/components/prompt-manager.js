"use strict";

// ============================================================
// 提示词模板管理面板 — 缓存优化可视化
// 对接后端: /api/creative/prompt-templates/*
// ============================================================

let promptTemplates = [];
let promptCacheStats = {};

async function loadPromptTemplates() {
  var { ok, data } = await apiGet('/api/creative/prompt-templates');
  if (ok && data) {
    promptTemplates = data.templates || [];
    promptCacheStats = data.cache_stats || {};
  }
  return { templates: promptTemplates, stats: promptCacheStats };
}

async function loadPromptTemplateDetail(taskType) {
  var { ok, data } = await apiGet('/api/creative/prompt-templates/' + encodeURIComponent(taskType));
  return ok ? data : null;
}

async function loadCostSavings() {
  var { ok, data } = await apiGet('/api/creative/prompt-templates/cost-savings');
  return ok ? data : null;
}

function renderPromptManagerPanel() {
  var container = $('#prompt-manager-panel');
  if (!container) return;
  container.innerHTML = '<div class="text-muted" style="padding:12px;">加载中...</div>';
  initPromptManager();
}

async function initPromptManager() {
  await loadPromptTemplates();
  var container = $('#prompt-manager-panel');
  if (!container) return;

  var totalCalls = 0;
  var totalHits = 0;
  Object.values(promptCacheStats).forEach(function(s) {
    totalCalls += (s.calls || 0);
    totalHits += Math.round((s.calls || 0) * (s.estimated_cache_hit_rate || 0));
  });
  var overallRate = totalCalls > 0 ? Math.round(totalHits / totalCalls * 100) : 0;

  var savings = await loadCostSavings();

  container.innerHTML = 
    '<div class="pm-overview">' +
      '<div class="pm-stat-card">' +
        '<div class="pm-stat-value">' + promptTemplates.length + '</div>' +
        '<div class="pm-stat-label">已注册模板</div>' +
      '</div>' +
      '<div class="pm-stat-card">' +
        '<div class="pm-stat-value">' + overallRate + '%</div>' +
        '<div class="pm-stat-label">缓存命中率</div>' +
      '</div>' +
      '<div class="pm-stat-card">' +
        '<div class="pm-stat-value">' + totalCalls + '</div>' +
        '<div class="pm-stat-label">总调用次数</div>' +
      '</div>' +
      (savings && savings.estimated_savings ?
        '<div class="pm-stat-card highlight">' +
          '<div class="pm-stat-value">¥' + savings.estimated_savings.toFixed(2) + '</div>' +
          '<div class="pm-stat-label">预估节省</div>' +
        '</div>' : '') +
    '</div>' +
    '<div class="pm-template-list" id="pm-template-list">' +
      promptTemplates.map(function(t) {
        var stat = promptCacheStats[t.task_type] || {};
        var rate = stat.estimated_cache_hit_rate ? Math.round(stat.estimated_cache_hit_rate * 100) : 0;
        return '<div class="pm-template-card" onclick="openPromptTemplateDetail(\'' + escapeHtml(t.task_type) + '\')">' +
          '<div class="pm-template-header">' +
            '<div class="pm-template-type">' + escapeHtml(t.task_type) + '</div>' +
            '<div class="pm-template-rate ' + (rate >= 80 ? 'good' : (rate >= 50 ? 'ok' : 'bad')) + '">' + rate + '%</div>' +
          '</div>' +
          '<div class="pm-template-desc">' + escapeHtml(t.description || '') + '</div>' +
          '<div class="pm-template-meta">' +
            '<span>' + (stat.calls || 0) + ' 次调用</span>' +
            '<span>System Prompt: ' + (t.system_prompt_length || 0) + ' 字符</span>' +
            '<span class="pm-hash">' + escapeHtml(t.system_prompt_hash || '') + '</span>' +
          '</div>' +
          '<div class="pm-template-preview">' + escapeHtml(t.system_prompt_preview || '') + '</div>' +
        '</div>';
      }).join('') +
    '</div>';
}

async function openPromptTemplateDetail(taskType) {
  var modal = $('#prompt-detail-modal');
  var body = $('#prompt-detail-modal-body');
  var title = $('#prompt-detail-modal-title');
  if (!modal || !body) return;
  if (title) title.textContent = '提示词模板: ' + taskType;
  body.innerHTML = '<div class="text-muted" style="padding:16px;">加载中...</div>';
  modal.classList.add('open');

  var data = await loadPromptTemplateDetail(taskType);
  if (!data) {
    body.innerHTML = '<div class="text-muted" style="padding:16px;">加载失败</div>';
    return;
  }

  body.innerHTML = 
    '<div class="pm-detail-section">' +
      '<div class="pm-detail-label">任务类型</div>' +
      '<div class="pm-detail-value">' + escapeHtml(data.task_type) + '</div>' +
    '</div>' +
    (data.description ? '<div class="pm-detail-section"><div class="pm-detail-label">描述</div><div class="pm-detail-value">' + escapeHtml(data.description) + '</div></div>' : '') +
    '<div class="pm-detail-section">' +
      '<div class="pm-detail-label">System Prompt (固定，用于缓存命中)</div>' +
      '<pre class="pm-detail-code">' + escapeHtml(data.system_prompt || '') + '</pre>' +
    '</div>' +
    '<div class="pm-detail-section">' +
      '<div class="pm-detail-label">User Template (变量注入)</div>' +
      '<pre class="pm-detail-code">' + escapeHtml(data.user_template || '') + '</pre>' +
    '</div>' +
    '<div class="pm-detail-meta">' +
      '<div>System Prompt Hash: <code>' + escapeHtml(data.system_prompt_hash || '') + '</code></div>' +
      '<div>System Prompt 长度: ' + (data.system_prompt || '').length + ' 字符</div>' +
    '</div>';
}

function closePromptDetailModal() {
  var modal = $('#prompt-detail-modal');
  if (modal) modal.classList.remove('open');
}
