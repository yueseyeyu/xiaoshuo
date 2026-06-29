"use strict";

// ============================================================
// 日志管理页面 v7.6
// ============================================================
const LOGS_PAGE_SIZE = 50;
let logsCurrentPage = 0;
let logsTotalCount = 0;

function initLogsPage() {
  logsCurrentPage = 0;
  loadLogDates();
  refreshLogs();
}

async function loadLogDates() {
  const { ok, data: dates } = await apiGet('/api/logs/dates');
  if (!ok || !dates) {
    console.error('[Logs] 加载日期失败');
    return;
  }
  var sel = $('#logs-date');
  if (!sel) return;
  var cat = $('#logs-category');
  var catVal = cat ? cat.value : 'access';
  var list = dates[catVal] || [];
  sel.innerHTML = '<option value="">全部日期</option>' +
    list.map(function(d) { return '<option value="' + d + '">' + d + '</option>'; }).join('');
}

async function refreshLogs() {
  var cat = $('#logs-category');
  var date = $('#logs-date');
  var level = $('#logs-level');
  var search = $('#logs-search');
  var catVal = cat ? cat.value : 'access';
  var dateVal = date ? date.value : '';
  var levelVal = level ? level.value : '';
  var searchVal = search ? search.value.trim() : '';

  var params = 'category=' + encodeURIComponent(catVal) +
    '&offset=' + (logsCurrentPage * LOGS_PAGE_SIZE) +
    '&limit=' + LOGS_PAGE_SIZE;
  if (dateVal) params += '&date=' + encodeURIComponent(dateVal);
  if (levelVal) params += '&level=' + encodeURIComponent(levelVal);
  if (searchVal) params += '&search=' + encodeURIComponent(searchVal);

  var tbody = $('#logs-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="logs-empty">加载中...</td></tr>';

  var t0 = performance.now();
  const { ok, data, error } = await apiGet('/api/logs?' + params);
  if (ok && data) {
    var dt = Math.round(performance.now() - t0);
    var queryTime = $('#logs-query-time');
    if (queryTime) queryTime.textContent = dt;
    renderLogsTable(data, catVal);
  } else {
    console.error('[Logs] 加载失败', error);
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="logs-empty">加载失败：' + escapeHtml(error || '未知错误') + '</td></tr>';
  }
}

function renderLogsTable(data, category) {
  var tbody = $('#logs-tbody');
  var totalEl = $('#logs-total');
  var prevBtn = $('#logs-prev');
  var nextBtn = $('#logs-next');
  var pageInfo = $('#logs-page-info');

  logsTotalCount = data.total || 0;
  if (totalEl) totalEl.textContent = logsTotalCount;

  var totalPages = Math.ceil(logsTotalCount / LOGS_PAGE_SIZE);
  if (prevBtn) prevBtn.disabled = logsCurrentPage <= 0;
  if (nextBtn) nextBtn.disabled = logsCurrentPage >= totalPages - 1;
  if (pageInfo) pageInfo.textContent = '第 ' + (logsCurrentPage + 1) + ' / ' + Math.max(1, totalPages) + ' 页';

  var entries = data.entries || [];
  if (!tbody) return;

  if (entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="logs-empty">暂无日志记录</td></tr>';
    return;
  }

  if (category === 'access') {
    tbody.innerHTML = entries.map(function(e, i) {
      var statusClass = e.status >= 400 ? 'logs-status-err' : (e.status >= 300 ? 'logs-status-warn' : 'logs-status-ok');
      var methodClass = e.method === 'POST' ? 'logs-method-post' : 'logs-method-get';
      return '<tr>' +
        '<td>' + (e.timestamp || '') + '</td>' +
        '<td><span class="logs-method-badge ' + methodClass + '">' + escapeHtml(e.method || '') + '</span></td>' +
        '<td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;">' + escapeHtml(e.path || '') + '</td>' +
        '<td class="' + statusClass + '">' + (e.status || 200) + '</td>' +
        '<td>' + (e.duration_ms != null ? e.duration_ms + 'ms' : '-') + '</td>' +
        '<td><button class="logs-detail-btn" onclick="openLogDetail(' + i + ')">详情</button></td>' +
      '</tr>';
    }).join('');
    // 缓存当前页数据，供详情弹窗使用
    window._logsCache = entries;
  } else {
    // 用户操作日志
    tbody.innerHTML = entries.map(function(e, i) {
      return '<tr>' +
        '<td>' + (e.timestamp || '') + '</td>' +
        '<td><span class="logs-method-badge logs-method-post">OP</span></td>' +
        '<td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;">' + escapeHtml(e.action || '') + '</td>' +
        '<td class="logs-status-ok">-</td>' +
        '<td>-</td>' +
        '<td><button class="logs-detail-btn" onclick="openLogDetail(' + i + ')">详情</button></td>' +
      '</tr>';
    }).join('');
    window._logsCache = entries;
  }
}

function logsPrevPage() {
  if (logsCurrentPage > 0) {
    logsCurrentPage--;
    refreshLogs();
  }
}

function logsNextPage() {
  var totalPages = Math.ceil(logsTotalCount / LOGS_PAGE_SIZE);
  if (logsCurrentPage < totalPages - 1) {
    logsCurrentPage++;
    refreshLogs();
  }
}

function openLogDetail(index) {
  var entry = (window._logsCache || [])[index];
  if (!entry) return;

  var title = $('#log-detail-title');
  var body = $('#log-detail-body');
  var modal = $('#log-detail-modal');
  if (!body || !modal) return;

  if (title) title.textContent = '日志详情 — ' + (entry.timestamp || '');

  var html = '';
  html += '<div class="logs-detail-section"><h4>基本信息</h4>';
  html += '<div class="logs-detail-row"><span class="logs-detail-label">时间</span><span class="logs-detail-value">' + escapeHtml(entry.timestamp || '-') + '</span></div>';
  html += '<div class="logs-detail-row"><span class="logs-detail-label">客户端</span><span class="logs-detail-value">' + escapeHtml(entry.client_ip || '-') + '</span></div>';
  html += '<div class="logs-detail-row"><span class="logs-detail-label">方法</span><span class="logs-detail-value">' + escapeHtml(entry.method || '-') + '</span></div>';
  html += '<div class="logs-detail-row"><span class="logs-detail-label">路径</span><span class="logs-detail-value">' + escapeHtml(entry.path || entry.action || '-') + '</span></div>';
  html += '<div class="logs-detail-row"><span class="logs-detail-label">状态</span><span class="logs-detail-value">' + (entry.status != null ? entry.status : '-') + '</span></div>';
  html += '<div class="logs-detail-row"><span class="logs-detail-label">耗时</span><span class="logs-detail-value">' + (entry.duration_ms != null ? entry.duration_ms + 'ms' : '-') + '</span></div>';
  html += '</div>';

  if (entry.params && Object.keys(entry.params).length > 0) {
    html += '<div class="logs-detail-section"><h4>请求参数</h4>';
    html += '<div class="logs-detail-json">' + escapeHtml(JSON.stringify(entry.params, null, 2)) + '</div>';
    html += '</div>';
  }

  if (entry.req_body) {
    html += '<div class="logs-detail-section"><h4>请求体</h4>';
    html += '<div class="logs-detail-json">' + escapeHtml(JSON.stringify(entry.req_body, null, 2)) + '</div>';
    html += '</div>';
  }

  if (entry.detail && Object.keys(entry.detail).length > 0) {
    html += '<div class="logs-detail-section"><h4>操作详情</h4>';
    html += '<div class="logs-detail-json">' + escapeHtml(JSON.stringify(entry.detail, null, 2)) + '</div>';
    html += '</div>';
  }

  body.innerHTML = html;
  modal.style.display = 'flex';
}

function closeLogDetailModal() {
  var modal = $('#log-detail-modal');
  if (modal) modal.style.display = 'none';
}
