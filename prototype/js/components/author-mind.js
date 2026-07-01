"use strict";

// ============================================================
// 作者心智模型面板 — 决策直觉引擎
// 对接后端: /api/creative/authors/*, /api/creative/decision/*
// ============================================================

let presetAuthors = [];
let selectedAuthorForDetail = null;

async function loadPresetAuthors() {
  const { ok, data } = await apiGet('/api/creative/authors/presets');
  if (ok && data) {
    presetAuthors = data.authors || [];
  }
  return presetAuthors;
}

async function loadAuthorDetail(authorName) {
  const { ok, data } = await apiGet('/api/creative/authors/' + encodeURIComponent(authorName));
  return ok ? data : null;
}

async function generateDecisionOptions(scenario, authors) {
  const body = { scenario: scenario, authors: authors || null, context: null };
  const { ok, data } = await apiPost('/api/creative/decision/options', body, 30000);
  return ok ? data : null;
}

async function recordDecisionChoice(scenario, chosenAuthor, allOptions) {
  const body = { scenario: scenario, chosen_author: chosenAuthor, all_options: allOptions || null };
  const { ok } = await apiPost('/api/creative/decision/record', body);
  return ok;
}

function renderAuthorMindPanel() {
  var container = $('#author-mind-panel');
  if (!container) return;
  container.innerHTML = 
    '<div class="amind-layout">' +
      '<div class="amind-left">' +
        '<div class="amind-section-title">预设作者心智模型</div>' +
        '<div class="amind-author-list" id="amind-author-list">' +
          '<div class="text-muted" style="padding:8px;">加载中...</div>' +
        '</div>' +
      '</div>' +
      '<div class="amind-right">' +
        '<div class="amind-detail" id="amind-detail">' +
          '<div class="text-muted" style="padding:16px;text-align:center;">选择左侧作者查看心智模型</div>' +
        '</div>' +
        '<div class="amind-divider"></div>' +
        '<div class="amind-decision-section">' +
          '<div class="amind-section-title">决策直觉引擎</div>' +
          '<div class="amind-decision-input">' +
            '<textarea id="amind-scenario-input" placeholder="输入创作场景，如：主角面对强敌，实力差距悬殊" rows="3"></textarea>' +
            '<button class="btn btn-primary" onclick="runDecisionEngine()" id="amind-run-btn">生成决策选项</button>' +
          '</div>' +
          '<div class="amind-decision-results" id="amind-decision-results"></div>' +
        '</div>' +
      '</div>' +
    '</div>';
  initAuthorMindPanel();
}

async function initAuthorMindPanel() {
  await loadPresetAuthors();
  var listEl = $('#amind-author-list');
  if (!listEl) return;
  if (presetAuthors.length === 0) {
    listEl.innerHTML = '<div class="text-muted" style="padding:8px;">暂无预设作者</div>';
    return;
  }
  listEl.innerHTML = presetAuthors.map(function(a) {
    return '<div class="amind-author-card" onclick="selectAuthorMind(\'' + escapeHtml(a.name) + '\')" data-author="' + escapeHtml(a.name) + '">' +
      '<div class="amind-author-avatar">' + escapeHtml(a.name[0]) + '</div>' +
      '<div class="amind-author-info">' +
        '<div class="amind-author-name">' + escapeHtml(a.name) + '</div>' +
        '<div class="amind-author-style">' + escapeHtml(a.style || '') + '</div>' +
        (a.representative_works && a.representative_works.length ?
          '<div class="amind-author-works">' + a.representative_works.map(function(w) { return '<span class="tag">' + escapeHtml(w) + '</span>'; }).join('') + '</div>' : '') +
      '</div>' +
    '</div>';
  }).join('');
}

