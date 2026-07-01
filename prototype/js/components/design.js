"use strict";

// 设计面板编辑状态由 app.js 全局声明，design.js 直接使用
function renderDesignFromSkeleton(data) {
  // ── 1. 粗纲（卷卡片）— 保留 progress/tags 结构 ──
  const roughPane = $('#design-rough');
  if (roughPane && data.volumes) {
    if (data.volumes.length === 0) {
      roughPane.innerHTML = '<div class="design-empty-hint" style="padding:40px;text-align:center;color:var(--text-secondary);">暂无粗纲数据。点击右上角「从AI生成骨架」或手动添加卷。<br><button class="btn btn-primary btn-sm" style="margin-top:12px;" onclick="loadSkeletonData()">从AI生成骨架</button></div>';
    } else {
      roughPane.innerHTML = '<div class="volume-grid">' + data.volumes.map(function(v, idx) {
        var tagsHtml = (v.tags || []).map(function(t) { return '<span class="tag">' + escapeHtml(t) + '</span>'; }).join('');
        var rhythmHtml = v.rhythm_goal ? '<div class="volume-rhythm" style="font-size:11px;color:var(--text-secondary);margin-top:4px;">节奏目标: ' + escapeHtml(v.rhythm_goal) + '</div>' : '';
        var progressHtml = '';
        if (v.written !== undefined && v.total !== undefined) {
          var pct = v.total > 0 ? Math.round(v.written / v.total * 100) : 0;
          var barClass = pct === 0 ? 'zero' : (pct < 33 ? 'low' : (pct < 67 ? 'mid' : 'high'));
          var progressText = pct === 0 ? '未开始' : ('已写 ' + v.written + ' / ' + v.total + ' 章');
          progressHtml = '<div class="volume-progress"><div class="volume-progress-bar ' + barClass + '" style="width:' + pct + '%"></div></div>' +
            '<div class="volume-progress-text">' + progressText + '</div>';
        }
        return '<div class="volume-card" onclick="openVolumeEdit(' + idx + ')" style="cursor:pointer;">' +
          '<div class="volume-header"><span class="volume-title">' + escapeHtml(v.title || '') + '</span><span class="volume-range">' + escapeHtml(v.range || '') + '</span></div>' +
          '<div class="volume-subtitle">' + escapeHtml(v.subtitle || '') + '</div>' +
          '<p class="volume-summary">' + escapeHtml(v.summary || '') + '</p>' +
          rhythmHtml +
          progressHtml +
          '<div class="volume-tags">' + tagsHtml + '</div>' +
          '</div>';
      }).join('') + '</div>';
    }
    DESIGN_DATA.volumes = data.volumes;
  }

  // ── 2. 细纲 — 保留 segment-card 格式 + 网文字段 ──
  const detailedPane = $('#design-detailed');
  if (detailedPane) {
    if (!data.chapters || data.chapters.length === 0) {
      detailedPane.innerHTML = '<div class="design-empty-hint" style="padding:40px;text-align:center;color:var(--text-secondary);">暂无细纲数据。可在粗纲页生成骨架后自动填充，或手动添加章节段。<br><button class="btn btn-secondary btn-sm" style="margin-top:12px;" onclick="showDesign(\'rough\')">去粗纲页</button></div>';
      DESIGN_DATA.chapters = [];
    } else {
      // 将后端 chapters 渲染为 segment-card 格式 + 网文字段（钩子/爽点/伏笔/期待感）
      detailedPane.innerHTML = '<div class="segment-grid">' + data.chapters.map(function(ch, idx) {
        var scenesHtml = (ch.scenes || []).map(function(s) { return '<li>' + escapeHtml(s) + '</li>'; }).join('');
        // P0-6: 渲染网文核心字段（有内容才显示）
        var webFields = '';
        if (ch.hook) webFields += '<div class="segment-field segment-field-hook"><b>钩子</b><p>' + escapeHtml(ch.hook) + '</p></div>';
        if (ch.pleasure) webFields += '<div class="segment-field segment-field-pleasure"><b>爽点</b><p>' + escapeHtml(ch.pleasure) + '</p></div>';
        if (ch.foreshadowing) webFields += '<div class="segment-field segment-field-foreshadow"><b>伏笔</b><p>' + escapeHtml(ch.foreshadowing) + '</p></div>';
        if (ch.expectation) webFields += '<div class="segment-field segment-field-expect"><b>期待感</b><p>' + escapeHtml(ch.expectation) + '</p></div>';
        return '<div class="segment-card" onclick="openChapterEdit(' + idx + ')" style="cursor:pointer;">' +
          '<div class="segment-header">' +
            '<div class="segment-title">' + escapeHtml(ch.title || '') + '</div>' +
            '<div class="segment-meta"><span class="segment-status planned">规划中</span></div>' +
          '</div>' +
          '<div class="segment-fields">' +
            '<div class="segment-field"><b>目标</b><p>' + escapeHtml(ch.goal || '') + '</p></div>' +
            '<div class="segment-field"><b>冲突</b><p>' + escapeHtml(ch.conflict || '') + '</p></div>' +
            '<div class="segment-field"><b>结果</b><p>' + escapeHtml(ch.result || '') + '</p></div>' +
          '</div>' +
          (webFields ? '<div class="segment-fields segment-web-fields">' + webFields + '</div>' : '') +
          (scenesHtml ? '<ul class="scene-list" style="margin-top:8px;">' + scenesHtml + '</ul>' : '') +
          '</div>';
      }).join('') + '</div>';
      DESIGN_DATA.chapters = data.chapters;
    }
  }

  // ── 3. 世界观 — 只更新 core 文本，保留 dimensions/timeline/preview 不破坏 ──
  if (data.world) {
    DESIGN_DATA.world = data.world;
    var worldSummary = document.querySelector('#design-world .world-core > p');
    if (worldSummary && data.world.core) {
      worldSummary.textContent = data.world.core;
    }
    // 如果有 powers 字段，更新规则系统维度
    if (data.world.powers) {
      var rulesDim = document.querySelector('#design-world .world-dimension h5');
      if (rulesDim) {
        var rulesList = rulesDim.parentElement.querySelector('ul');
        if (rulesList) {
          var powers = data.world.powers.split(/[，,；;\n]/).filter(Boolean);
          if (powers.length > 0) {
            rulesList.innerHTML = powers.map(function(p) { return '<li>' + escapeHtml(p.trim()) + '</li>'; }).join('');
          }
        }
      }
    }
  }

  // ── 4. 势力 — 只更新 faction-list，不删除 SVG 关系图 ──
  if (data.factions) {
    DESIGN_DATA.factions = data.factions;
    renderFactions();
  }

  // ── 5. 角色 — 只更新 character-grid，不删除 SVG 关系图 ──
  if (data.characters) {
    DESIGN_DATA.characters = data.characters;
    var charGrid = $('#character-grid');
    if (charGrid) {
      if (data.characters.length === 0) {
        charGrid.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-secondary);">暂无角色数据</div>';
      } else {
        charGrid.innerHTML = data.characters.map(function(c, idx) {
          return '<div class="character-card" onclick="openCharacterEdit(' + idx + ')" style="cursor:pointer;">' +
            '<h4>' + escapeHtml(c.name || '') + '</h4>' +
            '<div class="char-role">' + escapeHtml(c.role || '') + '</div>' +
            '<p>' + escapeHtml(c.desc || '') + '</p>' +
            '</div>';
        }).join('');
      }
    }
  }

  // 更新编辑按钮绑定
  initDesignEditButtons();
}
function updateDesignEmptyState() {
  const empty = $('#design-empty-state');
  const panes = document.querySelectorAll('.design-pane');
  const sidebar = $('#design-sidebar');
  const hasProject = currentProject && currentProject.id;
  if (empty) {
    empty.style.display = hasProject ? 'none' : 'flex';
  }
  if (sidebar) {
    sidebar.style.display = hasProject ? '' : 'none';
  }
  panes.forEach(p => {
    if (!hasProject) {
      p.style.display = 'none';
    } else {
      p.style.display = p.classList.contains('active') ? '' : 'none';
    }
  });
}

