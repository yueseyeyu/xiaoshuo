// ============================================================
// API 客户端 — 统一 fetch 封装、超时、错误处理
// ============================================================

// API_BASE 可在外部通过 window.API_BASE 覆盖，默认同源部署
const API_BASE = (typeof window !== 'undefined' && window.API_BASE) || '';
const DEFAULT_TIMEOUT = 10000;
let lastApiErrorToast = 0;
const API_ERROR_TOAST_COOLDOWN = 5000;

/**
 * 统一请求封装
 * @param {string} path - API 路径（如 '/api/search'）
 * @param {object} options - fetch options
 * @param {number} timeoutMs - 超时毫秒
 * @returns {Promise<{ok: boolean, data: any, error: string|null, status: number}>}
 */
async function apiFetch(path, options = {}, timeoutMs = DEFAULT_TIMEOUT) {
  const url = API_BASE + path;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      const msg = `HTTP ${res.status}: ${text || res.statusText}`;
      notifyApiError(path, msg);
      return { ok: false, data: null, error: msg, status: res.status };
    }
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const data = await res.json();
      return { ok: true, data, error: null, status: res.status };
    }
    const text = await res.text();
    return { ok: true, data: text, error: null, status: res.status };
  } catch (err) {
    clearTimeout(timer);
    const msg = err.name === 'AbortError' ? '请求超时' : (err.message || '网络错误');
    notifyApiError(path, msg);
    return { ok: false, data: null, error: msg, status: 0 };
  }
}

function notifyApiError(path, msg) {
  // 静默上报类接口不弹 toast，避免轮询轰炸
  if (path && (path.startsWith('/api/logs/operations') || path.startsWith('/api/hardware'))) return;
  const now = Date.now();
  if (now - lastApiErrorToast < API_ERROR_TOAST_COOLDOWN) return;
  lastApiErrorToast = now;
  if (typeof showToast === 'function') showToast('[API 错误] ' + msg);
}

async function apiGet(path, timeoutMs) {
  return apiFetch(path, { method: 'GET' }, timeoutMs);
}

async function apiPost(path, body, timeoutMs) {
  return apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, timeoutMs);
}

/**
 * 轮询辅助：返回 cancel 函数，调用后停止轮询
 * @param {Function} fn - 每次执行的异步函数，返回 truthy 则继续轮询
 * @param {number} intervalMs
 * @param {number} timeoutMs - 单次 fn 执行超时
 */
function poll(fn, intervalMs = 1000, timeoutMs = DEFAULT_TIMEOUT) {
  let cancelled = false;
  let timer = null;

  async function tick() {
    if (cancelled) return;
    try {
      const shouldContinue = await fn();
      if (!shouldContinue || cancelled) return;
    } catch (e) {
      console.error('[poll] error', e);
    }
    timer = setTimeout(tick, intervalMs);
  }

  tick();

  return function cancel() {
    cancelled = true;
    if (timer) clearTimeout(timer);
  };
}

// 兼容旧代码：保留 fetch 直接调用能力，但新增 API 均通过 apiFetch
