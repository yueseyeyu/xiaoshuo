/**
 * 硬件监控渲染
 */
import { api } from "./api.js";
import { state } from "./state.js";

const els = {
    temp: {
        value: document.getElementById("valTemp"),
        arc: document.getElementById("arcTemp"),
        badge: document.getElementById("badgeTemp"),
        root: document.getElementById("gaugeTemp"),
    },
    vram: {
        value: document.getElementById("valVram"),
        arc: document.getElementById("arcVram"),
        badge: document.getElementById("badgeVram"),
        root: document.getElementById("gaugeVram"),
    },
    fan: {
        value: document.getElementById("valFan"),
        arc: document.getElementById("arcFan"),
        badge: document.getElementById("badgeFan"),
        root: document.getElementById("gaugeFan"),
    },
    mem: {
        value: document.getElementById("valMem"),
        arc: document.getElementById("arcMem"),
        badge: document.getElementById("badgeMem"),
        root: document.getElementById("gaugeMem"),
    },
    logList: document.getElementById("logList"),
    alertDrawer: document.getElementById("alertDrawer"),
    alertBody: document.getElementById("alertBody"),
    closeAlertBtn: document.getElementById("closeAlertBtn"),
};

const CIRCUMFERENCE = 2 * Math.PI * 50; // 314

function setArc(arc, ratio) {
    arc.style.strokeDashoffset = CIRCUMFERENCE * (1 - Math.max(0, Math.min(1, ratio)));
}

function setHealth(root, badge, level, label) {
    root.classList.remove("green", "yellow", "red");
    badge.classList.remove("green", "yellow", "red");
    root.classList.add(level);
    badge.classList.add(level);
    badge.textContent = label;
}

function formatValue(value, fallback = "--") {
    return value === null || value === undefined ? fallback : value;
}

function renderTemp(value, thresholds) {
    if (value == null) {
        els.temp.value.textContent = "--";
        setArc(els.temp.arc, 0);
        setHealth(els.temp.root, els.temp.badge, "", "未检测");
        return "unknown";
    }
    els.temp.value.textContent = value;
    const ratio = Math.min(value / thresholds.temp_stop, 1);
    setArc(els.temp.arc, ratio);
    if (value >= thresholds.temp_stop) {
        setHealth(els.temp.root, els.temp.badge, "red", "异常");
        return "red";
    }
    if (value >= thresholds.temp_warn) {
        setHealth(els.temp.root, els.temp.badge, "yellow", "警告");
        return "yellow";
    }
    setHealth(els.temp.root, els.temp.badge, "green", "正常");
    return "green";
}

function renderVram(value, thresholds) {
    if (value == null) {
        els.vram.value.textContent = "--";
        setArc(els.vram.arc, 0);
        setHealth(els.vram.root, els.vram.badge, "", "未检测");
        return "unknown";
    }
    els.vram.value.textContent = value;
    const ratio = Math.min(value / thresholds.vram_red, 1);
    setArc(els.vram.arc, ratio);
    if (value >= thresholds.vram_red) {
        setHealth(els.vram.root, els.vram.badge, "red", "异常");
        return "red";
    }
    if (value >= thresholds.vram_orange) {
        setHealth(els.vram.root, els.vram.badge, "yellow", "警告");
        return "yellow";
    }
    setHealth(els.vram.root, els.vram.badge, "green", "正常");
    return "green";
}

function renderFan(value, thresholds, gpuTemp) {
    if (value == null) {
        els.fan.value.textContent = "--";
        setArc(els.fan.arc, 0);
        setHealth(els.fan.root, els.fan.badge, "", "未检测");
        return "unknown";
    }
    els.fan.value.textContent = value;
    const ratio = value / 100;
    setArc(els.fan.arc, ratio);
    if (value < thresholds.fan_min_percent) {
        // GPU 温度高但风扇慢 → 真正的异常；否则只是空闲/低载
        if (gpuTemp != null && gpuTemp >= thresholds.temp_warn) {
            setHealth(els.fan.root, els.fan.badge, "red", "异常");
            return "red";
        }
        setHealth(els.fan.root, els.fan.badge, "yellow", "低载");
        return "yellow";
    }
    setHealth(els.fan.root, els.fan.badge, "green", "正常");
    return "green";
}

