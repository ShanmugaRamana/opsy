const sidebar = document.getElementById('sidebar');
const collapseBtn = document.getElementById('collapse-btn');

collapseBtn.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
});

// Randomized greeting phrases
const phrases = [
    "Ready?",
    "What's next?",
    "Let's go.",
    "Hello.",
    "Need help?",
    "Build it.",
    "Let's work."
];
document.getElementById('greeting-text').innerText = phrases[Math.floor(Math.random() * phrases.length)];

// Sidebar user profile, loaded from the onboarded user's record
const BACKEND_URL = 'http://localhost:8000';

const ROLE_LABELS = {
    'developer': 'Developer',
    'sysadmin': 'Sysadmin',
    'homelab': 'Homelab / Self-hoster',
    'student': 'Student',
    'desktop-user': 'Just a regular desktop user'
};

async function loadSidebarUser() {
    try {
        const res = await fetch(`${BACKEND_URL}/linux/users`);
        if (!res.ok) return;

        const users = await res.json();
        const user = users[0];
        if (!user) return;

        document.getElementById('sidebar-user-avatar').src = `/${user.profile_pic}`;
        document.getElementById('sidebar-user-name').innerText = user.name;
        document.getElementById('sidebar-user-role').innerText = ROLE_LABELS[user.role_use_case] || user.role_use_case;
    } catch (e) {
        // Backend/database not reachable, keep the static fallback values
    }
}

loadSidebarUser();

// ---- Dropdown menu open/close (provider, model, effort) ----

function toggleDropdown(menuId) {
    // Model selection requires a provider to be chosen first
    if (menuId === 'model-menu' && !selectedProvider) return;

    // Close all other menus first
    document.querySelectorAll('.chip-menu').forEach(menu => {
        if (menu.id !== menuId) {
            menu.style.display = 'none';
            menu.closest('.chip-dropdown').classList.remove('active');
        }
    });
    const menu = document.getElementById(menuId);
    const dropdown = menu.closest('.chip-dropdown');

    if (menu.style.display === 'none' || !menu.style.display) {
        menu.style.display = 'block';
        dropdown.classList.add('active');
    } else {
        menu.style.display = 'none';
        dropdown.classList.remove('active');
    }
}

function closeMenu(menuId) {
    const menu = document.getElementById(menuId);
    menu.style.display = 'none';
    menu.closest('.chip-dropdown').classList.remove('active');
}

// Generic text-only selector (used by the Effort dropdown, which has no DB backing)
function selectOption(event, type, text) {
    event.stopPropagation();
    document.getElementById(`${type}-text`).innerText = text;
    closeMenu(`${type}-menu`);
}

// Close when clicking outside any dropdown
document.addEventListener('click', (e) => {
    if (!e.target.closest('.chip-dropdown')) {
        document.querySelectorAll('.chip-menu').forEach(menu => {
            menu.style.display = 'none';
            menu.closest('.chip-dropdown').classList.remove('active');
        });
    }
});

// ---- Provider + model dropdowns, dynamic from the models table ----
// No provider names are hardcoded here — both the list of providers and how to
// display them come entirely from GET /linux/models (provider_display_name).

let modelsByProvider = {};
let providerDisplayNames = {};
let selectedProvider = null;
let selectedModelId = null;

function setModelSelectorEnabled(enabled) {
    const modelSelector = document.getElementById('model-selector');
    modelSelector.style.opacity = enabled ? '1' : '0.5';
    modelSelector.style.cursor = enabled ? 'pointer' : 'not-allowed';
}

function renderProviderMenu() {
    const menu = document.getElementById('provider-menu');
    const providers = Object.keys(modelsByProvider);

    menu.innerHTML = providers.map(provider => {
        const label = providerDisplayNames[provider] || provider;
        return `<div class="chip-option" data-provider="${provider}" style="padding: 0.5rem 0.75rem; font-family: 'Inter', sans-serif; font-size: 0.75rem; color: var(--text-main);">${label}</div>`;
    }).join('');

    menu.querySelectorAll('.chip-option').forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();
            selectProvider(option.dataset.provider);
            closeMenu('provider-menu');
        });
    });
}

