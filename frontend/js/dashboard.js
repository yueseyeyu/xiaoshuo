/**
 * 拆书控制台渲染与交互
 */
import { api } from "./api.js";
import { state } from "./state.js";

const els = {
    bookQueue: document.getElementById("bookQueue"),
    genreSelect: document.getElementById("genreSelect"),
    selectAllBtn: document.getElementById("selectAllBtn"),
    selectNoneBtn: document.getElementById("selectNoneBtn"),
    selectionCount: document.getElementById("selectionCount"),
    powerBtn: document.getElementById("powerBtn"),
    powerText: document.getElementById("powerText"),
    powerIcon: document.getElementById("powerIcon"),
    statDone: document.getElementById("statDone"),
    statRunning: document.getElementById("statRunning"),
    statPending: document.getElementById("statPending"),
    globalStatusDot: document.getElementById("globalStatusDot"),
    globalStatusText: document.getElementById("globalStatusText"),
    confirmModal: document.getElementById("confirmModal"),
    cancelStopBtn: document.getElementById("cancelStopBtn"),
    confirmStopBtn: document.getElementById("confirmStopBtn"),
    // P1/P3: Pipeline progress
    pipelineProgress: document.getElementById("pipelineProgress"),
    pipelineStageName: document.getElementById("pipelineStageName"),
    pipelineStageNum: document.getElementById("pipelineStageNum"),
    pipelineStagePct: document.getElementById("pipelineStagePct"),
    pipelineFill: document.getElementById("pipelineFill"),
    pipelineSteps: document.getElementById("pipelineSteps"),
    pipelineMeta: document.getElementById("pipelineMeta"),
    pipelineCompleted: document.getElementById("pipelineCompleted"),
    pipelineCompletedList: document.getElementById("pipelineCompletedList"),
    pipelineError: document.getElementById("pipelineError"),
};

// P1: Stage display name mapping
const STAGE_NAMES = {
    "book_processor": "入库处理",
    "rhythm_analyzer": "拆书节奏分析",
    "rhythm_auditor": "节奏数据质检",
    "genre_synthesizer": "题材评分合成",
    "score_auditor": "评分数据质检",
    "quality_gate": "品质关卡",
    "creative_bridge": "创作桥接",
    "recursive_summarize": "递归摘要",
    "cross_book_synthesis": "跨书合成",
    "writing_instructions": "写作指令",
};

const PIPELINE_STAGES = [
    "book_processor",
    "rhythm_analyzer",
    "genre_synthesizer",
    "quality_gate",
    "creative_bridge",
    "recursive_summarize",
    "cross_book_synthesis",
    "writing_instructions",
];

let onStopConfirm = null;

function showToast(message, type = "info", action = null) {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    if (action) {
        const btn = document.createElement("button");
        btn.className = "toast-action";
        btn.textContent = action.label;
        btn.addEventListener("click", action.onClick);
        toast.appendChild(btn);
    }
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 250);
    }, type === "error" ? 8000 : 4000);
}

