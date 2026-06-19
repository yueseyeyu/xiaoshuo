/**
 * API 客户端封装
 */
const API_BASE = "";

async function request(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    const data = await res.json().catch(() => ({ ok: false, error: "Invalid JSON" }));
    return { status: res.status, ...data };
}

export const api = {
    progress: (genre = "末世") => request(`/api/progress?genre=${encodeURIComponent(genre)}`),
    hardware: () => request("/api/hardware"),
    status: () => request("/api/status"),
    logs: () => request("/api/logs"),
    book: (name, genre = "末世") => request(`/api/book/${encodeURIComponent(name)}?genre=${encodeURIComponent(genre)}`),
    score: (name, genre = "末世") => request(`/api/score/${encodeURIComponent(name)}?genre=${encodeURIComponent(genre)}`),
    // start may take 30-120s if LLM auto-start is needed
    startup: () => request("/api/startup-status"),
    // start may take 30-120s if LLM auto-start is needed
    start: (genre = "末世", books = []) => request("/api/start", {
        method: "POST",
        body: JSON.stringify({ genre, books }),
        signal: AbortSignal.timeout(180000),
    }),
    stop: () => request("/api/stop", {
        method: "POST",
        body: JSON.stringify({}),
    }),
};