function renderModelMenu() {
    const menu = document.getElementById('model-menu');
    const models = modelsByProvider[selectedProvider] || [];

    menu.innerHTML = models.map(model => {
        return `<div class="chip-option" data-model-id="${model.model_id}" data-display-name="${model.display_name}" style="padding: 0.5rem 0.75rem; font-family: 'Inter', sans-serif; font-size: 0.75rem; color: var(--text-main);">${model.display_name}</div>`;
    }).join('');

    menu.querySelectorAll('.chip-option').forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();
            selectModel(option.dataset.modelId, option.dataset.displayName);
            closeMenu('model-menu');
        });
    });
}

function selectProvider(provider) {
    selectedProvider = provider;
    document.getElementById('provider-text').innerText = providerDisplayNames[provider] || provider;

    const models = modelsByProvider[provider] || [];
    renderModelMenu();

    if (models.length > 0) {
        setModelSelectorEnabled(true);
        selectModel(models[0].model_id, models[0].display_name);
    } else {
        setModelSelectorEnabled(false);
        selectedModelId = null;
        document.getElementById('model-text').innerText = 'No models';
    }
}

function selectModel(modelId, displayName) {
    selectedModelId = modelId;
    document.getElementById('model-text').innerText = displayName;
}

async function loadProviderAndModelDropdowns() {
    const providerTextEl = document.getElementById('provider-text');
    const modelTextEl = document.getElementById('model-text');

    try {
        const res = await fetch(`${BACKEND_URL}/linux/models`);
        if (!res.ok) throw new Error(`models fetch failed: ${res.status}`);
        const models = await res.json();

        modelsByProvider = {};
        providerDisplayNames = {};
        models.forEach(model => {
            if (!modelsByProvider[model.provider]) modelsByProvider[model.provider] = [];
            modelsByProvider[model.provider].push(model);
            providerDisplayNames[model.provider] = model.provider_display_name;
        });

        const providers = Object.keys(modelsByProvider);
        renderProviderMenu();
        setModelSelectorEnabled(false);

        if (providers.length > 0) {
            providerTextEl.innerText = 'Select Provider';
            modelTextEl.innerText = 'Select Model';
        } else {
            providerTextEl.innerText = 'No provider';
            modelTextEl.innerText = 'No models';
        }
    } catch (e) {
        console.error('Could not load providers/models:', e);
        setModelSelectorEnabled(false);
        providerTextEl.innerText = 'No provider';
        modelTextEl.innerText = 'No models';
    }
}

loadProviderAndModelDropdowns();

// ---- Send message to the orchestrator ----

const chatLog = document.getElementById('chat-log');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

function appendMessage(role, text) {
    chatLog.style.display = 'flex';
    const bubble = document.createElement('div');
    bubble.className = `chat-message chat-message-${role}`;
    bubble.style.cssText = 'padding: 0.6rem 0.9rem; border-radius: 10px; font-family: \'Inter\', sans-serif; font-size: 0.85rem; line-height: 1.4; white-space: pre-wrap;';
    if (role === 'user') {
        bubble.style.alignSelf = 'flex-end';
        bubble.style.background = 'var(--card-bg)';
        bubble.style.border = '1px solid var(--border)';
    } else if (role === 'thinking') {
        bubble.style.color = 'var(--text-secondary, #888)';
        bubble.style.fontSize = '0.75rem';
        bubble.style.fontStyle = 'italic';
    } else if (role === 'error') {
        bubble.style.color = '#c0392b';
    }
    bubble.innerText = text;
    chatLog.appendChild(bubble);
    return bubble;
}

// ---- Orchestrator WebSocket: one persistent connection, reused across messages ----

