const BACKEND_URL = 'http://localhost:8000';
const BACKEND_WS = 'ws://localhost:8000';

const modelNameEl = document.getElementById('dl-model-name');
const fillEl = document.getElementById('dl-progress-fill');
const percentEl = document.getElementById('dl-percent');
const phaseEl = document.getElementById('dl-phase');
const bytesEl = document.getElementById('dl-bytes');
const speedEtaEl = document.getElementById('dl-speed-eta');
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

function formatEta(seconds) {
    if (!seconds || seconds <= 0) return '';
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return m > 0 ? `${m}m ${s}s left` : `${s}s left`;
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

    const speed = state.speed_mbps ? `${state.speed_mbps.toFixed(1)} MB/s` : '';
    const eta = formatEta(state.eta_seconds);
    speedEtaEl.innerText = [speed, eta].filter(Boolean).join(' · ');
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
    fillEl.style.width = '0%';
    errorEl.innerText = detail || 'The download failed.';
    errorEl.style.display = 'block';
    cancelBtn.innerText = 'Back to setup';
}

function showReady() {
    percentEl.innerText = '100%';
    phaseEl.innerText = 'Ready';
    fillEl.style.width = '100%';
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