function setLoading(loading) {
    els.powerBtn.disabled = loading;
    if (loading) {
        els.powerBtn.classList.add("loading");
    } else {
        els.powerBtn.classList.remove("loading");
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function getProgressPct(done, total) {
    if (typeof total !== "number" || total <= 0) return 0;
    return Math.min(100, Math.round((done / total) * 100));
}

function renderBookCard(book) {
    const isSelected = state.selected.has(book.name);
    const l1Pct = getProgressPct(book.l1_done, book.l1_total);
    // P2: use real l2_total from backend instead of deriving from l1_done
    const l2Total = typeof book.l2_total === "number" && book.l2_total > 0 ? book.l2_total : Math.max(1, Math.ceil(book.l1_total / 5));
    const l2Pct = getProgressPct(book.l2_done, l2Total);
    const l3Pct = book.l3_done ? 100 : 0;

    const cls = ["book-card"];
    if (isSelected) cls.push("selected");
    if (book.is_complete) cls.push("done");
    if (book.status === "running") cls.push("running");
    if (state.running) cls.push("disabled");

    return `
        <div class="${cls.join(" ")}" data-name="${escapeHtml(book.name)}">
            <div class="book-checkbox"></div>
            <div class="book-info">
                <div class="book-name">${escapeHtml(book.name)}</div>
                <div class="book-status">${escapeHtml(book.status_text)}</div>
            </div>
            <div class="book-progress">
                <div class="progress-bars">
                    <div class="progress-row">
                        <span class="progress-label">L1</span>
                        <div class="progress-track"><div class="progress-fill l1" style="width:${l1Pct}%"></div></div>
                        <span class="progress-pct">${l1Pct}%</span>
                    </div>
                    <div class="progress-row">
                        <span class="progress-label">L2</span>
                        <div class="progress-track"><div class="progress-fill l2" style="width:${l2Pct}%"></div></div>
                        <span class="progress-pct">${l2Pct}%</span>
                    </div>
                    <div class="progress-row">
                        <span class="progress-label">L3</span>
                        <div class="progress-track"><div class="progress-fill l3" style="width:${l3Pct}%"></div></div>
                        <span class="progress-pct">${l3Pct}%</span>
                    </div>
                </div>
            </div>
        </div>
    `;
}

export function renderBooks() {
    if (state.books.length === 0) {
        els.bookQueue.innerHTML = `
            <div class="empty-state">
                <div class="empty-title">暂无书籍</div>
                <div class="empty-desc">请选择题材，或确认 data/raw/novels/ 目录存在 TXT 文件</div>
            </div>
        `;
        return;
    }
    els.bookQueue.innerHTML = state.books.map(renderBookCard).join("");

    // Bind card clicks
    els.bookQueue.querySelectorAll(".book-card").forEach(card => {
        card.addEventListener("click", (e) => {
            if (state.running) return; // 运行中禁止选择
            const name = card.dataset.name;
            if (card.classList.contains("done")) {
                // P2: open detail view for completed books
                openBookDetail(name);
                return;
            }
            state.toggleBook(name);
            renderBooks();
            updatePowerButton();
        });
    });
}

export function updateStats() {
    const done = state.books.filter(b => b.is_complete).length;
    const running = state.books.filter(b => b.status === "running").length;
    const pending = state.books.length - done - running;
    els.statDone.textContent = done;
    els.statRunning.textContent = running;
    els.statPending.textContent = pending;
}

export function updatePowerButton() {
    const hasSelection = state.selected.size > 0;
    els.powerBtn.disabled = !state.running && !hasSelection;
    els.selectionCount.textContent = `已选 ${state.selected.size} 本`;

    if (state.running) {
        els.powerBtn.classList.add("running");
        els.powerText.textContent = "停止拆书";
        els.powerIcon.classList.add("running");
    } else {
        els.powerBtn.classList.remove("running");
        els.powerText.textContent = "启动拆书";
        els.powerIcon.classList.remove("running");
    }
}

export function updateGlobalStatus() {
    els.globalStatusDot.classList.remove("active", "running", "alert");
    if (state.alerts.length > 0) {
        els.globalStatusDot.classList.add("alert");
        els.globalStatusText.textContent = "硬件告警";
    } else if (state.running) {
        els.globalStatusDot.classList.add("running");
        els.globalStatusText.textContent = "拆书进行中";
    } else {
        els.globalStatusDot.classList.add("active");
        els.globalStatusText.textContent = "就绪";
    }
}

export async function refreshProgress() {
    try {
        const res = await api.progress(state.genre);
        if (!res.ok) {
            showToast(`加载书籍失败: ${res.error || "未知错误"}`, "error");
            return;
        }
        state.books = res.data;
        renderBooks();
        updateStats();
    } catch (e) {
        showToast("网络异常，无法获取书籍进度", "error");
    }
}

export async function refreshStatus() {
    try {
        const res = await api.status();
        if (res.ok) {
            state.running = res.data.running;
            state.pipelineStage = res.data.pipeline_stage || null;
            // If startup is in progress, don't override the startup progress display
            if (startupTimer) return;
            updatePowerButton();
            updateGlobalStatus();
            renderPipelineProgress();
        } else {
            showToast(`状态同步失败: ${res.error || "未知错误"}`, "error");
        }
    } catch (e) {
        showToast("网络异常，无法同步运行状态", "error");
    }
}

export function renderPipelineProgress() {
    const stage = state.pipelineStage;
    if (!stage || !state.running) {
        els.pipelineProgress.style.display = "none";
        return;
    }
    els.pipelineProgress.style.display = "block";

    // Current stage display name
    const displayName = STAGE_NAMES[stage.stage] || stage.stage;
    els.pipelineStageName.textContent = displayName;
    els.pipelineStageNum.textContent = `${stage.stage_num || "?"}/${stage.total || "?"}`;

    // P3: combine stage position (0..100 over whole pipeline) with intra-stage percent
    const totalStages = PIPELINE_STAGES.length;
    const currentIdx = PIPELINE_STAGES.indexOf(stage.stage);
    const stagePercent = typeof stage.percent === "number" ? stage.percent : 0;
    const pct = currentIdx >= 0
        ? Math.round(((currentIdx + stagePercent / 100) / totalStages) * 100)
        : stagePercent;
    els.pipelineFill.style.width = `${pct}%`;
    els.pipelineStagePct.textContent = `${stagePercent}%`;

    // P3: ETA / current book / current task
    const metaParts = [];
    if (stage.current_book) {
        metaParts.push(`当前书籍: ${stage.current_book}`);
    }
    if (stage.current_task) {
        metaParts.push(stage.current_task);
    }
    if (typeof stage.eta_seconds === "number" && stage.eta_seconds > 0) {
        const m = Math.floor(stage.eta_seconds / 60);
        const s = stage.eta_seconds % 60;
        metaParts.push(`预计剩余: ${m}分${s}秒`);
    }
    els.pipelineMeta.innerHTML = metaParts.map(p => `<span class="pipeline-meta-item">${escapeHtml(p)}</span>`).join("");

    // P3: completed books
    const completed = Array.isArray(stage.completed_books) ? stage.completed_books : [];
    if (completed.length) {
        els.pipelineCompleted.style.display = "block";
        els.pipelineCompletedList.innerHTML = completed.map(b => `<span class="pipeline-completed-chip">${escapeHtml(b)}</span>`).join("");
    } else {
        els.pipelineCompleted.style.display = "none";
    }

    // P3: error state
    if (stage.status === "error") {
        els.pipelineError.style.display = "block";
        els.pipelineError.textContent = stage.current_task || "管线异常";
        els.pipelineError.classList.add("visible");
    } else {
        els.pipelineError.style.display = "none";
        els.pipelineError.textContent = "";
        els.pipelineError.classList.remove("visible");
    }

    // Render step dots
    els.pipelineSteps.innerHTML = PIPELINE_STAGES.map((s, i) => {
        let cls = "pipeline-step-dot";
        if (s === stage.stage) cls += " active";
        else if (i < currentIdx) cls += " done";
        return `<span class="${cls}" title="${STAGE_NAMES[s] || s}"></span>`;
    }).join("");
}

export function showConfirmModal(onConfirm) {
    onStopConfirm = onConfirm;
    els.confirmModal.classList.add("open");
}

function hideConfirmModal() {
    els.confirmModal.classList.remove("open");
    onStopConfirm = null;
}

// Event bindings
els.genreSelect.addEventListener("change", (e) => {
    state.genre = e.target.value;
    state.selectNone();
    refreshProgress();
    updatePowerButton();
});

els.selectAllBtn.addEventListener("click", () => {
    if (state.running) { showToast("运行中禁止修改选择", "warning"); return; }
    state.selectAll();
    renderBooks();
    updatePowerButton();
});

els.selectNoneBtn.addEventListener("click", () => {
    if (state.running) { showToast("运行中禁止修改选择", "warning"); return; }
    state.selectNone();
    renderBooks();
    updatePowerButton();
});

let lastStartArgs = null; // 保存上次启动参数，用于重试
let startupTimer = null;    // 启动状态轮询定时器

els.powerBtn.addEventListener("click", async () => {
    if (state.running) {
        showConfirmModal(async () => {
            setLoading(true);
            stopStartupPolling();
            const res = await api.stop();
            setLoading(false);
            if (res.ok) {
                state.running = false;
                updatePowerButton();
                updateGlobalStatus();
                renderPipelineProgress();
                showToast(res.message || "已停止拆书", "info");
            } else {
                showToast(res.message || "停止失败", "error", {
                    label: "重试",
                    onClick: () => els.powerBtn.click(),
                });
            }
            hideConfirmModal();
        });
    } else {
        if (state.selected.size === 0) {
            showToast("请先选择要分析的书籍", "warning");
            return;
        }
        setLoading(true);
        const selectedBooks = Array.from(state.selected);
        lastStartArgs = { genre: state.genre, books: selectedBooks };
        els.powerText.textContent = "启动中...";
        const res = await api.start(state.genre, selectedBooks);
        setLoading(false);
        if (res.ok) {
            showStartupProgress();
            startStartupPolling();
        } else {
            updatePowerButton();
            showToast(res.message || "启动失败", "error", {
                label: "重试",
                onClick: () => retryStart(),
            });
        }
    }
});

function retryStart() {
    if (!lastStartArgs) return;
    els.powerText.textContent = "重试中...";
    setLoading(true);
    stopStartupPolling();
    api.start(lastStartArgs.genre, lastStartArgs.books).then(res => {
        setLoading(false);
        if (res.ok) {
            showStartupProgress();
            startStartupPolling();
        } else {
            updatePowerButton();
            showToast(res.message || "重试失败", "error", {
                label: "查看日志",
                onClick: () => window.open("/api/logs", "_blank"),
            });
        }
    });
}

function showStartupProgress() {
    els.pipelineProgress.style.display = "block";
    els.pipelineStageName.textContent = "服务启动";
    els.pipelineStageNum.textContent = "";
    els.pipelineStagePct.textContent = "0%";
    els.pipelineFill.style.width = "5%";
    els.pipelineMeta.innerHTML = "";
    els.pipelineSteps.innerHTML = "";
    els.pipelineCompleted.style.display = "none";
    els.pipelineError.style.display = "none";
}

function startStartupPolling() {
    stopStartupPolling();
    startupTimer = setInterval(async () => {
        try {
            const res = await api.startup();
            if (!res.ok) return;
            const ss = res.data;
            if (!ss) return;
            els.pipelineFill.style.width = `${ss.progress}%`;
            els.pipelineStagePct.textContent = `${ss.progress}%`;
            els.pipelineStageName.textContent = ss.status === "waiting_llm" ? "模型加载" : "服务启动";
            els.pipelineMeta.innerHTML = ss.message
                ? `<span class="pipeline-meta-item">${escapeHtml(ss.message)}</span>`
                : "";

            if (ss.status === "error") {
                stopStartupPolling();
                state.running = false;
                updatePowerButton();
                updateGlobalStatus();
                els.pipelineError.style.display = "block";
                els.pipelineError.textContent = ss.error || ss.message;
                els.pipelineError.classList.add("visible");
                showToast(ss.message || "启动失败", "error", {
                    label: "重试",
                    onClick: () => retryStart(),
                });
            } else if (ss.status === "running") {
                stopStartupPolling();
                state.running = true;
                updatePowerButton();
                updateGlobalStatus();
                showToast(ss.message || "已启动拆书", "info");
                // hide startup progress, let normal pipeline take over
                els.pipelineProgress.style.display = "none";
                refreshStatus();
            }
        } catch (e) {
            // ignore polling errors
        }
    }, 1000);
}

function stopStartupPolling() {
    if (startupTimer) {
        clearInterval(startupTimer);
        startupTimer = null;
    }
}

els.cancelStopBtn.addEventListener("click", hideConfirmModal);
els.confirmStopBtn.addEventListener("click", () => {
    if (onStopConfirm) onStopConfirm();
});
els.confirmModal.addEventListener("click", (e) => {
    if (e.target === els.confirmModal) hideConfirmModal();
});

// P2: Book detail panel
const detailEls = {
    modal: document.getElementById("bookDetailModal"),
    bookName: document.getElementById("detailBookName"),
    content: document.getElementById("detailContent"),
    closeBtn: document.getElementById("closeDetailBtn"),
    tabs: document.querySelectorAll(".detail-tab"),
    scoreBtn: document.getElementById("scoreBtn"),
};

const scoreEls = {
    modal: document.getElementById("scoreModal"),
    bookName: document.getElementById("scoreBookName"),
    body: document.getElementById("scoreBody"),
    closeBtn: document.getElementById("closeScoreBtn"),
};

let currentDetailBook = null;
let currentDetailData = null;
let currentDetailTab = "l3";

function safeJoin(arr, sep = ", ") {
    if (!Array.isArray(arr)) return "--";
    return arr.map(x => (typeof x === "string" ? x : JSON.stringify(x))).join(sep) || "--";
}

function renderL3(l3) {
    const summary = l3.book_summary || "暂无全书摘要";
    const structure = l3.structure_pattern || "--";
    const theme = l3.theme_evolution || "--";
    const insights = Array.isArray(l3.writing_insights) ? l3.writing_insights : [];
    const arcs = Array.isArray(l3.character_arcs) ? l3.character_arcs : [];
    const narrative = l3.narrative_rhythm || {};
    const hookSys = l3.hook_system || {};
    const commercial = l3.commercial_assessment || {};

    return `
        <div class="detail-section">
            <h4>全书摘要</h4>
            <p class="detail-para">${escapeHtml(summary)}</p>
        </div>
        <div class="detail-grid">
            <div class="detail-section"><h4>结构模式</h4><p>${escapeHtml(structure)}</p></div>
            <div class="detail-section"><h4>主题深化</h4><p>${escapeHtml(theme)}</p></div>
        </div>
        <div class="detail-section">
            <h4>角色弧光</h4>
            ${arcs.length ? arcs.map(a => `
                <div class="detail-item">
                    <span class="detail-key">${escapeHtml(a.name || "角色")}</span>
                    <span class="detail-value">${escapeHtml(a.full_arc || "--")}</span>
                </div>
            `).join("") : "<p>暂无角色弧光数据</p>"}
        </div>
        <div class="detail-grid">
            <div class="detail-section">
                <h4>叙事节奏</h4>
                <div class="detail-item"><span class="detail-key">模式</span><span class="detail-value">${escapeHtml(narrative.pattern || "--")}</span></div>
                <div class="detail-item"><span class="detail-key">平均钩子间隔</span><span class="detail-value">${escapeHtml(narrative.avg_hook_gap || "--")}</span></div>
                <div class="detail-item"><span class="detail-key">高潮章节</span><span class="detail-value">${escapeHtml(narrative.climax_chapters || "--")}</span></div>
            </div>
            <div class="detail-section">
                <h4>钩子系统</h4>
                <div class="detail-item"><span class="detail-key">长线伏笔</span><span class="detail-value">${escapeHtml(hookSys.long_term || "--")}</span></div>
                <div class="detail-item"><span class="detail-key">短线钩子</span><span class="detail-value">${escapeHtml(hookSys.short_term || "--")}</span></div>
                <div class="detail-item"><span class="detail-key">未兑现伏笔</span><span class="detail-value">${escapeHtml(hookSys.unresolved || "--")}</span></div>
            </div>
        </div>
        <div class="detail-section">
            <h4>商业化初评</h4>
            <div class="detail-item"><span class="detail-key">可读性</span><span class="detail-value">${escapeHtml(commercial.readability || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">流失风险章节</span><span class="detail-value">${escapeHtml(commercial.retention_risk_chapters || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">最佳章节</span><span class="detail-value">${escapeHtml(commercial.best_chapters || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">预估商业分</span><span class="detail-value">${escapeHtml(commercial.score_estimate || "--")}</span></div>
        </div>
        ${insights.length ? `
        <div class="detail-section">
            <h4>写作洞察</h4>
            <ul class="detail-list">${insights.map(i => `<li>${escapeHtml(i)}</li>`).join("")}</ul>
        </div>` : ""}
    `;
}

function renderL2(l2) {
    if (!Array.isArray(l2) || !l2.length) return `<div class="detail-empty">暂无卷级分析数据</div>`;
    return l2.map((vol, idx) => `
        <div class="detail-card">
            <div class="detail-card-title">卷 ${idx + 1} <span class="detail-range">${escapeHtml(vol.range || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">节奏模式</span><span class="detail-value">${escapeHtml(vol.rhythm_pattern || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">情绪曲线</span><span class="detail-value">${escapeHtml(vol.emotional_arc || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">冲突升级</span><span class="detail-value">${escapeHtml(vol.conflict_escalation || "--")}</span></div>
            <div class="detail-item"><span class="detail-key">卷摘要</span><span class="detail-value">${escapeHtml(vol.volume_summary || "--")}</span></div>
            ${vol.pleasure_landmarks && vol.pleasure_landmarks.length ? `
                <div class="detail-subtitle">爽点地标</div>
                ${vol.pleasure_landmarks.map(p => `
                    <div class="detail-tag">${escapeHtml(p.ch || "?")}章 · ${escapeHtml(p.type || "--")} · 强度${p.intensity ?? "?"}</div>
                `).join("")}
            ` : ""}
            ${vol.debt_register && vol.debt_register.length ? `
                <div class="detail-subtitle">叙事债务</div>
                ${vol.debt_register.map(d => `
                    <div class="detail-tag ${(d.severity || "").toLowerCase()}">${escapeHtml(d.type || "--")} · ${escapeHtml(d.desc || "--")} · ${escapeHtml(d.severity || "--")}</div>
                `).join("")}
            ` : ""}
        </div>
    `).join("");
}

function renderL1(l1) {
    if (!Array.isArray(l1) || !l1.length) return `<div class="detail-empty">暂无章节摘要数据</div>`;
    return l1.map((grp, idx) => `
        <div class="detail-card compact">
            <div class="detail-card-title">章节组 ${idx + 1} <span class="detail-range">${escapeHtml(grp.chapters || "--")}</span></div>
            ${grp.chapter_summaries && grp.chapter_summaries.length ? `
                <div class="detail-subtitle">章节摘要</div>
                ${grp.chapter_summaries.map(s => `<div class="detail-line">${escapeHtml(typeof s === "string" ? s : (s.summary || JSON.stringify(s)))}</div>`).join("")}
            ` : ""}
            ${grp.hooks && grp.hooks.length ? `
                <div class="detail-subtitle">钩子</div>
                ${grp.hooks.map(h => `<div class="detail-tag">${escapeHtml(h.t || h.type || "--")} · ${escapeHtml(h.d || h.desc || "--")}</div>`).join("")}
            ` : ""}
            ${grp.key_events && grp.key_events.length ? `
                <div class="detail-subtitle">关键事件</div>
                ${grp.key_events.map(e => `<div class="detail-line">${escapeHtml(typeof e === "string" ? e : JSON.stringify(e))}</div>`).join("")}
            ` : ""}
            ${grp.foreshadowing && grp.foreshadowing.length ? `
                <div class="detail-subtitle">伏笔</div>
                ${grp.foreshadowing.map(f => `<div class="detail-tag">${escapeHtml(f.id || "--")} · ${escapeHtml(f.d || f.desc || "--")} · ${escapeHtml(f.s || f.status || "--")}</div>`).join("")}
            ` : ""}
        </div>
    `).join("");
}

function renderDetailContent() {
    if (!currentDetailData) {
        detailEls.content.innerHTML = `<div class="detail-empty">加载中...</div>`;
        return;
    }
    const data = currentDetailData;
    detailEls.tabs.forEach(t => t.classList.toggle("active", t.dataset.tab === currentDetailTab));
    if (currentDetailTab === "l3") {
        detailEls.content.innerHTML = renderL3(data.l3_analysis || {});
    } else if (currentDetailTab === "l2") {
        detailEls.content.innerHTML = renderL2(data.l2_summaries || []);
    } else if (currentDetailTab === "l1") {
        detailEls.content.innerHTML = renderL1(data.l1_summaries || []);
    }
}

export async function openBookDetail(name) {
    currentDetailBook = name;
    currentDetailTab = "l3";
    detailEls.bookName.textContent = name;
    detailEls.content.innerHTML = `<div class="detail-empty">加载中...</div>`;
    detailEls.modal.classList.add("open");
    detailEls.scoreBtn.disabled = true;
    detailEls.scoreBtn.textContent = "商业化打分";

    const res = await api.book(name, state.genre);
    if (!res.ok) {
        detailEls.content.innerHTML = `<div class="detail-empty error">加载失败: ${escapeHtml(res.error || "未知错误")}</div>`;
        return;
    }
    currentDetailData = res.data;
    detailEls.scoreBtn.disabled = false;
    renderDetailContent();
}

function closeBookDetail() {
    detailEls.modal.classList.remove("open");
    currentDetailBook = null;
    currentDetailData = null;
}

detailEls.closeBtn.addEventListener("click", closeBookDetail);
detailEls.modal.addEventListener("click", (e) => {
    if (e.target === detailEls.modal) closeBookDetail();
});

detailEls.tabs.forEach(tab => {
    tab.addEventListener("click", () => {
        currentDetailTab = tab.dataset.tab;
        renderDetailContent();
    });
});

// P2: Commercial score
async function runCommercialScore() {
    if (!currentDetailBook) return;
    scoreEls.bookName.textContent = `${currentDetailBook} - 商业化评估`;
    scoreEls.body.innerHTML = `<div class="detail-empty">正在计算商业化评分，请稍候...</div>`;
    scoreEls.modal.classList.add("open");

    const res = await api.score(currentDetailBook, state.genre);
    if (!res.ok) {
        scoreEls.body.innerHTML = `<div class="detail-empty error">评分失败: ${escapeHtml(res.error || "未知错误")}</div>`;
        return;
    }
    renderScoreResult(res.data);
}

function renderScoreResult(data) {
    const commercial = data.commercial || {};
    const grade = commercial.grade || "N/A";
    const overall = commercial.overall ?? "--";
    const risks = Array.isArray(commercial.risks) ? commercial.risks : [];
    const scores = commercial.scores || {};

    const scoreRows = Object.entries(scores).map(([k, v]) => `
        <div class="score-bar-row">
            <span class="score-bar-label">${escapeHtml(k)}</span>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${Math.max(0, Math.min(100, v))}%"></div></div>
            <span class="score-bar-value">${typeof v === "number" ? v : "--"}</span>
        </div>
    `).join("");

    scoreEls.body.innerHTML = `
        <div class="score-header">
            <div class="score-grade">${escapeHtml(String(grade))}</div>
            <div class="score-overall">综合分 <strong>${overall}</strong></div>
        </div>
        <div class="detail-section">
            <h4>分项得分</h4>
            ${scoreRows || "<p>暂无分项得分</p>"}
        </div>
        ${risks.length ? `
        <div class="detail-section">
            <h4>弃书风险</h4>
            ${risks.map(r => `
                <div class="detail-tag red">${escapeHtml(String(r.ch || ""))}章 · ${escapeHtml(r.reason)} · 流失率 ${escapeHtml(r.fire_rate)}</div>
            `).join("")}
        </div>` : ""}
        <div class="detail-grid">
            <div class="detail-section">
                <h4>签约预测</h4>
                <div class="detail-item"><span class="detail-key">分数</span><span class="detail-value">${commercial.signing_score ?? "--"}</span></div>
                <div class="detail-item"><span class="detail-key">来源</span><span class="detail-value">${escapeHtml(commercial.llm_source || "rule")}</span></div>
            </div>
            <div class="detail-section">
                <h4>留存预测</h4>
                <div class="detail-item"><span class="detail-key">分数</span><span class="detail-value">${commercial.retention_score ?? "--"}</span></div>
                <div class="detail-item"><span class="detail-key">慢热</span><span class="detail-value">${commercial.slow_burn ? "是" : "否"}</span></div>
            </div>
        </div>
    `;
}

scoreEls.closeBtn.addEventListener("click", () => scoreEls.modal.classList.remove("open"));
scoreEls.modal.addEventListener("click", (e) => {
    if (e.target === scoreEls.modal) scoreEls.modal.classList.remove("open");
});
detailEls.scoreBtn.addEventListener("click", runCommercialScore);