const WS_URL = `${BACKEND_URL.replace('http', 'ws')}/linux/orchestrator/ws`;
let orchestratorSocket = null;

const SEVERITY_COLORS = { plenty: '#2ecc71', moderate: '#f1c40f', tight: '#e67e22', critical: '#e74c3c' };

let activeTrace = null;
let traceRows = {};

function startTrace() {
    const details = document.createElement('details');
    details.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.72rem; color: var(--text-secondary, #888); margin-top: 0.25rem;';
    const summary = document.createElement('summary');
    summary.style.cursor = 'pointer';
    summary.innerText = '🔍 How I checked this';
    details.appendChild(summary);
    chatLog.appendChild(details);
    activeTrace = details;
    traceRows = {};
    return details;
}

function traceRow(command, label) {
    if (!activeTrace) startTrace();
    const row = document.createElement('div');
    row.style.cssText = 'padding: 0.15rem 0; white-space: pre-wrap; word-break: break-word;';
    row.innerText = `Running: ${label}…`;
    activeTrace.appendChild(row);
    traceRows[command] = row;
    return row;
}

function renderDiskReport(report) {
    if (!report) return;

    if (report.summary) appendMessage('assistant', report.summary);

    if (report.percent_used != null) {
        const barWrap = document.createElement('div');
        barWrap.style.cssText = 'width: 100%; max-width: 400px; margin: 0.25rem 0; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; height: 10px;';
        const bar = document.createElement('div');
        const pct = Math.min(100, Math.max(0, report.percent_used));
        const color = SEVERITY_COLORS[report.severity] || '#888';
        bar.style.cssText = `height: 100%; width: ${pct}%; background: ${color};`;
        barWrap.appendChild(bar);
        chatLog.appendChild(barWrap);
    }

    if (report.top_consumers && report.top_consumers.length > 0) {
        const list = document.createElement('div');
        list.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.8rem; margin: 0.25rem 0; white-space: pre-wrap;';
        list.innerText = report.top_consumers
            .map((c) => `${c.label}: ${c.size_gb != null ? c.size_gb + ' GB' : '?'}`)
            .join('\n');
        chatLog.appendChild(list);
    }

    if (report.suggestion) appendMessage('thinking', `💡 ${report.suggestion}`);
}

function handleOrchestratorEvent(rawEvent) {
    let data;
    try {
        data = JSON.parse(rawEvent.data);
    } catch (e) {
        return;
    }

    switch (data.type) {
        case 'tool_call':
            traceRow(data.command, data.label);
            break;
        case 'tool_result': {
            const row = traceRows[data.command];
            if (row) row.innerText = `${data.label}: ${data.output}`;
            break;
        }
        case 'final':
            activeTrace = null;
            if (data.mode === 'disk') {
                renderDiskReport(data.disk_report);
            } else {
                if (data.thinking) appendMessage('thinking', data.thinking);
                appendMessage('assistant', data.content);
            }
            break;
        case 'error':
            activeTrace = null;
            appendMessage('error', `Error: ${data.detail}`);
            break;
    }
}

function ensureSocket(onReady) {
    if (orchestratorSocket && orchestratorSocket.readyState === WebSocket.OPEN) {
        onReady();
        return;
    }
    if (!orchestratorSocket || orchestratorSocket.readyState === WebSocket.CLOSED) {
        orchestratorSocket = new WebSocket(WS_URL);
        orchestratorSocket.addEventListener('message', handleOrchestratorEvent);
        orchestratorSocket.addEventListener('error', () => appendMessage('error', 'Connection error.'));
    }
    orchestratorSocket.addEventListener('open', onReady, { once: true });
}

function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || !selectedProvider || !selectedModelId) return;

    chatInput.value = '';
    appendMessage('user', message);

    ensureSocket(() => {
        orchestratorSocket.send(JSON.stringify({
            provider: selectedProvider,
            model_id: selectedModelId,
            message,
        }));
    });
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
});