async function selectAuthorMind(authorName) {
  selectedAuthorForDetail = authorName;
  $$('.amind-author-card').forEach(function(c) {
    c.classList.toggle('active', c.dataset.author === authorName);
  });
  var detailEl = $('#amind-detail');
  if (!detailEl) return;
  detailEl.innerHTML = '<div class="text-muted" style="padding:16px;">加载中...</div>';
  var data = await loadAuthorDetail(authorName);
  if (!data) {
    detailEl.innerHTML = '<div class="text-muted" style="padding:16px;">加载失败</div>';
    return;
  }
  var fw = data.framework || {};
  detailEl.innerHTML = 
    '<div class="amind-detail-header">' +
      '<div class="amind-detail-name">' + escapeHtml(authorName) + '</div>' +
      '<div class="amind-detail-works">' + (data.representative_works || []).map(function(w) { return '<span class="tag">' + escapeHtml(w) + '</span>'; }).join('') + '</div>' +
    '</div>' +
    '<div class="amind-framework-grid">' +
      renderFrameworkItem('故事结构', fw.structure, fw.structure_detail) +
      renderFrameworkItem('爽点逻辑', fw.pleasure_logic, fw.pleasure_detail) +
      renderFrameworkItem('节奏方法论', fw.rhythm_method, fw.rhythm_detail) +
      renderFrameworkItem('人物塑造', fw.characterization, fw.characterization_detail) +
      renderFrameworkItem('冲突风格', fw.conflict_style, fw.conflict_detail) +
      renderFrameworkItem('世界观构建', fw.worldbuilding, fw.worldbuilding_detail) +
    '</div>' +
    (data.signature_techniques && data.signature_techniques.length ?
      '<div class="amind-subsection"><b>标志性技法</b><ul class="amind-tech-list">' +
      data.signature_techniques.map(function(t) {
        return '<li>' + escapeHtml(t.technique || t.name || JSON.stringify(t)) + (t.desc ? ' — ' + escapeHtml(t.desc) : '') + '</li>';
      }).join('') + '</ul></div>' : '') +
    (data.craft_notes && data.craft_notes.length ?
      '<div class="amind-subsection"><b>创作谈</b><ul class="amind-notes-list">' +
      data.craft_notes.map(function(n) { return '<li>' + escapeHtml(n) + '</li>'; }).join('') + '</ul></div>' : '');
}

function renderFrameworkItem(label, value, detail) {
  if (!value) return '';
  return '<div class="amind-fw-item">' +
    '<div class="amind-fw-label">' + escapeHtml(label) + '</div>' +
    '<div class="amind-fw-value">' + escapeHtml(value) + '</div>' +
    (detail ? '<div class="amind-fw-detail">' + escapeHtml(detail) + '</div>' : '') +
  '</div>';
}

async function runDecisionEngine() {
  var scenario = $('#amind-scenario-input').value.trim();
  if (!scenario) {
    showToast('请输入创作场景');
    return;
  }
  var resultsEl = $('#amind-decision-results');
  var btn = $('#amind-run-btn');
  if (resultsEl) resultsEl.innerHTML = '<div class="text-muted" style="padding:8px;">正在生成决策选项...</div>';
  if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

  var authors = presetAuthors.slice(0, 5).map(function(a) { return a.name; });
  var data = await generateDecisionOptions(scenario, authors);

  if (btn) { btn.disabled = false; btn.textContent = '生成决策选项'; }
  if (!data || !data.options || data.options.length === 0) {
    if (resultsEl) resultsEl.innerHTML = '<div class="text-muted" style="padding:8px;">未生成有效选项</div>';
    return;
  }

  window._currentDecisionOptions = data.options;
  if (resultsEl) {
    resultsEl.innerHTML = '<div class="amind-options-list">' +
      data.options.map(function(opt, i) {
        var o = opt;
        if (typeof opt === 'string') { try { o = JSON.parse(opt); } catch(e) { o = { author: '?', choice: opt }; } }
        return '<div class="amind-option-card" data-idx="' + i + '">' +
          '<div class="amind-option-header">' +
            '<span class="amind-option-author">' + escapeHtml(o.author || '?') + '</span>' +
            '<button class="btn btn-secondary btn-sm" onclick="chooseDecisionOption(' + i + ')">采用此方案</button>' +
          '</div>' +
          '<div class="amind-option-choice">' + escapeHtml(o.choice || '') + '</div>' +
          (o.reasoning ? '<div class="amind-option-reasoning">' + escapeHtml(o.reasoning) + '</div>' : '') +
          (o.risk ? '<div class="amind-option-risk">风险：' + escapeHtml(o.risk) + '</div>' : '') +
        '</div>';
      }).join('') +
    '</div>';
  }
}

async function chooseDecisionOption(idx) {
  var options = window._currentDecisionOptions || [];
  var opt = options[idx];
  if (!opt) return;
  var scenario = $('#amind-scenario-input').value.trim();
  var authorName = opt.author || '';
  await recordDecisionChoice(scenario, authorName, options);
  showToast('已采用 ' + authorName + ' 的方案，决策已记录');
  $$('.amind-option-card').forEach(function(c, i) {
    c.classList.toggle('chosen', i === idx);
  });
}