function renderDesignSidebar() {
  const totalEl = $('#design-status-total');
  const writtenEl = $('#design-status-written');
  const plannedEl = $('#design-status-planned');
  const barEl = $('#design-status-bar');
  const hintEl = $('#design-status-hint');
  if (!currentProject) return;
  const total = currentProject.totalChapters || 0;
  const written = currentProject.writtenChapters || 0;
  const planned = Math.max(0, total - written);
  const pct = total > 0 ? Math.round((written / total) * 100) : 0;
  if (totalEl) totalEl.textContent = String(total);
  if (writtenEl) writtenEl.textContent = String(written);
  if (plannedEl) plannedEl.textContent = String(planned);
  if (barEl) barEl.style.width = pct + '%';
  if (hintEl) hintEl.textContent = '写作进度 ' + pct + '%';
}

async function loadDesignData() {
  updateDesignEmptyState();
  if (!currentProject || !currentProject.id) return;
  try {
    const [skeletonRes, worldRes, charsRes, factionsRes] = await Promise.all([
      ProjectAPI.getSkeleton(currentProject.id),
      ProjectAPI.getWorld(currentProject.id),
      ProjectAPI.getCharacters(currentProject.id),
      ProjectAPI.getFactions(currentProject.id),
    ]);
    renderDesignSidebar();
    const data = {
      volumes: (skeletonRes && skeletonRes.volumes) || [],
      chapters: (skeletonRes && skeletonRes.chapters) || [],
      world: (worldRes && worldRes.core !== undefined) ? worldRes : { core: '', powers: '' },
      characters: (charsRes && charsRes.characters) || [],
      factions: (factionsRes && factionsRes.factions) || [],
    };
    // 兼容：旧版势力可能还在 world.factions 里
    if (!data.factions.length && data.world.factions) {
      data.factions = data.world.factions;
    }
    renderDesignFromSkeleton(data);
  } catch (e) {
    console.error('loadDesignData failed', e);
    showToast('加载设计数据失败');
  }
}

