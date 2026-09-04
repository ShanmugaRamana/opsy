const BACKEND_URL = 'http://localhost:8000';
const BACKEND_WS = 'ws://localhost:8000';

const modelNameEl = document.getElementById('dl-model-name');
const fillEl = document.getElementById('dl-progress-fill');
const percentEl = document.getElementById('dl-percent');
const phaseEl = document.getElementById('dl-phase');
const bytesEl = document.getElementById('dl-bytes');
const speedEtaEl = document.getElementById('dl-speed-eta');
const elapsedEl = document.getElementById('dl-elapsed');
const errorEl = document.getElementById('dl-error');
const readyEl = document.getElementById('dl-ready-message');
const cancelBtn = document.getElementById('dl-cancel-btn');

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return '—';
    const gb = bytes / (1024 ** 3);
    if (gb >= 1) return `${gb.toFixed(2)} GB`;
    const mb = bytes / (1024 ** 2);
    return `${mb.toFixed(0)} MB`;
}

function formatDuration(seconds) {
    const total = Math.max(Math.round(seconds), 0);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// The elapsed clock ticks locally between events. The backend's `elapsed_seconds` is the authority -
// each event re-anchors this - but events arrive every 250ms at best and stop entirely during a long
// verify, and a time readout that freezes looks as broken as one that disappears.
let elapsedBaseSeconds = 0;
let elapsedAnchorMs = Date.now();
let elapsedTimer = null;

function renderElapsed() {
    const drift = (Date.now() - elapsedAnchorMs) / 1000;
    elapsedEl.innerText = `Elapsed ${formatDuration(elapsedBaseSeconds + drift)}`;
}

function startElapsedTicker() {
    if (elapsedTimer !== null) return;
    elapsedTimer = setInterval(renderElapsed, 1000);
}

function stopElapsedTicker() {
    if (elapsedTimer === null) return;
    clearInterval(elapsedTimer);
    elapsedTimer = null;
}

function applyProgress(state) {
    if (state.display_name) modelNameEl.innerText = state.display_name;

    const percent = state.percent || 0;
    fillEl.style.width = `${Math.min(percent, 100)}%`;
    percentEl.innerText = `${percent.toFixed(1)}%`;
    phaseEl.innerText = state.phase || '';

    const downloaded = formatBytes(state.downloaded_bytes);
    const total = formatBytes(state.total_bytes);
    bytesEl.innerText = state.total_bytes ? `${downloaded} of ${total}` : downloaded;

    if (typeof state.elapsed_seconds === 'number') {
        elapsedBaseSeconds = state.elapsed_seconds;
        elapsedAnchorMs = Date.now();
        renderElapsed();
        startElapsedTicker();
    }

    // The backend clears these deliberately when the transfer pauses (a verify phase has no speed),
    // and carries the last known pair forward otherwise. Rendering whatever arrived is therefore
    // correct - but an empty string would collapse the row's width and shift the layout, so the
    // absence of a figure gets words rather than nothing.
    const speed = state.speed_mbps ? `${state.speed_mbps.toFixed(1)} MB/s` : '';
    const eta = state.eta_seconds > 0 ? `${formatDuration(state.eta_seconds)} left` : '';
    const parts = [speed, eta].filter(Boolean);
    if (parts.length) {
        speedEtaEl.innerText = parts.join(' · ');
    } else {
        // Nothing measured yet is "Estimating…"; nothing to measure (a verify phase) is a dash, not
        // a promise of a number that isn't coming.
        const transferring = !state.phase || state.phase === 'downloading';
        speedEtaEl.innerText = transferring ? 'Estimating…' : '—';
    }
}

function fadeToHome() {
    setTimeout(() => {
        document.body.style.transition = 'opacity 0.8s ease';
        document.body.style.opacity = '0';
        setTimeout(() => {
            window.location.href = '/';
        }, 800);
    }, 1200);
}

function showError(detail) {
    stopElapsedTicker();
    fillEl.style.width = '0%';
    speedEtaEl.innerText = '—';
    errorEl.innerText = detail || 'The download failed.';
    errorEl.style.display = 'block';
    cancelBtn.innerText = 'Back to setup';
}

function showReady() {
    stopElapsedTicker();
    percentEl.innerText = '100%';
    phaseEl.innerText = 'Ready';
    fillEl.style.width = '100%';
    speedEtaEl.innerText = '—';
    readyEl.style.display = 'block';
    cancelBtn.style.display = 'none';
    fadeToHome();
}

let gotSnapshot = false;

function connect() {
    const ws = new WebSocket(`${BACKEND_WS}/linux/local-models/download/ws`);

    ws.onmessage = (rawEvent) => {
        let event;
        try {
            event = JSON.parse(rawEvent.data);
        } catch (e) {
            console.error('Could not parse download event:', e);
            return;
        }

        if (event.type === 'snapshot') {
            gotSnapshot = true;
            applyProgress(event);
            if (event.status === 'ready') {
                showReady();
            } else if (event.status === 'failed' || event.status === 'cancelled') {
                showError(event.error);
            }
        } else if (event.type === 'progress') {
            applyProgress(event);
        } else if (event.type === 'done') {
            showReady();
        } else if (event.type === 'error') {
            if (!gotSnapshot) {
                // Nothing is downloading (e.g. this page was opened directly, or after the pull
                // already finished and was cleared) - this isn't a failure to report, just nowhere
                // to be.
                window.location.href = '/setup';
                return;
            }
            showError(event.detail);
        }
    };

    ws.onerror = () => {
        console.error('Download WebSocket connection failed.');
    };

    ws.onclose = () => {
        window._downloadWs = null;
    };

    window._downloadWs = ws;
}

cancelBtn.addEventListener('click', async () => {
    if (errorEl.style.display === 'block') {
        window.location.href = '/setup';
        return;
    }

    cancelBtn.disabled = true;
    cancelBtn.innerText = 'Cancelling…';
    try {
        await fetch(`${BACKEND_URL}/linux/local-models/download/cancel`, { method: 'POST' });
    } catch (e) {
        console.error('Could not reach backend to cancel download:', e);
    }
    window.location.href = '/setup';
});

connect();
