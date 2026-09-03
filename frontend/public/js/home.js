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

function scrollChatToBottom() {
    const scrollArea = document.getElementById('chat-scroll-area');
    if (scrollArea) scrollArea.scrollTop = scrollArea.scrollHeight;
}

function appendMessage(role, text) {
    chatLog.style.display = 'flex';
    document.querySelector('.main-content').classList.add('is-chatting');
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
    scrollChatToBottom();
    return bubble;
}

// ---- Orchestrator WebSocket: one persistent connection, reused across messages ----

const WS_URL = `${BACKEND_URL.replace('http', 'ws')}/linux/orchestrator/ws`;
let orchestratorSocket = null;

const SEVERITY_COLORS = { plenty: '#2ecc71', moderate: '#f1c40f', tight: '#e67e22', critical: '#e74c3c' };

// The live trace for the turn in flight: a panel that exists from the first event, updates its own
// header as work happens, and collapses once the answer lands.
let trace = null;

function startTrace() {
    chatLog.style.display = 'flex';
    document.querySelector('.main-content').classList.add('is-chatting');

    const details = document.createElement('details');
    details.open = true;
    details.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.72rem; color: var(--text-secondary, #888); border-left: 2px solid var(--border); padding-left: 0.6rem; margin: 0.25rem 0;';

    const summary = document.createElement('summary');
    summary.style.cssText = 'cursor: pointer; list-style: none; font-weight: 500;';
    summary.innerText = 'Starting';
    details.appendChild(summary);

    const thinking = document.createElement('div');
    thinking.style.cssText = 'white-space: pre-wrap; font-style: italic; padding: 0.2rem 0; line-height: 1.45;';
    details.appendChild(thinking);

    const commands = document.createElement('div');
    details.appendChild(commands);

    chatLog.appendChild(details);
    trace = { details, summary, thinking, commands, rows: {}, count: 0, labels: [] };
    return trace;
}

function ensureTrace() {
    return trace || startTrace();
}

// The header is never a fixed string: it names whatever is happening right now, then settles into a
// summary of what was actually run.
function setTraceHeader(text) {
    ensureTrace().summary.innerText = text;
}

function appendThinkingDelta(text) {
    const active = ensureTrace();
    active.thinking.innerText += text;
    if (active.count === 0) setTraceHeader('Thinking');
    scrollChatToBottom();
}

function traceRowKey(data) {
    return `${data.command}::${data.path || ''}`;
}

function startTraceRow(data) {
    const active = ensureTrace();
    const target = data.path ? `${data.label} (${data.path})` : data.label;

    const row = document.createElement('div');
    row.style.cssText = 'padding: 0.15rem 0; word-break: break-word;';
    row.innerText = `Running ${target}`;
    active.commands.appendChild(row);

    active.rows[traceRowKey(data)] = { row, target };
    active.count += 1;
    active.labels.push(target);
    setTraceHeader(`Running ${target}`);
    scrollChatToBottom();
}

function finishTraceRow(data) {
    const active = ensureTrace();
    const entry = active.rows[traceRowKey(data)];
    if (!entry) return;

    const output = document.createElement('div');
    output.style.cssText = 'white-space: pre-wrap; word-break: break-word; opacity: 0.75; margin: 0.1rem 0 0.4rem 0.6rem;';
    output.innerText = data.output;

    entry.row.innerText = entry.target;
    entry.row.style.fontWeight = '500';
    entry.row.insertAdjacentElement('afterend', output);
    setTraceHeader(`Checked ${entry.target}`);
    scrollChatToBottom();
}

// `keepOpen` is for a salvaged answer: when the model never returned a usable report, the commands
// that actually ran are more trustworthy than the summary, so the work stays visible.
function closeTrace(keepOpen) {
    if (!trace) return;
    const { count, labels } = trace;
    if (count === 0) {
        setTraceHeader('How I checked this: reasoning only, no commands run');
    } else if (count === 1) {
        setTraceHeader(`How I checked this: ${labels[0]}`);
    } else {
        setTraceHeader(`How I checked this: ${count} commands, ending with ${labels[count - 1]}`);
    }
    trace.details.open = Boolean(keepOpen);
    trace = null;
}

// Provider errors arrive as raw upstream JSON. Pull out something a person can act on.
function friendlyError(detail) {
    const text = String(detail || 'Something went wrong.');

    if (/rate.?limit|\b429\b|too many requests/i.test(text)) {
        const wait = text.match(/try again in ([0-9.]+)\s*s/i);
        const model = text.match(/model `([^`]+)`/);
        const forModel = model ? ` for ${model[1]}` : '';
        return wait
            ? `Rate limit reached${forModel}. It should clear in about ${Math.ceil(parseFloat(wait[1]))} seconds — try again then, or pick a different model.`
            : `Rate limit reached${forModel}. Wait a moment and try again, or pick a different model.`;
    }

    if (/\b401\b|invalid.*api.?key|authentication/i.test(text)) {
        return 'That provider rejected the API key. Check the key in setup.';
    }

    const message = text.match(/"message"\s*:\s*"([^"]+)"/);
    if (message) return message[1];

    return text.length > 300 ? `${text.slice(0, 300)}...` : text;
}

function countdownRetry(row, seconds) {
    let remaining = Math.ceil(seconds);
    const tick = () => {
        if (remaining <= 0) {
            row.innerText = 'Retrying now';
            return;
        }
        row.innerText = `Rate limited by the provider, retrying in ${remaining}s`;
        setTraceHeader(`Rate limited, retrying in ${remaining}s`);
        remaining -= 1;
        setTimeout(tick, 1000);
    };
    tick();
}

function appendBlock(text, styles) {
    chatLog.style.display = 'flex';
    document.querySelector('.main-content').classList.add('is-chatting');
    const block = document.createElement('div');
    block.style.cssText = `font-family: 'Inter', sans-serif; white-space: pre-wrap; ${styles}`;
    block.innerText = text;
    chatLog.appendChild(block);
    scrollChatToBottom();
    return block;
}

function renderDiskReport(report) {
    if (!report) return;

    if (report.summary) appendMessage('assistant', report.summary);
    // Say plainly when the answer is recovered prose rather than a real report, so a degraded
    // answer is never mistaken for a confident one.
    if (report.salvaged) {
        appendBlock(
            'The model did not return a structured report. This is the closest answer recovered from its reply — the trace above shows what was actually checked.',
            'font-size: 0.75rem; padding: 0 0.9rem; opacity: 0.7; font-style: italic;',
        );
    }
    if (report.explanation) {
        appendBlock(report.explanation, 'font-size: 0.82rem; line-height: 1.5; padding: 0 0.9rem; opacity: 0.9;');
    }

    const capacity = report.capacity;
    if (capacity && capacity.percent_used != null) {
        const barWrap = document.createElement('div');
        barWrap.style.cssText = 'width: 100%; max-width: 400px; margin: 0.4rem 0.9rem; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; height: 10px;';
        const bar = document.createElement('div');
        const pct = Math.min(100, Math.max(0, capacity.percent_used));
        bar.style.cssText = `height: 100%; width: ${pct}%; background: ${SEVERITY_COLORS[capacity.severity] || '#888'};`;
        barWrap.appendChild(bar);
        chatLog.appendChild(barWrap);

        const parts = [`${pct}% used`];
        if (capacity.free_gb != null && capacity.total_gb != null) {
            parts.push(`${capacity.free_gb} GB free of ${capacity.total_gb} GB`);
        }
        if (capacity.severity) parts.push(capacity.severity);
        appendBlock(parts.join(' · '), 'font-size: 0.75rem; padding: 0 0.9rem; opacity: 0.75;');
    }

    if (report.facts && report.facts.length > 0) {
        const table = document.createElement('table');
        table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse;';
        report.facts.forEach((fact) => {
            const tr = document.createElement('tr');
            const label = document.createElement('td');
            label.style.cssText = 'padding: 0.15rem 0.9rem 0.15rem 0; opacity: 0.7; vertical-align: top;';
            label.innerText = fact.label;
            const value = document.createElement('td');
            value.style.cssText = 'padding: 0.15rem 0; word-break: break-word;';
            value.innerText = fact.value;
            tr.appendChild(label);
            tr.appendChild(value);
            table.appendChild(tr);
        });
        chatLog.appendChild(table);
    }

    if (report.top_consumers && report.top_consumers.length > 0) {
        const text = report.top_consumers
            .map((c) => `${c.label}: ${c.size_gb != null ? c.size_gb + ' GB' : 'size unknown'}`)
            .join('\n');
        appendBlock(text, 'font-size: 0.8rem; padding: 0.2rem 0.9rem; line-height: 1.5;');
    }

    if (report.suggestion) {
        appendBlock(report.suggestion, 'font-size: 0.8rem; padding: 0.4rem 0.9rem; line-height: 1.5; border-left: 2px solid var(--border); margin: 0.3rem 0.9rem;');
    }
}

function handleOrchestratorEvent(rawEvent) {
    let data;
    try {
        data = JSON.parse(rawEvent.data);
    } catch (e) {
        return;
    }

    switch (data.type) {
        case 'started':
            startTrace();
            break;
        case 'classified':
            setTraceHeader(data.mode === 'disk' ? 'Checking storage' : 'Answering');
            break;
        case 'thinking_delta':
            appendThinkingDelta(data.text);
            break;
        case 'rate_limited': {
            const active = ensureTrace();
            active.details.open = true;
            const row = document.createElement('div');
            row.style.cssText = 'padding: 0.15rem 0; color: #e67e22;';
            active.commands.appendChild(row);
            countdownRetry(row, data.retry_in);
            break;
        }
        case 'retrying': {
            const active = ensureTrace();
            active.details.open = true;
            const row = document.createElement('div');
            row.style.cssText = 'padding: 0.15rem 0; color: #e67e22;';
            row.innerText = `Provider connection failed, retrying (attempt ${data.attempt})`;
            active.commands.appendChild(row);
            setTraceHeader('Retrying after a connection failure');
            break;
        }
        case 'tool_call':
            startTraceRow(data);
            break;
        case 'tool_result':
            finishTraceRow(data);
            break;
        case 'final': {
            // The general path doesn't stream, so its thinking arrives whole; keep it in the panel.
            if (data.thinking && trace && !trace.thinking.innerText) {
                trace.thinking.innerText = data.thinking;
            }
            const salvaged = Boolean(data.disk_report && data.disk_report.salvaged);
            closeTrace(salvaged);
            if (data.mode === 'disk') {
                renderDiskReport(data.disk_report);
            } else {
                appendMessage('assistant', data.content);
            }
            break;
        }
        case 'error':
            closeTrace(true);
            appendMessage('error', friendlyError(data.detail));
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