function renderMem(used, total) {
    if (used == null || total == null) {
        els.mem.value.textContent = "--";
        setArc(els.mem.arc, 0);
        setHealth(els.mem.root, els.mem.badge, "", "未检测");
        return "unknown";
    }
    els.mem.value.textContent = used;
    const ratio = used / total;
    setArc(els.mem.arc, ratio);
    if (ratio >= 0.9) {
        setHealth(els.mem.root, els.mem.badge, "red", "异常");
        return "red";
    }
    if (ratio >= 0.75) {
        setHealth(els.mem.root, els.mem.badge, "yellow", "警告");
        return "yellow";
    }
    setHealth(els.mem.root, els.mem.badge, "green", "正常");
    return "green";
}

function renderLogs(logs) {
    cachedLogs = logs;
    const filtered = logLevelFilter === "all"
        ? logs
        : logs.filter(l => l.level === logLevelFilter);
    els.logList.innerHTML = filtered.slice(-20).map(log => `
        <div class="log-item">
            <span class="log-time">${log.time}</span>
            <span class="log-level ${log.level.toLowerCase()}">${log.level}</span>
            <span class="log-message">${escapeHtml(log.message)}</span>
        </div>
    `).join("");
    els.logList.scrollTop = els.logList.scrollHeight;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

let lastAlertCount = 0;
// P1: Log level filter
let logLevelFilter = "all";
let cachedLogs = [];

function renderAlerts(alerts) {
    if (alerts.length === 0) {
        els.alertDrawer.classList.remove("open");
        document.body.classList.remove("hardware-alert");
        lastAlertCount = 0;
        return;
    }
    els.alertBody.innerHTML = alerts.map(a => `
        <div class="alert-item">
            <div class="alert-time">${a.time}</div>
            <div class="alert-text">${escapeHtml(a.message)}</div>
        </div>
    `).join("");

    if (alerts.length > lastAlertCount) {
        els.alertDrawer.classList.add("open");
        document.body.classList.add("hardware-alert");
    }
    lastAlertCount = alerts.length;
}

export async function updateHardware() {
    try {
        const res = await api.hardware();
        if (!res.ok) return;
        const d = res.data;
        state.hardware = d;

        const t = d.thresholds;
        const tempLevel = renderTemp(d.gpu_temp, t);
        const vramLevel = renderVram(d.vram_used_mb, t);
        const fanLevel = renderFan(d.fan_speed, t, d.gpu_temp);
        const memLevel = renderMem(d.sys_memory_used_gb, d.sys_memory_total_gb);
        const levels = [tempLevel, vramLevel, fanLevel, memLevel];

        // Build alerts from current hardware state
        const alerts = [];
        if (d.gpu_temp >= t.temp_stop) {
            alerts.push({ time: d.updated_at, message: `GPU 温度 ${d.gpu_temp}°C 超过紧急阈值 ${t.temp_stop}°C` });
        } else if (d.gpu_temp >= t.temp_warn) {
            alerts.push({ time: d.updated_at, message: `GPU 温度 ${d.gpu_temp}°C 达到警告阈值 ${t.temp_warn}°C` });
        }
        if (d.vram_used_mb >= t.vram_red) {
            alerts.push({ time: d.updated_at, message: `显存使用 ${d.vram_used_mb}MB 超过红色阈值 ${t.vram_red}MB` });
        } else if (d.vram_used_mb >= t.vram_orange) {
            alerts.push({ time: d.updated_at, message: `显存使用 ${d.vram_used_mb}MB 达到橙色阈值 ${t.vram_orange}MB` });
        }
        if (d.fan_speed != null && d.fan_speed < t.fan_min_percent && d.gpu_temp != null && d.gpu_temp >= t.temp_warn) {
            alerts.push({ time: d.updated_at, message: `风扇转速 ${d.fan_speed}% 过低且 GPU 温度 ${d.gpu_temp}°C 偏高` });
        }
        if (d.sys_memory_used_gb && d.sys_memory_total_gb && d.sys_memory_used_gb / d.sys_memory_total_gb >= 0.9) {
            alerts.push({ time: d.updated_at, message: `系统内存使用超过 90%` });
        }
        state.alerts = alerts;
        renderAlerts(alerts);
    } catch (e) {
        // silent fail
    }
}

export async function updateLogs() {
    try {
        const res = await api.logs();
        if (res.ok) renderLogs(res.data);
    } catch (e) {
        // silent fail
    }
}

els.closeAlertBtn.addEventListener("click", () => {
    els.alertDrawer.classList.remove("open");
});

// P1: Log level filter buttons
document.querySelectorAll(".log-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".log-filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        logLevelFilter = btn.dataset.level;
        renderLogs(cachedLogs);
    });
});