function renderFactionsFromData(factions) {
  // 委托给 renderFactions，不破坏 SVG 关系图
  renderFactions();
}
function initDesignEditButtons() {
  $$('.volume-card').forEach((card, idx) => {
    card.onclick = () => openVolumeEdit(idx);
  });
  $$('.segment-card').forEach((card, idx) => {
    card.onclick = () => openChapterEdit(idx);
  });
  $$('.character-card').forEach((card, idx) => {
    card.onclick = () => openCharacterEdit(idx);
  });
  const worldCore = $('.world-core');
  if (worldCore) worldCore.onclick = () => openWorldEdit();
  renderFactions();
}
function openDesignDrawer(title, bodyHtml) {
  const titleEl = $('#design-edit-title');
  const bodyEl = $('#design-edit-body');
  const modal = $('#design-edit-modal');
  const overlay = $('#design-edit-overlay');
  if (titleEl) titleEl.textContent = title;
  if (bodyEl) bodyEl.innerHTML = bodyHtml + '<div class="report-ai-suggestions" id="design-ai-box" style="display:none"></div>';
  if (modal) modal.classList.add('open');
  if (overlay) overlay.classList.add('open');
}
function closeDesignEdit() {
  const modal = $('#design-edit-modal');
  const overlay = $('#design-edit-overlay');
  if (modal) modal.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
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
  // P0-6: 增加网文核心字段 — 钩子/爽点/伏笔/期待感
  openDesignDrawer('编辑 ' + c.title,
    '<div class="design-edit-section"><label class="design-edit-section-title">基础结构</label>' +
    '<div class="report-detail-field"><label>目标</label><textarea id="design-edit-goal">' + escapeHtml(c.goal || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>冲突</label><textarea id="design-edit-conflict">' + escapeHtml(c.conflict || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>结果</label><textarea id="design-edit-result">' + escapeHtml(c.result || '') + '</textarea></div>' +
    '</div>' +
    '<div class="design-edit-section"><label class="design-edit-section-title">网文核心要素 <span class="design-edit-hint">（决定读者留存率的关键字段）</span></label>' +
    '<div class="report-detail-field"><label>钩子 <span class="field-hint">本章如何吸引读者看下一章</span></label><textarea id="design-edit-hook" placeholder="例：结尾揭露主角身世之谜，引发好奇">' + escapeHtml(c.hook || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>爽点 <span class="field-hint">本章要满足什么情绪</span></label><textarea id="design-edit-pleasure" placeholder="例：装逼打脸，实力碾压，反派被打脸">' + escapeHtml(c.pleasure || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>伏笔 <span class="field-hint">本章埋下的伏笔及回收章节</span></label><textarea id="design-edit-foreshadowing" placeholder="例：老K的伤疤 → 第45章揭露是前组织留下的">' + escapeHtml(c.foreshadowing || '') + '</textarea></div>' +
    '<div class="report-detail-field"><label>期待感 <span class="field-hint">本章如何增强读者期待</span></label><textarea id="design-edit-expectation" placeholder="例：暗示更大危机即将到来，读者期待主角如何应对">' + escapeHtml(c.expectation || '') + '</textarea></div>' +
    '</div>' +
    '<div class="design-edit-section"><label class="design-edit-section-title">场景列表</label>' +
    '<div class="report-detail-field"><label>场景（每行一个）</label><textarea id="design-edit-scenes">' + escapeHtml((c.scenes || []).join('\n')) + '</textarea></div>' +
    '</div>'
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
async function aiSuggestDesign() {
  const box = $('#design-ai-box');
  if (!box) return;
  box.style.display = 'block';
  box.innerHTML = '<div style="padding:12px;color:var(--text-secondary);font-size:13px;">正在检查模型状态...</div>';
  // v8.5: 检查模型是否在线，不再返回假建议
  try {
    var { ok, data } = await apiGet('/api/model/status');
    if (!ok || !data || data.mode === 'unknown') {
      box.innerHTML = '<div style="padding:12px;color:var(--text-warning);font-size:13px;">⚠ 无法获取模型状态，请检查后端服务</div>';
      return;
    }
    var models = data.models || {};
    var anyRunning = Object.values(models).some(function(m) { return m && m.status === 'running'; });
    if (!anyRunning) {
      box.innerHTML = '<div style="padding:12px;color:var(--text-warning);font-size:13px;">⚠ 本地模型未启动，请先在<a style="color:var(--accent-primary);cursor:pointer;" onclick="navigate(\'hardware\')">硬件监控</a>页启动模型</div>';
      return;
    }
    var typeLabel = { volume: '粗纲', chapter: '细纲', character: '角色', world: '世界观' }[designEditType] || '设计';
    box.innerHTML = '<div style="padding:12px;color:var(--text-secondary);font-size:13px;">模型已就绪。AI建议功能正在开发中，当前请通过<a style="color:var(--accent-primary);cursor:pointer;" onclick="navigate(\'writing\')">写作页</a>的AI辅助使用模型能力。</div>';
  } catch (e) {
    box.innerHTML = '<div style="padding:12px;color:var(--text-danger);font-size:13px;">请求失败: ' + escapeHtml(e.message) + '</div>';
  }
}
async function saveDesignEdit() {
  if (!currentProject || !currentProject.id) {
    showToast('请先选择或创建一个项目');
    return;
  }
  const pid = currentProject.id;
  try {
    if (designEditType === 'volume') {
      const v = DESIGN_DATA.volumes[designEditIndex];
      v.title = $('#design-edit-title-input').value;
      v.range = $('#design-edit-range').value;
      v.subtitle = $('#design-edit-subtitle').value;
      v.summary = $('#design-edit-summary').value;
      v.tags = $('#design-edit-tags').value.split(',').map(t => t.trim()).filter(Boolean);
      await ProjectAPI.updateSkeleton(pid, { volumes: DESIGN_DATA.volumes, chapters: DESIGN_DATA.chapters });
    } else if (designEditType === 'chapter') {
      const c = DESIGN_DATA.chapters[designEditIndex];
      c.goal = $('#design-edit-goal').value;
      c.conflict = $('#design-edit-conflict').value;
      c.result = $('#design-edit-result').value;
      // P0-6: 保存网文核心字段
      c.hook = $('#design-edit-hook').value;
      c.pleasure = $('#design-edit-pleasure').value;
      c.foreshadowing = $('#design-edit-foreshadowing').value;
      c.expectation = $('#design-edit-expectation').value;
      c.scenes = $('#design-edit-scenes').value.split('\n').map(t => t.trim()).filter(Boolean);
      await ProjectAPI.updateSkeleton(pid, { volumes: DESIGN_DATA.volumes, chapters: DESIGN_DATA.chapters });
    } else if (designEditType === 'character') {
      const c = DESIGN_DATA.characters[designEditIndex];
      c.name = $('#design-edit-name').value;
      c.role = $('#design-edit-role').value;
      c.desc = $('#design-edit-desc').value;
      await ProjectAPI.updateCharacters(pid, DESIGN_DATA.characters);
    } else if (designEditType === 'world') {
      DESIGN_DATA.world.core = $('#design-edit-core').value;
      DESIGN_DATA.world.powers = $('#design-edit-powers').value;
      await ProjectAPI.updateWorld(pid, DESIGN_DATA.world);
    } else if (designEditType === 'faction') {
      const factions = DESIGN_DATA.factions || DESIGN_DATA.world.factions || [];
      const f = factions[designEditIndex];
      f.name = $('#design-edit-faction-name').value;
      f.desc = $('#design-edit-faction-desc').value;
      DESIGN_DATA.factions = factions;
      // 清理旧版 world.factions，避免数据重复
      if (DESIGN_DATA.world && DESIGN_DATA.world.factions) {
        delete DESIGN_DATA.world.factions;
      }
      await ProjectAPI.updateFactions(pid, factions);
    }
    renderDesign();
    await refreshProjectData();
    showToast('已保存');
    closeDesignEdit();
  } catch (e) {
    console.error('saveDesignEdit failed', e);
    showToast('保存失败');
  }
}

async function refreshProjectData() {
  if (!currentProject || !currentProject.id) return;
  const project = await ProjectAPI.get(currentProject.id);
  if (project) {
    appState.projectData = project;
  }
}
function renderFactions() {
  const list = $('#faction-list');
  if (!list) return;
  const factions = DESIGN_DATA.factions || DESIGN_DATA.world.factions || [];
  list.innerHTML = factions.map((f, idx) =>
    '<div class="faction-item" onclick="openFactionEdit(' + idx + ')">' +
      '<div class="faction-item-body"><b>' + escapeHtml(f.name || '') + '</b><p>' + escapeHtml(f.desc || '') + '</p></div>' +
      '<button class="faction-edit-icon" title="编辑" onclick="event.stopPropagation();openFactionEdit(' + idx + ')">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
      '</button>' +
    '</div>'
  ).join('');
  // P0: 同步更新 SVG 关系图
  renderFactionSVG(factions);
}

// 动态生成势力关系 SVG
function renderFactionSVG(factions) {
  var svg = document.querySelector('#design-factions .relation-svg');
  if (!svg) return;
  if (!factions || factions.length === 0) {
    svg.innerHTML = '<text x="300" y="150" text-anchor="middle" fill="var(--text-muted)" font-size="13">暂无势力数据，请在下方添加</text>';
    return;
  }
  var cx = 300, cy = 150;
  var n = factions.length;
  var nodeR = n > 6 ? 22 : 28;
  var fontSize = n > 6 ? 10 : 12;
  var radiusX = n <= 2 ? 0 : Math.min(200, 100 + n * 15);
  var radiusY = n <= 2 ? 0 : Math.min(90, 50 + n * 8);

  // 计算节点位置
  var positions = factions.map(function(f, i) {
    if (n === 1) return { x: cx, y: cy };
    if (n === 2) return [{ x: cx - 100, y: cy }, { x: cx + 100, y: cy }][i];
    var angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    return { x: cx + Math.cos(angle) * radiusX, y: cy + Math.sin(angle) * radiusY };
  });

  var html = '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="20" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="var(--text-secondary)"/></marker></defs>';

  // 连线：第一个节点向所有其他节点放射 + 相邻节点虚线连接
  for (var i = 1; i < n; i++) {
    var p1 = positions[0], p2 = positions[i];
    html += '<line x1="' + p1.x + '" y1="' + p1.y + '" x2="' + p2.x + '" y2="' + p2.y + '" stroke="var(--border)" stroke-width="1"/>';
  }
  if (n > 2) {
    for (var i = 1; i < n; i++) {
      var next = (i + 1) % n;
      if (next === 0) continue;
      var pa = positions[i], pb = positions[next];
      html += '<line x1="' + pa.x + '" y1="' + pa.y + '" x2="' + pb.x + '" y2="' + pb.y + '" stroke="var(--border)" stroke-width="1" stroke-dasharray="3,3" opacity="0.5"/>';
    }
  }

  // 节点
  factions.forEach(function(f, i) {
    var p = positions[i];
    var isMain = i === 0;
    var stroke = isMain ? 'var(--accent)' : 'var(--border)';
    var sw = isMain ? 2 : 1;
    var textColor = isMain ? 'var(--text)' : 'var(--text-secondary)';
    var name = escapeHtml(f.name || ('势力' + (i + 1)));
    if (name.length > 5) name = name.substring(0, 4) + '…';
    html += '<g onclick="openFactionEdit(' + i + ')" style="cursor:pointer;">';
    html += '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + nodeR + '" fill="var(--surface)" stroke="' + stroke + '" stroke-width="' + sw + '"/>';
    html += '<text x="' + p.x + '" y="' + (p.y + 4) + '" text-anchor="middle" fill="' + textColor + '" font-size="' + fontSize + '">' + name + '</text>';
    html += '</g>';
  });

  svg.innerHTML = html;
}
function openFactionEdit(idx) {
  designEditType = 'faction';
  designEditIndex = idx;
  const factions = DESIGN_DATA.factions || DESIGN_DATA.world.factions || [];
  const f = factions[idx];
  openDesignDrawer('编辑势力：' + f.name,
    '<div class="report-detail-field"><label>势力名称</label><input type="text" id="design-edit-faction-name" value="' + escapeHtml(f.name || '') + '"></div>' +
    '<div class="report-detail-field"><label>势力描述</label><textarea id="design-edit-faction-desc">' + escapeHtml(f.desc || '') + '</textarea></div>'
  );
}
function renderDesign() {
  $$('.volume-card').forEach((card, idx) => {
    const v = DESIGN_DATA.volumes[idx];
    if (!v) return;
    var titleEl = card.querySelector('.volume-title');
    var rangeEl = card.querySelector('.volume-range');
    var subtitleEl = card.querySelector('.volume-subtitle');
    var summaryEl = card.querySelector('.volume-summary');
    var tagsEl = card.querySelector('.volume-tags');
    if (titleEl) titleEl.textContent = v.title || '';
    if (rangeEl) rangeEl.textContent = v.range || '';
    if (subtitleEl) subtitleEl.textContent = v.subtitle || '';
    if (summaryEl) summaryEl.textContent = v.summary || '';
    if (tagsEl) tagsEl.innerHTML = (v.tags || []).map(function(t) { return '<span class="tag">' + escapeHtml(t) + '</span>'; }).join('');
  });
  $$('.segment-card').forEach((card, idx) => {
    const c = DESIGN_DATA.chapters[idx];
    if (!c) return;
    var titleEl = card.querySelector('.segment-title');
    if (titleEl) titleEl.textContent = c.title || '';
    var fields = card.querySelectorAll('.segment-fields:first-child .segment-field p');
    if (fields.length >= 3) {
      fields[0].textContent = c.goal || '';
      fields[1].textContent = c.conflict || '';
      fields[2].textContent = c.result || '';
    }
    // P0-6: 更新网文字段
    var webFieldsContainer = card.querySelector('.segment-web-fields');
    if (webFieldsContainer) {
      webFieldsContainer.innerHTML =
        (c.hook ? '<div class="segment-field segment-field-hook"><b>钩子</b><p>' + escapeHtml(c.hook) + '</p></div>' : '') +
        (c.pleasure ? '<div class="segment-field segment-field-pleasure"><b>爽点</b><p>' + escapeHtml(c.pleasure) + '</p></div>' : '') +
        (c.foreshadowing ? '<div class="segment-field segment-field-foreshadow"><b>伏笔</b><p>' + escapeHtml(c.foreshadowing) + '</p></div>' : '') +
        (c.expectation ? '<div class="segment-field segment-field-expect"><b>期待感</b><p>' + escapeHtml(c.expectation) + '</p></div>' : '');
    }
    var sceneList = card.querySelector('.scene-list');
    if (sceneList) {
      sceneList.innerHTML = (c.scenes || []).map(function(s) { return '<li>' + escapeHtml(s) + '</li>'; }).join('');
    }
  });
  $$('.character-card').forEach((card, idx) => {
    const c = DESIGN_DATA.characters[idx];
    if (!c) return;
    var h4 = card.querySelector('h4');
    var role = card.querySelector('.char-role');
    var p = card.querySelector('p');
    if (h4) h4.textContent = c.name || '';
    if (role) role.textContent = c.role || '';
    if (p) p.textContent = c.desc || '';
  });
  renderFactions();
  renderOutlinePanel();
}
function showDesign(name) {
  $$('.subnav-item').forEach((s) => s.classList.toggle('active', s.dataset.sub === name));
  $$('.design-pane').forEach((p) => {
    p.classList.remove('active');
    p.style.display = 'none';
  });
  const target = $('#design-' + name);
  if (target) {
    target.classList.add('active');
    target.style.display = '';
  }
  updateDesignEmptyState();
}

// ============================================================
// P0-5/P0-8: 快速开始向导 — 从一句话梗概到大纲骨架
// ============================================================

var _quickStartStep = 1;
var _qsMaxSteps = 5;

function openQuickStart() {
  var modal = $('#quick-start-modal');
  if (!modal) return;
  _quickStartStep = 1;
  _qsMaxSteps = 5;
  _renderQuickStartStep();
  modal.classList.add('open');
  var overlay = $('#quick-start-overlay');
  if (overlay) overlay.classList.add('open');
}

function closeQuickStart() {
  var modal = $('#quick-start-modal');
  if (!modal) return;
  modal.classList.remove('open');
  var overlay = $('#quick-start-overlay');
  if (overlay) overlay.classList.remove('open');
}

function _renderQuickStartStep() {
  var body = $('#quick-start-body');
  if (!body) return;
  var indicator = $('#quick-start-indicator');
  if (indicator) {
    indicator.innerHTML = '';
    for (var i = 1; i <= _qsMaxSteps; i++) {
      var cls = i < _quickStartStep ? 'done' : (i === _quickStartStep ? 'active' : '');
      indicator.innerHTML += '<span class="qs-step-dot ' + cls + '"></span>';
      if (i < _qsMaxSteps) indicator.innerHTML += '<span class="qs-step-line"></span>';
    }
  }
  if (_quickStartStep === 1) {
    // Step 1: 题材 (World 的前置)
    body.innerHTML =
      '<h3 class="qs-title">选择题材</h3>' +
      '<p class="qs-desc">选择你正在写或想写的题材，系统会参考同类爆款数据辅助设计</p>' +
      '<div class="qs-genre-grid">' +
        ['末世','仙侠','科幻','都市','悬疑','无限流','历史','奇幻','洪荒','同人','游戏','玄幻'].map(function(g) {
          return '<button class="qs-genre-btn" onclick="quickStartSelectGenre(\'' + g + '\')">' + g + '</button>';
        }).join('') +
      '</div>';
  } else if (_quickStartStep === 2) {
    // Step 2: 剧情 (Plot) — 一句话梗概 + 扩展
    var genre = $('#qs-genre-hidden') ? $('#qs-genre-hidden').value : '';
    body.innerHTML =
      '<h3 class="qs-title">剧情 — 用一句话抓住故事核心</h3>' +
      '<p class="qs-desc">好的梗概 = 主角 + 金手指 + 核心冲突 + 目标。先写一句话，再扩展到 100-300 字的简介。</p>' +
      '<div class="qs-input-area">' +
        '<textarea id="qs-premise" placeholder="例：高考生在末日考场觉醒模拟器，每次死亡保留记忆，必须在72小时轮回中拯救城市。" rows="3" style="font-size:15px;"></textarea>' +
        '<textarea id="qs-synopsis" placeholder="扩展简介（可选）：用 100-300 字描述故事走向、主要矛盾、主角成长路径..." rows="4" style="margin-top:8px;font-size:13px;"></textarea>' +
        '<div class="qs-examples">' +
          '<div class="qs-example-label">优秀梗概参考：</div>' +
          '<div class="qs-example-item" onclick="document.getElementById(\'qs-premise\').value=this.textContent">普通程序员获得游戏系统，在都市中升级打怪成为商业帝国掌门人</div>' +
          '<div class="qs-example-item" onclick="document.getElementById(\'qs-premise\').value=this.textContent">穿越洪荒，成为天道选中的量劫之子，在封神量劫中谋划成圣</div>' +
          '<div class="qs-example-item" onclick="document.getElementById(\'qs-premise\').value=this.textContent">无限流：被选中者进入恐怖片世界，完成任务获得能力，逐渐揭开无限空间的真相</div>' +
        '</div>' +
      '</div>' +
      '<div class="qs-nav">' +
        '<button class="btn btn-secondary" onclick="_quickStartStep=1;_renderQuickStartStep()">上一步</button>' +
        '<button class="btn btn-primary" onclick="quickStartConfirmPremise()">下一步</button>' +
      '</div>';
  } else if (_quickStartStep === 3) {
    // Step 3: 卖点 (Hook) — 核心差异
    body.innerHTML =
      '<h3 class="qs-title">卖点 — 你的故事凭什么吸引读者？</h3>' +
      '<p class="qs-desc">思考你的故事与同类作品的核心差异。这个差异就是读者选择你的理由。</p>' +
      '<div class="qs-input-area">' +
        '<textarea id="qs-hook" placeholder="例：系统不是打怪升级，而是通过养灵宠让灵宠代打，实现人仗狗势" rows="3" style="font-size:15px;"></textarea>' +
        '<div class="qs-examples">' +
          '<div class="qs-example-label">卖点提炼参考：</div>' +
          '<div class="qs-example-item" onclick="document.getElementById(\'qs-hook\').value=this.textContent">金手指有代价：每次使用模拟器会加速变异，主角必须在实力和人性间抉择</div>' +
          '<div class="qs-example-item" onclick="document.getElementById(\'qs-hook\').value=this.textContent">视角反转：主角以为自己重生，其实是模拟器中的NPC获得了自我意识</div>' +
          '<div class="qs-example-item" onclick="document.getElementById(\'qs-hook\').value=this.textContent">题材混搭：修仙+克苏鲁，灵气复苏实则是古神苏醒的前兆</div>' +
        '</div>' +
      '</div>' +
      '<div class="qs-nav">' +
        '<button class="btn btn-secondary" onclick="_quickStartStep=2;_renderQuickStartStep()">上一步</button>' +
        '<button class="btn btn-primary" onclick="quickStartConfirmHook()">下一步</button>' +
      '</div>';
  } else if (_quickStartStep === 4) {
    // Step 4: 人设+目标 (Characters + Goals)
    body.innerHTML =
      '<h3 class="qs-title">人设与目标 — 谁在做什么，为什么？</h3>' +
      '<p class="qs-desc">主角人设应服务于剧情。配角应服务于主角——主角缺什么就安排什么。</p>' +
      '<div class="qs-input-area">' +
        '<div class="qs-field-group">' +
          '<label>主角人设（一句话）</label>' +
          '<textarea id="qs-protagonist" placeholder="例：聪明但爱摆烂的理性派，躲在灵宠后面运筹帷幄" rows="2"></textarea>' +
        '</div>' +
        '<div class="qs-field-group">' +
          '<label>金手指/外挂</label>' +
          '<textarea id="qs-goldfinger" placeholder="例：灵宠养成系统，灵宠等级越高代战能力越强，但需要消耗主角的寿命" rows="2"></textarea>' +
        '</div>' +
        '<div class="qs-field-group">' +
          '<label>阶段目标（每10万字一个大目标）</label>' +
          '<textarea id="qs-goals" placeholder="例：征服宗门 → 征服帝国 → 征服大陆 → 登顶顶峰" rows="3"></textarea>' +
        '</div>' +
      '</div>' +
      '<div class="qs-nav">' +
        '<button class="btn btn-secondary" onclick="_quickStartStep=3;_renderQuickStartStep()">上一步</button>' +
        '<button class="btn btn-primary" onclick="quickStartConfirmCharacters()">下一步</button>' +
      '</div>';
  } else if (_quickStartStep === 5) {
    // Step 5: 确认并生成 (World 自动衍生)
    var genre = $('#qs-genre-hidden') ? $('#qs-genre-hidden').value : '';
    var premise = $('#qs-premise-hidden') ? $('#qs-premise-hidden').value : '';
    var hook = $('#qs-hook-hidden') ? $('#qs-hook-hidden').value : '';
    var protagonist = $('#qs-protagonist-hidden') ? $('#qs-protagonist-hidden').value : '';
    var goldfinger = $('#qs-goldfinger-hidden') ? $('#qs-goldfinger-hidden').value : '';
    var goals = $('#qs-goals-hidden') ? $('#qs-goals-hidden').value : '';
    body.innerHTML =
      '<h3 class="qs-title">确认并生成</h3>' +
      '<p class="qs-desc">系统将根据以上设定创建项目并生成骨架。世界观将根据剧情和金手指自动衍生，无需手动设定。</p>' +
      '<div class="qs-confirm-card">' +
        '<div class="qs-confirm-row"><span>题材</span><b>' + escapeHtml(genre) + '</b></div>' +
        '<div class="qs-confirm-row"><span>剧情</span><b>' + escapeHtml(premise) + '</b></div>' +
        '<div class="qs-confirm-row"><span>卖点</span><b>' + escapeHtml(hook || '未填写') + '</b></div>' +
        '<div class="qs-confirm-row"><span>主角</span><b>' + escapeHtml(protagonist || '未填写') + '</b></div>' +
        '<div class="qs-confirm-row"><span>金手指</span><b>' + escapeHtml(goldfinger || '未填写') + '</b></div>' +
        '<div class="qs-confirm-row"><span>目标</span><b>' + escapeHtml(goals || '未填写') + '</b></div>' +
      '</div>' +
      '<div class="qs-confirm-tips">' +
        '<div class="qs-tip"><b>&#9889;</b> 前三章保持快节奏，2000 字内出现第一次冲突</div>' +
        '<div class="qs-tip"><b>&#9889;</b> 每 3 章至少一个清晰爽点，避免连续 5 章无爽点</div>' +
        '<div class="qs-tip"><b>&#9889;</b> 主角金手指要在第 1 章落地，第 3 章首次展示威力</div>' +
        '<div class="qs-tip"><b>&#128218;</b> 建议先用拆书功能分析 3-5 本同类精品书，获取真实数据后再微调大纲</div>' +
      '</div>' +
      '<div class="qs-nav">' +
        '<button class="btn btn-secondary" onclick="_quickStartStep=4;_renderQuickStartStep()">上一步</button>' +
        '<button class="btn btn-primary" onclick="quickStartGenerate()">创建项目并生成骨架</button>' +
      '</div>';
  }
}

function quickStartSelectGenre(genre) {
  var hidden = $('#qs-genre-hidden');
  if (!hidden) {
    hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.id = 'qs-genre-hidden';
    document.body.appendChild(hidden);
  }
  hidden.value = genre;
  _quickStartStep = 2;
  _renderQuickStartStep();
}

function quickStartConfirmPremise() {
  var textarea = $('#qs-premise');
  if (!textarea || !textarea.value.trim()) {
    showToast('请输入一句话梗概');
    return;
  }
  _setHidden('qs-premise-hidden', textarea.value.trim());
  var synopsis = $('#qs-synopsis');
  if (synopsis && synopsis.value.trim()) {
    _setHidden('qs-synopsis-hidden', synopsis.value.trim());
  }
  _quickStartStep = 3;
  _renderQuickStartStep();
}

function quickStartConfirmHook() {
  var textarea = $('#qs-hook');
  if (!textarea || !textarea.value.trim()) {
    showToast('请填写卖点（你的故事与同类作品的核心差异）');
    return;
  }
  _setHidden('qs-hook-hidden', textarea.value.trim());
  _quickStartStep = 4;
  _renderQuickStartStep();
}

function quickStartConfirmCharacters() {
  var prota = $('#qs-protagonist');
  var gf = $('#qs-goldfinger');
  var goals = $('#qs-goals');
  if (!prota || !prota.value.trim()) {
    showToast('请填写主角人设');
    return;
  }
  _setHidden('qs-protagonist-hidden', prota.value.trim());
  _setHidden('qs-goldfinger-hidden', gf ? gf.value.trim() : '');
  _setHidden('qs-goals-hidden', goals ? goals.value.trim() : '');
  _quickStartStep = 5;
  _renderQuickStartStep();
}

function _setHidden(id, value) {
  var hidden = document.getElementById(id);
  if (!hidden) {
    hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.id = id;
    document.body.appendChild(hidden);
  }
  hidden.value = value;
}

async function quickStartGenerate() {
  var genre = $('#qs-genre-hidden') ? $('#qs-genre-hidden').value : '末世';
  var premise = $('#qs-premise-hidden') ? $('#qs-premise-hidden').value : '';
  var hook = $('#qs-hook-hidden') ? $('#qs-hook-hidden').value : '';
  var protagonist = $('#qs-protagonist-hidden') ? $('#qs-protagonist-hidden').value : '';
  var goldfinger = $('#qs-goldfinger-hidden') ? $('#qs-goldfinger-hidden').value : '';
  var goals = $('#qs-goals-hidden') ? $('#qs-goals-hidden').value : '';
  if (!premise) { showToast('请输入梗概'); return; }
  closeQuickStart();
  showLoading();
  // 创建项目
  try {
    var fullSummary = premise;
    if (hook) fullSummary += ' 【卖点】' + hook;
    if (protagonist) fullSummary += ' 【主角】' + protagonist;
    if (goldfinger) fullSummary += ' 【金手指】' + goldfinger;
    var { ok, data } = await apiPost('/api/projects', {
      meta: {
        title: premise.substring(0, 12) + '...',
        genre: genre,
        summary: fullSummary,
        volumes_count: 5,
        total_chapters: 300,
      },
      from_demo: false,
    });
    hideLoading();
    if (ok && data && data.project) {
      saveProject(_normalizeProjectMeta(data.project));
      showToast('项目已创建，正在生成骨架...');
      // 先用内置模板生成骨架（后端 AI 生成端点暂未就绪时的 fallback）
      _generateSkeletonFromPremise(genre, premise, { hook: hook, protagonist: protagonist, goldfinger: goldfinger, goals: goals });
      await loadDesignData();
      updateDesignEmptyState();
      navigate('design');
    } else {
      showToast('创建项目失败，请重试');
    }
  } catch (e) {
    hideLoading();
    showToast('创建失败: ' + e.message);
  }
}

// 根据梗概生成骨架模板（不依赖 LLM，基于题材规则模板）
function _generateSkeletonFromPremise(genre, premise, extra = {}) {
  var templates = {
    '末世': [
      { title: '第一卷', range: '1-60章', subtitle: '灾变降临', summary: premise + ' 主角在灾变中觉醒能力，被迫面对末日初期的混乱。', tags: ['觉醒','逃亡','生存'] },
      { title: '第二卷', range: '61-120章', subtitle: '废墟秩序', summary: '主角建立据点，组建团队，在资源匮乏中确立领导地位。', tags: ['据点','团队','资源'] },
      { title: '第三卷', range: '121-180章', subtitle: '暗流涌动', summary: '外部势力介入，内部出现分歧，主角面临信任与利益考验。', tags: ['冲突','权谋','分裂'] },
      { title: '第四卷', range: '181-240章', subtitle: '进化之路', summary: '危机升级，主角必须向更危险的区域进发，实力大幅提升。', tags: ['进化','副本','Boss'] },
      { title: '第五卷', range: '241-300章', subtitle: '终极真相', summary: '幕后真相揭露，主角面临最终抉择，格局拉升至世界级。', tags: ['真相','决战','终章'] }
    ],
    '_default': [
      { title: '第一卷', range: '1-60章', subtitle: '起步篇', summary: premise + ' 主角获得金手指，初步展示能力。', tags: ['起步','金手指'] },
      { title: '第二卷', range: '61-120章', subtitle: '发展篇', summary: '主角在更大舞台展现实力，建立势力或人脉。', tags: ['发展','势力'] },
      { title: '第三卷', range: '121-180章', subtitle: '高潮篇', summary: '核心冲突爆发，主角面临最大挑战。', tags: ['高潮','冲突'] },
      { title: '第四卷', range: '181-240章', subtitle: '转折篇', summary: '格局升级，新的威胁出现，主角突破瓶颈。', tags: ['转折','升级'] },
      { title: '第五卷', range: '241-300章', subtitle: '终章', summary: '终极对决，主角达成目标，故事圆满收束。', tags: ['终章','圆满'] }
    ]
  };
  var volumes = templates[genre] || templates._default;

  // 生成细纲段（每10章一段）— 融入五步法数据
  var goalList = (extra.goals || '').split(/[→\->\n]/).map(function(s) { return s.trim(); }).filter(Boolean);
  var chapters = [];
  for (var i = 0; i < 30; i++) {
    var chNum = i * 10 + 1;
    var chEnd = chNum + 9;
    var volIdx = Math.floor(i / 6); // 6段 per volume
    var vol = volumes[volIdx] || volumes[volumes.length - 1];
    // 五步法：第1段填入 hook，前6段填入 goldfinger 信息
    var chHook = '';
    var chPleasure = '';
    var chExpectation = '';
    if (i === 0) {
      chHook = extra.hook ? '开篇钩子：' + extra.hook : '开篇钩子：前300字出冲突，金手指落地';
      chPleasure = extra.goldfinger ? '金手指首秀：' + extra.goldfinger.substring(0, 40) : '金手指首次展示';
      chExpectation = '读者期待：主角如何应对危机';
    } else if (i === 1) {
      chHook = '章末悬念：第一次危机升级';
      chPleasure = '爽点：金手指威力初显';
    } else if (i === 2) {
      chHook = '黄金三章收束：小闭环完成';
      chPleasure = '爽点：第一次打脸/逆袭';
      chExpectation = '读者期待：主角的真正潜力';
    }
    // 阶段目标映射
    var goalIdx = Math.min(i, goalList.length - 1);
    var goalText = goalList.length > 0 ? goalList[goalIdx] : vol.subtitle + '阶段目标';
    chapters.push({
      title: '第' + chNum + '-' + chEnd + '章',
      goal: goalText,
      conflict: '待细化',
      result: '待细化',
      hook: chHook,
      pleasure: chPleasure,
      foreshadowing: '',
      expectation: chExpectation,
      scenes: []
    });
  }

  // 保存到项目
  if (currentProject && currentProject.id) {
    var pid = currentProject.id;
    // 五步法：世界观自动衍生（从 premise + goldfinger 推导）
    var worldCore = premise;
    if (extra.hook) worldCore += ' 核心卖点：' + extra.hook;
    var worldPowers = extra.goldfinger || '待设定（建议：能力来源、升级路径、限制条件）';
    ProjectAPI.updateSkeleton(pid, {
      volumes: volumes,
      chapters: chapters,
    }).then(function() {
      // 生成世界观初稿
      return ProjectAPI.updateWorld(pid, {
        core: worldCore,
        powers: worldPowers,
      });
    }).then(function() {
      // 生成主角角色卡
      if (extra.protagonist) {
        return ProjectAPI.updateCharacters(pid, [{
          name: extra.protagonist.split('，')[0].substring(0, 10) || '主角',
          role: '主角',
          desc: extra.protagonist + (extra.goldfinger ? ' 金手指：' + extra.goldfinger : ''),
        }]).then(function(res) {
          if (!res) {
            showToast('骨架已生成，但角色卡创建失败，请稍后手动添加');
          } else {
            showToast('骨架已生成！点击粗纲查看，点击细纲编辑每段内容');
          }
          loadDesignData();
        });
      } else {
        showToast('骨架已生成！点击粗纲查看，点击细纲编辑每段内容');
        loadDesignData();
      }
    }).catch(function(err) {
      console.error('骨架生成失败:', err);
      showToast('骨架生成失败：' + (err.message || String(err)));
    });
  }
}
