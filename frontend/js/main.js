/**
 * 应用入口
 */
import { state } from "./state.js";
import {
    refreshProgress,
    refreshStatus,
    updateGlobalStatus,
} from "./dashboard.js";
import { updateHardware, updateLogs } from "./hardware.js";

async function init() {
    await refreshStatus();
    await refreshProgress();
    await updateHardware();
    await updateLogs();
    updateGlobalStatus();

    // Polling intervals
    setInterval(refreshStatus, 3000);
    setInterval(refreshProgress, 5000);
    setInterval(updateHardware, 3000);
    setInterval(updateLogs, 5000);
}

init().catch(console.error);
