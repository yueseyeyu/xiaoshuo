"use strict";

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
  const exitDemoBtn = $('#exit-demo-btn');
  if (exitDemoBtn) exitDemoBtn.style.display = (hasProject && isDemoProject(currentProject)) ? '' : 'none';
  const pageTitle = $('#dashboard-page-title');
  const fab = $('#continue-writing-fab');
  const fabMeta = $('#fab-meta');
  if (hasProject) {
    if (pageTitle) pageTitle.textContent = '工作台· ' + (currentProject.title || '未命名作品');
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
    if (fab) fab.style.display = '';
    if (fabMeta) fabMeta.textContent = '第' + (currentProject.writtenChapters + 1 || 1) + '章';
  } else {
    if (pageTitle) pageTitle.textContent = '工作台';
    $('#dashboard-subtitle').textContent = '当前无进行中的项目';
    if (fab) fab.style.display = 'none';
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
  const modal = $('#create-project-modal');
  if (modal) modal.classList.remove('open');
}

async function confirmCreateProject() {
  const title = $('#cp-title').value.trim();
  if (!title) { showToast('请输入作品名称'); return; }
  const genre = $('#cp-genre').value || '末世';
  const volumes = parseInt($('#cp-volumes').value) || 5;
  const chapters = parseInt($('#cp-chapters').value) || 300;
  const result = await ProjectAPI.create({
    meta: {
      title: '《' + title.replace(/《|》/g, '') + '》',
      author: '作者',
      genre: genre,
      volumes_count: volumes,
      total_chapters: chapters,
      written_chapters: 0,
      summary: '',
    }
  });
  if (result && result.project) {
    saveProject(result.project);
    closeCreateProjectModal();
    showToast('已创建作品 ' + title);
    // 创建后引导
    setTimeout(() => {
      showToast('下一步：在书库中导入参考书，或在设计页规划粗纲');
    }, 2800);
  } else {
    showToast('创建作品失败');
  }
}

async function loadDemoProject() {
  clearToasts();
  showToast('正在加载示例项目，请稍候...', 0);
  try {
    // 优先复用已存在的示例项目，避免重复创建
    const list = await ProjectAPI.list({ include_demo: true });
    const demo = list && list.projects && list.projects.find(p => p.is_demo);
    if (demo) {
      const project = await ProjectAPI.get(demo.id);
      clearToasts();
      if (project && project.meta) {
        saveProject(project);
        showToast('已加载示例项目');
        return;
      }
    }
    // 没有示例项目时才创建
    const result = await ProjectAPI.createFromDemo();
    clearToasts();
    if (result && result.project) {
      saveProject(result.project);
      showToast('已加载示例项目');
    } else {
      showToast('加载示例项目失败：接口未返回项目数据');
    }
  } catch (e) {
    clearToasts();
    console.error('loadDemoProject failed', e);
    showToast('加载示例项目失败：' + (e.message || '网络超时'));
  }
}

async function exitDemoProject() {
  const demoId = currentProject && currentProject.id;
  setCurrentProject(null);
  if (demoId) {
    try { await ProjectAPI.delete(demoId); } catch (e) { console.error('delete demo failed', e); }
  }
  showToast('已退出示例项目');
}
