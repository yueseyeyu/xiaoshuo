// ============================================================
// 工作台 / 项目卡片
// ============================================================
function renderDashboardProject() {
  const hasProject = !!currentProject;
  const hero = $('#hero-has-project');
  const empty = $('#hero-empty-state');
  const sidebar = $('.dashboard-sidebar');
  const pipeline = $('.pipeline-station');
  const section = $('.dashboard-section');
  const kpiRow = $('.library-kpi-row');
  const stageBar = $('#creative-stage-bar');
  const workstation = $('#dashboard-workstation');
  if (hero) hero.style.display = hasProject ? '' : 'none';
  if (empty) empty.style.display = hasProject ? 'none' : '';
  if (sidebar) sidebar.style.display = hasProject ? '' : 'none';
  if (pipeline) pipeline.style.display = hasProject ? '' : 'none';
  if (section) section.style.display = hasProject ? '' : 'none';
  if (kpiRow) kpiRow.style.display = hasProject ? '' : 'none';
  if (stageBar) stageBar.style.display = hasProject ? '' : 'none';
  if (workstation) workstation.style.gridTemplateColumns = hasProject ? '' : '1fr';
  if (hasProject) {
    $('#hero-title').textContent = currentProject.title || '未命名作品';
    $('#hero-greeting').textContent = greetingByHour() + '，' + (currentProject.author || '作者');
    $('#hero-volumes').textContent = currentProject.volumes || 0;
    $('#hero-chapters').textContent = currentProject.totalChapters || 0;
    $('#hero-genre').textContent = currentProject.genre || '未设置';
    $('#hero-stat-chapters').textContent = currentProject.writtenChapters || 0;
    const progress = currentProject.totalChapters ? Math.round((currentProject.writtenChapters || 0) / currentProject.totalChapters * 100) : 0;
    $('#hero-stat-progress').textContent = progress + '%';
    $('#hero-stat-cards').textContent = currentProject.cards || 0;
    $('#dashboard-subtitle').textContent = currentProject.genre ? (currentProject.genre + ' · ' + (currentProject.writtenChapters || 0) + '/' + (currentProject.totalChapters || 0) + ' 章') : '项目信息待完善';
  } else {
    $('#dashboard-subtitle').textContent = '当前无进行中的项目';
  }
}

function greetingByHour() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

function createProject() {
  $('#cp-title').value = '';
  $('#cp-genre').value = '末世';
  $('#cp-volumes').value = 5;
  $('#cp-chapters').value = 300;
  $('#cp-desc').value = '';
  $('#create-project-modal').classList.add('open');
}

function closeCreateProjectModal() {
  $('#create-project-modal').classList.remove('open');
}

function confirmCreateProject() {
  const title = $('#cp-title').value.trim();
  if (!title) { showToast('请输入作品名称'); return; }
  const genre = $('#cp-genre').value || '末世';
  const volumes = parseInt($('#cp-volumes').value) || 5;
  const chapters = parseInt($('#cp-chapters').value) || 300;
  saveProject({
    title: '《' + title.replace(/《|》/g, '') + '》',
    author: '作者',
    genre: genre,
    volumes: volumes,
    totalChapters: chapters,
    writtenChapters: 0,
    cards: 0,
    createdAt: new Date().toISOString()
  });
  closeCreateProjectModal();
  showToast('已创建作品 ' + title);
  renderDashboardProject();
  // 创建后引导
  setTimeout(() => {
    showToast('下一步：在书库中导入参考书，或在设计页规划粗纲');
  }, 2800);
}

function loadDemoProject() {
  saveProject({
    title: '《末日模拟器》',
    author: '作者',
    genre: '末世',
    volumes: 5,
    totalChapters: 300,
    writtenChapters: 127,
    cards: 156,
    createdAt: new Date().toISOString()
  });
  showToast('已加载示例项目');
}
