"use strict";

// ============================================================
// 章节目标门控面板 — 5条硬性完成标准验证
// 对接后端: /api/creative/goal-gate/*
// ============================================================

let goalGateResult = null;

async function verifyChapterGoal(chapterText, chapterNum) {
  if (!chapterText || chapterText.trim().length < 100) {
    showToast('章节内容太少，至少需要 100 字');
    return null;
  }
  chapterNum = chapterNum || (typeof WRITING_CURRENT_CHAPTER !== 'undefined' ? WRITING_CURRENT_CHAPTER : 1);
  var body = {
    chapter_text: chapterText,
    chapter_num: chapterNum,
    target_chars: [2000, 5000],
    min_pleasure_points: 1,
    emotion_curve_template: 'rising',
    require_canon_check: false,
    min_s3_score: 0,
    context: null,
  };
  var { ok, data, error } = await apiPost('/api/creative/goal-gate/verify', body, 30000);
  if (ok && data) {
    goalGateResult = data;
    renderGoalGateResult(data);
    return data;
  }
  console.error('[GoalGate] 验证失败', error);
  showToast('目标验证失败: ' + (error || '未知错误'));
  return null;
}

function renderGoalGateResult(data) {
  var panel = $('#goal-gate-panel');
  if (!panel) return;
  if (!data) {
    panel.innerHTML = '<div class="text-muted" style="padding:12px;">点击"验证完成标准"检查章节质量</div>';
    return;
  }

  var passed = data.result === 'pass';
  var conditions = data.conditions || [];
  var failedCount = conditions.filter(function(c) { return !c.passed; }).length;

  panel.innerHTML = 
    '<div class="gg-result ' + (passed ? 'gg-pass' : 'gg-fail') + '">' +
      '<div class="gg-result-icon">' + (passed ? '✓' : '✗') + '</div>' +
      '<div class="gg-result-info">' +
        '<div class="gg-result-title">' + (passed ? '章节通过验证' : '未通过验证') + '</div>' +
        '<div class="gg-result-meta">' +
          conditions.length + ' 项检查 · ' +
          (conditions.length - failedCount) + ' 通过 · ' +
          failedCount + ' 未通过' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="gg-conditions">' +
      conditions.map(function(c) {
        return '<div class="gg-condition ' + (c.passed ? 'passed' : 'failed') + '">' +
          '<div class="gg-cond-header">' +
            '<span class="gg-cond-icon">' + (c.passed ? '✓' : '✗') + '</span>' +
            '<span class="gg-cond-name">' + escapeHtml(c.name || c.condition || '') + '</span>' +
            '<span class="gg-cond-status ' + (c.passed ? 'pass' : 'fail') + '">' + (c.passed ? '通过' : '未通过') + '</span>' +
          '</div>' +
          (c.detail ? '<div class="gg-cond-detail">' + escapeHtml(c.detail) + '</div>' : '') +
          (c.suggestion ? '<div class="gg-cond-suggestion">建议：' + escapeHtml(c.suggestion) + '</div>' : '') +
        '</div>';
      }).join('') +
    '</div>' +
    (data.iteration != null ? '<div class="gg-iteration">迭代次数：' + data.iteration + '</div>' : '');
}

function toggleGoalGatePanel() {
  var panel = $('#goal-gate-container');
  if (!panel) return;
  var isHidden = panel.style.display === 'none';
  panel.style.display = isHidden ? '' : 'none';
  if (isHidden) {
    // 面板打开时自动填充当前章节内容
    var editor = $('#editor-textarea');
    if (editor && editor.value && editor.value.trim().length > 100) {
      verifyChapterGoal(editor.value);
    } else {
      renderGoalGatePanelEmpty();
    }
  }
}

function renderGoalGatePanelEmpty() {
  var panel = $('#goal-gate-panel');
  if (!panel) return;
  panel.innerHTML = 
    '<div class="gg-empty">' +
      '<div class="gg-empty-icon"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></div>' +
      '<p>点击下方按钮验证章节是否满足完成标准</p>' +
      '<div class="gg-criteria-preview">' +
        '<div class="gg-criteria-item"><span class="gg-dot"></span>字数范围 (2000-5000字)</div>' +
        '<div class="gg-criteria-item"><span class="gg-dot"></span>爽点数量 (≥1个)</div>' +
        '<div class="gg-criteria-item"><span class="gg-dot"></span>情绪曲线 (上升型)</div>' +
        '<div class="gg-criteria-item"><span class="gg-dot"></span>Canon一致性检查</div>' +
        '<div class="gg-criteria-item"><span class="gg-dot"></span>S3评审得分 (≥70分)</div>' +
      '</div>' +
    '</div>';
}

async function loadGoalGateHistory() {
  var { ok, data } = await apiGet('/api/creative/goal-gate/history?limit=10');
  if (!ok || !data || !data.records) return [];
  return data.records;
}
