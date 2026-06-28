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
function editWorldview() {
  showToast('世界观编辑器开发中');
}
function selectRelationNode(name) {
  const svg = $('#char-relation-svg');
  if (!svg) return;
  const lines = svg.querySelectorAll('.relation-line');
  const nodes = svg.querySelectorAll('.relation-node');
  lines.forEach((l) => {
    const active = l.dataset.from === name || l.dataset.to === name;
    l.classList.toggle('active', active);
    l.classList.toggle('dimmed', !active);
  });
  nodes.forEach((n) => {
    const active = n.dataset.name === name;
    const connected = Array.from(lines).some((l) =>
      (l.dataset.from === name && l.dataset.to === n.dataset.name) ||
      (l.dataset.to === name && l.dataset.from === n.dataset.name)
    );
    n.classList.toggle('active', active);
    n.classList.toggle('connected', connected);
    n.classList.toggle('dimmed', !active && !connected);
  });
}
function toggleHiddenChars(btn) {
  const grid = $('#character-grid');
  if (!grid) return;
  const hidden = grid.querySelectorAll('.character-card[data-hidden="true"]');
  const expanded = btn.dataset.expanded === 'true';
  hidden.forEach((c) => c.classList.toggle('shown', !expanded));
  btn.textContent = expanded ? '展开全部角色' : '收起隐藏角色';
  btn.dataset.expanded = expanded ? 'false' : 'true';
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
    '<div class="faction-item" onclick="openFactionEdit(' + idx + ')">' +
      '<div class="faction-item-body"><b>' + escapeHtml(f.name || '') + '</b><p>' + escapeHtml(f.desc || '') + '</p></div>' +
      '<button class="faction-edit-icon" title="编辑" onclick="event.stopPropagation();openFactionEdit(' + idx + ')">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
      '</button>' +
    '</div>'
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
function showDesign(name) {
  $$('.design-pane').forEach((p) => p.classList.remove('active'));
  const target = $('#design-' + name);
  if (target) target.classList.add('active');
  $$('.subnav-item').forEach((s) => s.classList.toggle('active', s.dataset.sub === name));
}
