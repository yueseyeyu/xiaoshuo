function saveTasks() {
  try {
    localStorage.setItem('xiaoshuo_tasks', JSON.stringify(tasks));
  } catch (e) {}
}
function loadTasks() {
  try {
    const raw = localStorage.getItem('xiaoshuo_tasks');
    if (raw) {
      const saved = JSON.parse(raw);
      if (Array.isArray(saved) && saved.length) {
        tasks = saved;
        // 对未完成的任务恢复轮询
        tasks.forEach((t) => {
          if (t.backendId && t.status !== 'completed' && t.status !== 'failed') {
            pollTaskStatus(t);
          }
        });
        return;
      }
    }
  } catch (e) {}
  tasks = (DATA.tasks || []).slice();
}
function renderTasks() {
  const grid = $('#task-grid');
  if (!grid) return;
  saveTasks();
  const pipeline = $('#disassembly-pipeline-station');
  const filtered = taskFilter === 'all' ? tasks : tasks.filter((t) => t.status === taskFilter);
  if (filtered.length === 0) {
    if (pipeline) pipeline.style.display = 'none';
    if (taskFilter !== 'all') {
      const filterLabels = { running: '进行中', completed: '已完成', failed: '失败' };
      grid.innerHTML = '<div class="empty-state">暂无' + (filterLabels[taskFilter] || taskFilter) + '任务</div>';
      $$('#task-filter-tabs .filter-tab').forEach((t) => t.classList.toggle('active', t.dataset.filter === taskFilter));
      return;
    }
    const hasQueue = tasks.length > 0;
    const wizardSteps = getWizardStepStates();
    const stepHtml = wizardSteps.map((s) =>
      '<div class="wizard-step ' + s.state + '" title="' + s.desc + '">' +
        '<span class="wizard-step-num">' + (s.state === 'completed' ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>' : s.num) + '</span>' +
        '<div class="wizard-step-body"><b>' + s.title + '</b><span>' + s.subtitle + '</span></div>' +
      '</div>'
    ).join('<div class="wizard-step-arrow"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg></div>');
    const primaryEmpty = DATA && DATA.books && DATA.books.length === 0 ? 'btn-secondary' : 'btn-primary';
    const secondaryEmpty = DATA && DATA.books && DATA.books.length === 0 ? 'btn-primary' : 'btn-secondary';
    const primaryLabel = DATA && DATA.books && DATA.books.length === 0 ? '去书库导入书籍' : '新建拆书任务';
    const primaryAction = DATA && DATA.books && DATA.books.length === 0 ? 'navigate(\'library\')' : 'openTaskModal()';
    const wizardTitle = hasQueue ? '继续拆书分析' : '开始你的第一次拆书分析';
    const wizardSubtitle = hasQueue
      ? '队列中已有 ' + tasks.length + ' 个任务 · 点击新建任务继续分析'
      : '拆书是把爆款小说拆解为可复用创作技法的核心流程';
    grid.innerHTML = '<div class="quick-start-wizard">' +
      '<div class="wizard-head">' +
        '<div class="wizard-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg></div>' +
        '<div><div class="wizard-title">' + wizardTitle + '</div><div class="wizard-subtitle">' + wizardSubtitle + '</div></div>' +
      '</div>' +
      '<div class="wizard-steps">' + stepHtml + '</div>' +
      '<div class="wizard-actions">' +
        '<button class="btn ' + primaryEmpty + '" onclick="' + primaryAction + '">' + primaryLabel + '</button>' +
        '<button class="btn ' + secondaryEmpty + '" onclick="loadDemoDisassembly()">查看示例《全球高武》</button>' +
      '</div>' +
      '<div class="wizard-tip">提示：拆书分析约需 10-30 分钟/本 · 当前 GPU 空闲</div>' +
    '</div>';
  } else {
    if (pipeline) pipeline.style.display = '';
    grid.innerHTML = filtered.map((t) => {
      const retryBtn = t.status === 'failed' ? '<button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();retryTask(\'' + t.id + '\')" style="margin-left:auto">重试</button>' : '';
      return '<div class="task-card">' +
        '<div class="task-header"><span class="task-type">' + t.typeLabel + '</span><span class="task-badge ' + t.status + '">' + statusLabel(t.status) + '</span>' + retryBtn + '</div>' +
        '<div class="task-meta">书籍：' + t.books.slice(0, 2).join('、') + (t.books.length > 2 ? ' 等' + t.books.length + '本' : '') + '</div>' +
        '<div class="task-progress"><div style="width:' + t.progress + '%"></div></div>' +
        '<div class="task-msg">' + t.message + '</div>' +
        '</div>';
    }).join('');
  }
  $$('#task-filter-tabs .filter-tab').forEach((t) => t.classList.toggle('active', t.dataset.filter === taskFilter));
}
function loadDemoDisassembly() {
  const demo = {
    id: 'demo-' + Date.now(),
    type: 'full',
    typeLabel: '拆书分析',
    books: ['《全球高武》'],
    genre: '末世',
    status: 'completed',
    progress: 100,
    message: '156 张技法卡 · 平均节奏 8.2 · 耗时 12 分钟'
  };
  tasks.push(demo);
  saveTasks();
  renderTasks();
  showToast('已加载《全球高武》示例拆书结果');
}
function openTaskModal() {
  $('#task-modal').classList.add('open');
  filterTaskBooks();
}
function closeTaskModal() {
  $('#task-modal').classList.remove('open');
}
function renderTaskBookChecklist() {
  const container = $('#task-book-checklist');
  if (!container || !DATA || !DATA.books) return;
  container.innerHTML = DATA.books.map((b, idx) => {
    return '<label class="book-checkbox"><input type="checkbox" class="task-book-check" value="' + idx + '"><span>' + escapeHtml(b.title) + '</span></label>';
  }).join('');
}
function filterTaskBooks() {
  const genre = $('#task-genre').value;
  $$('.book-checkbox').forEach((label) => {
    const input = label.querySelector('input');
    if (!input) return;
    const idx = Number(input.value);
    const book = DATA.books[idx];
    if (!book) { label.style.display = 'none'; return; }
    const show = genre === 'all' || book.genre === genre;
    label.style.display = show ? 'flex' : 'none';
  });
}
function initTaskTypeHandler() {
  const typeSelect = $('#task-type');
  if (!typeSelect) return;
  typeSelect.addEventListener('change', () => {
    const rangeRow = $('#task-range-row');
    if (!rangeRow) return;
    rangeRow.style.display = typeSelect.value === 'rhythm' ? '' : 'none';
  });
}
function startTask() {
  const type = $('#task-type').value;
  const checked = $$('.task-book-check:checked');
  const selectedBooks = checked.map((c) => DATA.books[Number(c.value)]).filter(Boolean);
  const titles = selectedBooks.map((b) => b.title);
  const files = selectedBooks.map((b) => b.file).filter(Boolean);
  if (selectedBooks.length === 0) {
    showToast('请至少选择一本书');
    return;
  }
  const rangeStart = $('#task-range-start').value || null;
  const rangeEnd = $('#task-range-end').value || null;
  createTask(type, titles, files, rangeStart, rangeEnd);
  closeTaskModal();
  navigate('disassembly');
  showToast('任务已创建');
}
async function createTask(type, titles, files, rangeStart, rangeEnd) {
  const label = TASK_TYPE_LABELS[type] || type;
  const rangeInfo = rangeStart ? ' (第' + rangeStart + '-' + (rangeEnd || '末') + '章)' : '';
  const localTask = {
    id: 'local-' + Date.now(),
    backendId: null,
    type: type,
    typeLabel: label + rangeInfo,
    books: titles,
    _files: files,
    status: 'queued',
    progress: 0,
    message: '排队中...',
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
  };
  tasks.unshift(localTask);
  renderTasks();

  const { ok, data, error } = await apiPost('/api/tasks', { type: type, books: files });
  if (ok && data && !data.error) {
    localTask.backendId = data.id;
    localTask.status = data.status || 'queued';
    pollTaskStatus(localTask);
  } else {
    localTask.status = 'failed';
    localTask.message = '提交失败：' + (error || (data && data.error) || '未知错误');
    renderTasks();
  }
}
function pollTaskStatus(task) {
  if (!task || !task.backendId) return;
  const cancel = poll(async () => {
    const { ok, data } = await apiGet('/api/task?id=' + task.backendId);
    if (!ok || !data) {
      task.status = 'failed';
      task.message = '轮询失败';
      renderTasks();
      return false;
    }
    if (data.error) {
      task.status = 'failed';
      task.message = data.error;
      renderTasks();
      return false;
    }
    task.status = data.status;
    task.progress = data.progress || 0;
    task.message = data.message || '';
    renderTasks();
    if (data.status === 'completed' || data.status === 'failed') {
      if (data.status === 'completed') {
        showToast('任务完成：' + task.typeLabel);
        loadApiData();
      }
      return false;
    }
    return true;
  }, 1500);
  registerPoll(cancel);
}
function retryTask(taskId) {
  const task = tasks.find(t => t.id === taskId);
  if (!task) return;
  task.status = 'queued';
  task.progress = 0;
  task.message = '排队中...';
  task.backendId = null;
  renderTasks();
  createTask(task.type, task.books, task._files || [], null, null);
  showToast('任务已重新排队');
}
