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

// ---- Sessions: sidebar list, switching, and the "chat already running" guard ----
//
// currentSessionId is null until either a message is sent (the backend creates and reports one
// back via `session_created`) or the user opens a past chat from the sidebar - it is never restored
// from the DB's "active" session on load, since doing so without also replaying that session's
// transcript would silently attach the next typed message to a conversation nothing on screen
// shows. turnInProgress mirrors the live trace's lifetime and is what New Chat and the sidebar
// check before letting the user switch away mid-turn (see plans/session-management.md).

const SESSIONS_URL = `${BACKEND_URL}/linux/sessions`;

let currentSessionId = null;
let turnInProgress = false;
let sessionsById = {};

const newChatBtn = document.getElementById('new-chat-btn');
const activeChatSection = document.getElementById('active-chat-section');
const activeSessionListEl = document.getElementById('active-session-list');
const recentChatSection = document.getElementById('recent-chat-section');
const recentSessionListEl = document.getElementById('recent-session-list');
const runningBanner = document.getElementById('running-banner');
const runningBannerText = document.getElementById('running-banner-text');
const runningBannerBtn = document.getElementById('running-banner-btn');

function showRunningBanner(sessionId, sessionName) {
    runningBannerText.innerText = `"${sessionName || 'A chat'}" is still running.`;
    runningBanner.dataset.sessionId = sessionId;
    runningBanner.style.display = 'flex';
}

function hideRunningBanner() {
    runningBanner.style.display = 'none';
    delete runningBanner.dataset.sessionId;
}

runningBannerBtn.addEventListener('click', () => {
    const sessionId = runningBanner.dataset.sessionId;
    hideRunningBanner();
    if (sessionId) switchToSession(Number(sessionId), { skipActivate: true });
});

function setTurnInProgress(value) {
    turnInProgress = value;
    renderSessionList();
}

function renderSessionList() {
    const sessions = Object.values(sessionsById).sort(
        (a, b) => new Date(b.updated_at) - new Date(a.updated_at)
    );
    newChatBtn.disabled = turnInProgress;
    
    activeSessionListEl.innerHTML = '';
    recentSessionListEl.innerHTML = '';
    
    let hasActive = false;
    let hasRecent = false;

    sessions.forEach((session) => {
        const item = document.createElement('button');
        const isActive = session.session_id === currentSessionId;
        item.className = 'session-item' + (isActive ? ' active' : '');
        item.innerText = session.session_name;
        item.disabled = turnInProgress;
        item.addEventListener('click', () => switchToSession(session.session_id));
        
        if (isActive) {
            activeSessionListEl.appendChild(item);
            hasActive = true;
        } else {
            recentSessionListEl.appendChild(item);
            hasRecent = true;
        }
    });

    activeChatSection.style.display = hasActive ? 'block' : 'none';
    recentChatSection.style.display = hasRecent ? 'block' : 'none';
}

async function loadSessions() {
    try {
        const res = await fetch(SESSIONS_URL);
        if (!res.ok) return;
        const sessions = await res.json();
        sessionsById = {};
        sessions.forEach((s) => { sessionsById[s.session_id] = s; });
        renderSessionList();
    } catch (e) {
        // Backend/database not reachable, the sidebar list just stays empty
    }
}

// Reuses the exact renderers the live "final" event already uses, so a replayed turn looks
// identical to how it looked when it actually happened.
function renderStoredTurn(turn) {
    if (turn.role === 'user') {
        appendMessage('user', turn.content || '');
        return;
    }
    const renderer = REPORT_RENDERERS[turn.mode];
    if (renderer) {
        renderer(turn[`${turn.mode}_report`]);
    } else {
        appendMessage('assistant', turn.content || '');
    }
}

function resetChatView() {
    chatLog.innerHTML = '';
    chatLog.style.display = 'none';
    document.querySelector('.main-content').classList.remove('is-chatting');
    trace = null;
    // Any failure card that was awaiting a retry went out with the transcript.
    retryingCard = null;
}

async function switchToSession(sessionId, options = {}) {
    if (turnInProgress || sessionId === currentSessionId) return;

    if (!options.skipActivate) {
        try {
            const res = await fetch(`${SESSIONS_URL}/${sessionId}/activate`, { method: 'POST' });
            if (res.status === 409) {
                const body = await res.json().catch(() => ({}));
                const detail = body.detail || {};
                showRunningBanner(detail.session_id, detail.session_name);
                return;
            }
            if (!res.ok) return;
        } catch (e) {
            appendMessage('error', 'Could not reach the backend to switch chats.');
            return;
        }
    }

    let turns = [];
    try {
        const res = await fetch(`${SESSIONS_URL}/${sessionId}/chats`);
        if (res.ok) turns = await res.json();
    } catch (e) {
        // Falls through with an empty transcript rather than blocking the switch entirely
    }

    currentSessionId = sessionId;
    hideRunningBanner();
    resetChatView();
    turns.forEach(renderStoredTurn);
    scrollChatToBottom();
    renderSessionList();
}

newChatBtn.addEventListener('click', () => {
    if (turnInProgress) {
        const running = sessionsById[currentSessionId];
        showRunningBanner(currentSessionId, running ? running.session_name : null);
        return;
    }
    currentSessionId = null;
    hideRunningBanner();
    resetChatView();
    renderSessionList();
});

loadSessions();

// ---- Send message to the orchestrator ----

const chatLog = document.getElementById('chat-log');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

function updateScrollFade() {
    const scrollArea = document.getElementById('chat-scroll-area');
    if (!scrollArea) return;
    if (scrollArea.scrollHeight > scrollArea.clientHeight) {
        scrollArea.classList.add('has-scroll');
    } else {
        scrollArea.classList.remove('has-scroll');
    }
}

function scrollChatToBottom() {
    const scrollArea = document.getElementById('chat-scroll-area');
    if (scrollArea) {
        scrollArea.scrollTop = scrollArea.scrollHeight;
        updateScrollFade();
    }
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
const LOAD_SEVERITY_COLORS = { idle: '#2ecc71', normal: '#2ecc71', busy: '#e67e22', overloaded: '#e74c3c' };
const NETWORK_SEVERITY_COLORS = { online: '#2ecc71', degraded: '#e67e22', offline: '#e74c3c' };
// The ladder marks a position in a chain rather than a quantity, so its rungs get their own three
// states instead of the severity scale the disk and process bars use.
const RUNG_COLORS = { ok: '#2ecc71', fail: '#e74c3c', unknown: '#888' };

// The live trace for the turn in flight: a panel that exists from the first event, updates its own
// header as work happens, and collapses once the answer lands.
let trace = null;

// The message of the most recently sent turn, kept so its failure card can re-send exactly that text
// instead of asking the user to retype it, and the card currently waiting on a retry it triggered.
// `turnPending` spans send until the turn resolves one way or the other - wider than
// `turnInProgress`, which only starts at the backend's "started" event and so would miss a socket
// that dies before the turn ever begins.
let inFlightMessage = null;
let retryingCard = null;
let turnPending = false;

function startTrace() {
    chatLog.style.display = 'flex';
    document.querySelector('.main-content').classList.add('is-chatting');

    const details = document.createElement('details');
    details.open = true;
    details.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.72rem; color: var(--text-secondary, #888); border-left: 2px solid var(--border); padding-left: 0.6rem; margin: 0.25rem 0;';

    const summary = document.createElement('summary');
    summary.style.cssText = 'cursor: pointer; list-style: none; font-weight: 500; display: flex; align-items: center; gap: 0.4rem;';

    const logo = document.createElement('img');
    logo.src = '/assets/images/logo.png';
    logo.style.cssText = 'width: 14px; height: 14px; object-fit: contain; animation: pulse 1.5s infinite; opacity: 0.8;';
    summary.appendChild(logo);

    const textSpan = document.createElement('span');
    textSpan.innerText = 'Starting';
    summary.appendChild(textSpan);
    
    details.appendChild(summary);

    const thinking = document.createElement('div');
    thinking.style.cssText = 'white-space: pre-wrap; font-style: italic; padding: 0.2rem 0; line-height: 1.45;';
    details.appendChild(thinking);

    const commands = document.createElement('div');
    details.appendChild(commands);

    chatLog.appendChild(details);
    trace = { details, summary, textSpan, logo, thinking, commands, rows: {}, count: 0, labels: [] };
    return trace;
}

function ensureTrace() {
    return trace || startTrace();
}

let retryCycleInterval = null;
const retryWords = ["Thinking...", "Analyzing...", "Holding on...", "Working..."];
let retryWordIndex = 0;

function startRetryCycling() {
    const active = ensureTrace();
    if (retryCycleInterval) return;
    
    const updateWord = () => {
        if (!trace) return;
        trace.textSpan.innerText = retryWords[retryWordIndex];
        retryWordIndex = (retryWordIndex + 1) % retryWords.length;
    };
    
    updateWord();
    retryCycleInterval = setInterval(updateWord, 3000);
}

function stopRetryCycling() {
    if (retryCycleInterval) {
        clearInterval(retryCycleInterval);
        retryCycleInterval = null;
    }
}

// The header is never a fixed string: it names whatever is happening right now, then settles into a
// summary of what was actually run.
function setTraceHeader(text) {
    stopRetryCycling();
    const active = ensureTrace();
    active.textSpan.innerText = text;
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

// ---- Command approval ----

// The agent can ask to run a command the fixed allow-lists don't cover. Nothing runs until the user
// answers here, and the card shows the exact command that will be executed.
const pendingPermissions = {};

async function sendPermissionDecision(requestId, decision) {
    try {
        const response = await fetch(`${BACKEND_URL}/linux/orchestrator/permissions/${requestId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ decision }),
        });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            appendMessage('error', friendlyError(body.detail || 'Could not send that decision.'));
        }
    } catch (e) {
        appendMessage('error', 'Could not reach the backend to send that decision.');
    }
}

function renderPermissionRequest(data) {
    const active = ensureTrace();
    active.details.open = true;

    const card = document.createElement('div');
    card.style.cssText = 'margin: 0.4rem 0; padding: 0.6rem; border: 1px solid var(--border); border-radius: 8px; background: var(--card-bg);';

    const title = document.createElement('div');
    title.style.cssText = 'font-weight: 600; margin-bottom: 0.3rem;';
    title.innerText = 'Zyros wants to run a command';
    card.appendChild(title);

    if (data.reason) {
        const reason = document.createElement('div');
        reason.style.cssText = 'margin-bottom: 0.4rem; line-height: 1.45;';
        reason.innerText = data.reason;
        card.appendChild(reason);
    }

    const command = document.createElement('div');
    command.style.cssText = 'font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; padding: 0.4rem 0.5rem; margin-bottom: 0.5rem; border-radius: 6px; background: var(--bg, rgba(0,0,0,0.05)); overflow-x: auto; white-space: pre;';
    command.innerText = data.command;
    card.appendChild(command);

    if (data.count_lines) {
        const note = document.createElement('div');
        note.style.cssText = 'font-size: 0.7rem; opacity: 0.65; margin-bottom: 0.4rem;';
        note.innerText = 'Only a count of the result will be reported, not the full output.';
        card.appendChild(note);
    }

    const buttons = document.createElement('div');
    buttons.style.cssText = 'display: flex; gap: 0.4rem;';

    const decide = (decision) => {
        Array.from(buttons.children).forEach((b) => { b.disabled = true; });
        buttons.remove();
        const pending = document.createElement('div');
        pending.style.cssText = 'opacity: 0.7;';
        pending.innerText = decision === 'approve' ? 'Approved, running...' : 'Denied.';
        card.appendChild(pending);
        sendPermissionDecision(data.request_id, decision);
    };

    const approve = document.createElement('button');
    approve.innerText = 'Approve';
    approve.style.cssText = 'padding: 0.3rem 0.7rem; border-radius: 6px; border: 1px solid var(--border); cursor: pointer; font-family: inherit; font-size: 0.72rem;';
    approve.addEventListener('click', () => decide('approve'));

    const deny = document.createElement('button');
    deny.innerText = 'Deny';
    deny.style.cssText = approve.style.cssText;
    deny.addEventListener('click', () => decide('deny'));

    buttons.appendChild(approve);
    buttons.appendChild(deny);
    card.appendChild(buttons);

    active.commands.appendChild(card);
    pendingPermissions[data.request_id] = card;
    setTraceHeader('Waiting for your approval');
    chatLog.scrollTop = chatLog.scrollHeight;
}

function resolvePermissionRequest(data) {
    const card = pendingPermissions[data.request_id];
    delete pendingPermissions[data.request_id];
    if (!card) return;

    // Covers the timeout case, where nobody clicked and the backend denied on the user's behalf.
    Array.from(card.querySelectorAll('button')).forEach((b) => b.remove());
    if (!data.approved) {
        const note = document.createElement('div');
        note.style.cssText = 'opacity: 0.7;';
        note.innerText = 'Not run.';
        card.appendChild(note);
    }
}

function startTraceRow(data) {
    const active = ensureTrace();
    
    // Close any previously open command details in this trace
    const openDetails = active.commands.querySelectorAll('details[open]');
    openDetails.forEach(d => d.open = false);

    const target = data.path ? `${data.label} (${data.path})` : data.label;

    const details = document.createElement('details');
    details.open = true;
    details.style.cssText = 'margin: 0.15rem 0; padding-left: 0.2rem;';

    const summary = document.createElement('summary');
    summary.style.cssText = 'cursor: pointer; padding: 0.15rem 0; word-break: break-word; font-weight: 500; opacity: 0.9;';
    summary.innerText = `Running ${target}...`;
    
    details.appendChild(summary);
    active.commands.appendChild(details);

    active.rows[traceRowKey(data)] = { details, summary, target };
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
    output.style.cssText = 'white-space: pre-wrap; word-break: break-word; opacity: 0.75; margin: 0.2rem 0 0.4rem 1.2rem; padding-left: 0.4rem; border-left: 1px solid var(--border); max-height: 15rem; overflow-y: auto; scrollbar-width: thin; scrollbar-color: rgba(0, 0, 0, 0.2) transparent;';
    output.classList.add('tool-result-scroll');
    output.innerText = data.output;

    entry.summary.innerText = entry.target;
    entry.details.appendChild(output);
    setTraceHeader(`Checked ${entry.target}`);
    scrollChatToBottom();
}

// `keepOpen` is for a salvaged answer: when the model never returned a usable report, the commands
// that actually ran are more trustworthy than the summary, so the work stays visible.
function closeTrace(keepOpen) {
    if (!trace) return;
    stopRetryCycling();
    trace.logo.style.animation = 'none';
    trace.logo.style.opacity = '0.5';
    
    // Close any remaining open command details
    const openDetails = trace.commands.querySelectorAll('details[open]');
    openDetails.forEach(d => d.open = false);

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

    // Local-provider failures (Ollama unreachable) are already a plain, actionable sentence from the
    // backend - unlike a cloud 401, there is no key to "check in setup", so this returns as-is rather
    // than falling into that copy below.
    if (/ollama isn'?t (running|installed)/i.test(text)) {
        return text;
    }

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

// What to tell the user about a turn that died, and whether sending the same message again could
// plausibly get a different answer. By the time an error reaches the client the backend has already
// spent its retry budget, so `retryable` means "a person can do something and try again", not "this
// will probably work on its own".
function describeFailure(detail, status) {
    const text = String(detail || '');

    if (/ollama isn'?t (running|installed)/i.test(text)) {
        return { title: friendlyError(text), hint: 'Start Ollama, then send this again.', retryable: true };
    }
    if (/connection to the backend|agent unreachable/i.test(text)) {
        return {
            title: 'Lost the connection to the backend.',
            hint: 'Check that the Zyros backend is still running, then send this again.',
            retryable: true,
        };
    }
    if (status === 429 || /rate.?limit|\b429\b|too many requests/i.test(text)) {
        return {
            title: friendlyError(text),
            hint: 'Zyros already retried this a few times. Wait a moment, or pick a different model, then send it again.',
            retryable: true,
        };
    }
    if (status === 401 || status === 403 || /\b401\b|invalid.*api.?key|authentication/i.test(text)) {
        return {
            title: 'That provider rejected the API key.',
            hint: 'Fix the key on the setup page, then send this again.',
            retryable: true,
        };
    }
    if (/no stored api key/i.test(text)) {
        return {
            title: 'No API key is stored for this provider.',
            hint: 'Add one on the setup page, then send this again.',
            retryable: true,
        };
    }
    if (status === 400) {
        // A rejected request (unknown provider, malformed payload) answers the same way every time,
        // so a retry button here would only be a second way to fail.
        return { title: friendlyError(text), hint: 'Pick a different provider or model below and send again.', retryable: false };
    }
    return {
        title: "That didn't go through.",
        hint: 'The provider stopped responding after a few tries. Your message is still here — send it again when you are ready.',
        retryable: true,
    };
}

// The card that replaces a raw provider error in the transcript: a sentence a person can act on, the
// technical detail folded away for when it is actually wanted, and a button that re-sends the exact
// message that failed so the turn is recoverable without retyping it.
function renderTurnFailure(data) {
    const { title, hint, retryable } = describeFailure(data.detail, data.status);
    const message = inFlightMessage;

    // A retry that failed again is one failure, not two: its card goes so the new one takes its
    // place, instead of leaving a dead "Sending again..." button stranded above it.
    if (retryingCard) {
        retryingCard.card.remove();
        retryingCard = null;
    }

    chatLog.style.display = 'flex';
    document.querySelector('.main-content').classList.add('is-chatting');

    const card = document.createElement('div');
    card.style.cssText = 'display: flex; justify-content: space-between; align-items: center; font-family: \'Inter\', sans-serif; font-size: 0.8rem; line-height: 1.45; padding: 0.7rem 0.9rem; margin: 0.25rem 0; border: 1px solid var(--border); border-left: 3px solid #c0392b; border-radius: 8px; background: var(--card-bg); gap: 1rem;';

    const content = document.createElement('div');
    content.style.cssText = 'display: flex; flex-direction: column; gap: 0.15rem; flex: 1;';

    const heading = document.createElement('div');
    heading.style.cssText = 'font-weight: 600; color: #c0392b;';
    heading.innerText = title;
    content.appendChild(heading);

    const body = document.createElement('div');
    body.style.cssText = 'opacity: 0.8;';
    body.innerText = hint;
    content.appendChild(body);
    
    card.appendChild(content);

    if (retryable && message) {
        const actions = document.createElement('div');
        actions.style.cssText = 'display: flex; align-items: center; flex-shrink: 0;';

        const retry = document.createElement('button');
        retry.innerText = 'Retry';
        retry.style.cssText = 'padding: 0.4rem 0.9rem; border-radius: 6px; border: none; background: var(--text-main); color: var(--bg-color); cursor: pointer; font-family: inherit; font-size: 0.75rem; font-weight: 500; white-space: nowrap; transition: opacity 0.2s;';
        
        const reset = () => {
            retry.disabled = false;
            retry.style.opacity = '1';
            retry.style.cursor = 'pointer';
            retry.innerText = 'Retry';
        };

        retry.addEventListener('click', () => {
            retry.disabled = true;
            retry.style.opacity = '0.5';
            retry.style.cursor = 'default';
            retry.innerText = 'Sending again...';
            retryingCard = { card, reset };
            sendTurn(message, { isRetry: true });
        });
        
        actions.appendChild(retry);
        card.appendChild(actions);
    }

    chatLog.appendChild(card);
    scrollChatToBottom();
    return card;
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

// Say plainly when the answer is recovered prose rather than a real report, so a degraded answer is
// never mistaken for a confident one. Shared across every report type: the meaning doesn't change
// depending on which agent produced the reply.
function appendSalvagedNotice() {
    appendBlock(
        'The model did not return a structured report. This is the closest answer recovered from its reply — the trace above shows what was actually checked.',
        'font-size: 0.75rem; padding: 0 0.9rem; opacity: 0.7; font-style: italic;',
    );
}

function appendFactsTable(facts) {
    if (!facts || facts.length === 0) return;
    const table = document.createElement('table');
    table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse;';
    facts.forEach((fact) => {
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

function formatMemoryMb(mb) {
    if (mb == null) return '';
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function renderDiskReport(report) {
    if (!report) return;

    if (report.summary) appendMessage('assistant', report.summary);
    if (report.salvaged) appendSalvagedNotice();
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

    appendFactsTable(report.facts);

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

function renderAppsTable(apps) {
    const table = document.createElement('table');
    table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse; width: calc(100% - 1.8rem);';
    apps.forEach((app) => {
        const tr = document.createElement('tr');

        const name = document.createElement('td');
        name.style.cssText = 'padding: 0.25rem 0.9rem 0.25rem 0; font-weight: 500; white-space: nowrap; vertical-align: top;';
        name.innerText = app.name;
        tr.appendChild(name);

        const stats = document.createElement('td');
        stats.style.cssText = 'padding: 0.25rem 0.9rem 0.25rem 0; opacity: 0.75; white-space: nowrap; vertical-align: top;';
        const bits = [];
        if (app.cpu_percent != null) bits.push(`${app.cpu_percent}% CPU`);
        if (app.memory_mb != null) bits.push(formatMemoryMb(app.memory_mb));
        if (app.processes != null) bits.push(`${app.processes} proc${app.processes === 1 ? '' : 's'}`);
        if (app.uptime) bits.push(app.uptime);
        stats.innerText = bits.join(' · ');
        tr.appendChild(stats);

        const detail = document.createElement('td');
        detail.style.cssText = 'padding: 0.25rem 0; opacity: 0.65; word-break: break-word;';
        detail.innerText = app.detail || '';
        tr.appendChild(detail);

        table.appendChild(tr);
    });
    chatLog.appendChild(table);
}

function renderProcessesTable(processes) {
    const table = document.createElement('table');
    table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse;';
    processes.forEach((proc) => {
        const tr = document.createElement('tr');

        const pid = document.createElement('td');
        pid.style.cssText = 'padding: 0.15rem 0.6rem 0.15rem 0; opacity: 0.55; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; vertical-align: top;';
        pid.innerText = proc.pid != null ? proc.pid : '';
        tr.appendChild(pid);

        const name = document.createElement('td');
        name.style.cssText = 'padding: 0.15rem 0.9rem 0.15rem 0; font-weight: 500; vertical-align: top;';
        name.innerText = proc.name;
        tr.appendChild(name);

        const stats = document.createElement('td');
        stats.style.cssText = 'padding: 0.15rem 0; opacity: 0.75;';
        const bits = [];
        if (proc.cpu_percent != null) bits.push(`${proc.cpu_percent}% CPU`);
        if (proc.memory_mb != null) bits.push(formatMemoryMb(proc.memory_mb));
        if (proc.state) bits.push(proc.state);
        stats.innerText = bits.join(' · ');
        tr.appendChild(stats);

        table.appendChild(tr);
    });
    chatLog.appendChild(table);
}

function renderProcessReport(report) {
    if (!report) return;

    if (report.summary) appendMessage('assistant', report.summary);
    if (report.salvaged) appendSalvagedNotice();
    if (report.explanation) {
        appendBlock(report.explanation, 'font-size: 0.82rem; line-height: 1.5; padding: 0 0.9rem; opacity: 0.9;');
    }

    if (report.apps && report.apps.length > 0) {
        // A real foreground/background split only when the session actually let us see windows.
        // Rendering it on a degraded answer would show a distinction that was never observed.
        if (report.confidence === 'full') {
            const foreground = report.apps.filter((a) => a.state === 'foreground');
            const background = report.apps.filter((a) => a.state !== 'foreground');
            if (foreground.length > 0) {
                appendBlock('Active windows', 'font-size: 0.72rem; padding: 0.3rem 0.9rem 0; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.03em;');
                renderAppsTable(foreground);
            }
            if (background.length > 0) {
                appendBlock('Background', 'font-size: 0.72rem; padding: 0.3rem 0.9rem 0; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.03em;');
                renderAppsTable(background);
            }
        } else {
            renderAppsTable(report.apps);
        }

        // Above the app list is where the split would have gone, so the limitation is read right
        // where its absence would otherwise be confusing.
        if (report.confidence === 'degraded') {
            appendBlock(
                'Window information is not available for this session, so which of these applications have a visible window cannot be determined. The list itself is accurate.',
                'font-size: 0.75rem; padding: 0.3rem 0.9rem 0; opacity: 0.7; font-style: italic;',
            );
        }
    }

    if (report.processes && report.processes.length > 0) {
        renderProcessesTable(report.processes);
    }

    const load = report.load;
    if (load) {
        if (load.cpu_percent != null) {
            const barWrap = document.createElement('div');
            barWrap.style.cssText = 'width: 100%; max-width: 400px; margin: 0.4rem 0.9rem; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; height: 10px;';
            const bar = document.createElement('div');
            const pct = Math.min(100, Math.max(0, load.cpu_percent));
            bar.style.cssText = `height: 100%; width: ${pct}%; background: ${LOAD_SEVERITY_COLORS[load.severity] || '#888'};`;
            barWrap.appendChild(bar);
            chatLog.appendChild(barWrap);
        }

        const parts = [];
        if (load.cpu_percent != null) parts.push(`${load.cpu_percent}% CPU`);
        if (load.memory_percent != null) parts.push(`${load.memory_percent}% memory`);
        if (load.load_1m != null) {
            parts.push(load.cores != null ? `${load.load_1m} load / ${load.cores} cores` : `${load.load_1m} load`);
        }
        if (load.severity) parts.push(load.severity);
        if (parts.length > 0) {
            appendBlock(parts.join(' · '), 'font-size: 0.75rem; padding: 0 0.9rem; opacity: 0.75;');
        }
    }

    appendFactsTable(report.facts);

    // The one thing worth noticing, called out above the suggestion so it reads as the headline
    // rather than one more line in a list the user has to scan.
    if (report.standout) {
        appendBlock(report.standout, 'font-size: 0.8rem; padding: 0.4rem 0.9rem; line-height: 1.5; border-left: 2px solid var(--border); margin: 0.3rem 0.9rem; font-weight: 500;');
    }

    if (report.suggestion) {
        appendBlock(report.suggestion, 'font-size: 0.8rem; padding: 0.4rem 0.9rem; line-height: 1.5; border-left: 2px solid var(--border); margin: 0.3rem 0.9rem;');
    }
}

// The five rungs, in the order they are walked. A failure at one implies nothing about the ones
// above it, which is exactly why the chain is rendered instead of a single online/offline verdict.
const LADDER_RUNGS = [
    ['link', 'Link'],
    ['address', 'Address'],
    ['gateway', 'Gateway'],
    ['dns', 'DNS'],
    ['internet', 'Internet'],
];

function renderConnectivityLadder(connectivity) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin: 0.5rem 0.9rem;';

    LADDER_RUNGS.forEach(([key, label], index) => {
        const status = connectivity[key] || 'unknown';
        const failed = connectivity.failed_at === key;

        const rung = document.createElement('div');
        const color = RUNG_COLORS[status] || RUNG_COLORS.unknown;
        // The failing rung is the answer, so it carries the only filled background in the row.
        rung.style.cssText = [
            'display: flex; align-items: center; gap: 0.3rem;',
            'font-family: \'Inter\', sans-serif; font-size: 0.72rem;',
            'padding: 0.2rem 0.5rem; border-radius: 5px;',
            `border: 1px solid ${failed ? color : 'var(--border)'};`,
            failed ? `background: ${color}22; font-weight: 600;` : '',
            status === 'unknown' ? 'opacity: 0.5;' : '',
        ].join(' ');

        const dot = document.createElement('span');
        dot.style.cssText = `width: 6px; height: 6px; border-radius: 50%; background: ${color}; flex: none;`;
        rung.appendChild(dot);

        const text = document.createElement('span');
        text.innerText = label;
        rung.appendChild(text);
        wrap.appendChild(rung);

        if (index < LADDER_RUNGS.length - 1) {
            const arrow = document.createElement('span');
            arrow.style.cssText = 'opacity: 0.3; font-size: 0.7rem;';
            arrow.innerText = '→';
            wrap.appendChild(arrow);
        }
    });

    chatLog.appendChild(wrap);

    const parts = [];
    if (connectivity.severity) parts.push(connectivity.severity);
    if (connectivity.failed_at) {
        parts.push(`first failure at ${connectivity.failed_at}`);
    } else if (connectivity.severity === 'online') {
        parts.push('every layer checked out');
    }
    if (parts.length > 0) {
        const line = appendBlock(parts.join(' · '), 'font-size: 0.75rem; padding: 0 0.9rem; opacity: 0.8;');
        if (line && connectivity.severity) {
            line.style.color = NETWORK_SEVERITY_COLORS[connectivity.severity] || '';
        }
    }
}

function renderInterfacesTable(interfaces) {
    const table = document.createElement('table');
    table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse; width: calc(100% - 1.8rem);';
    interfaces.forEach((iface) => {
        const tr = document.createElement('tr');

        const name = document.createElement('td');
        name.style.cssText = 'padding: 0.25rem 0.9rem 0.25rem 0; font-weight: 500; white-space: nowrap; vertical-align: top;';
        name.innerText = iface.name;
        tr.appendChild(name);

        const stats = document.createElement('td');
        stats.style.cssText = 'padding: 0.25rem 0.9rem 0.25rem 0; opacity: 0.75; white-space: nowrap; vertical-align: top;';
        const bits = [];
        if (iface.kind) bits.push(iface.kind);
        if (iface.state) bits.push(iface.state);
        if (iface.ipv4) bits.push(iface.ipv4);
        if (iface.ipv6) bits.push(iface.ipv6);
        if (iface.signal_dbm != null) bits.push(`${iface.signal_dbm} dBm`);
        stats.innerText = bits.join(' · ');
        tr.appendChild(stats);

        const detail = document.createElement('td');
        detail.style.cssText = 'padding: 0.25rem 0; opacity: 0.65; word-break: break-word;';
        detail.innerText = iface.detail || '';
        tr.appendChild(detail);

        table.appendChild(tr);
    });
    chatLog.appendChild(table);
}

function renderConnectionsTable(connections) {
    const table = document.createElement('table');
    table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse; width: calc(100% - 1.8rem);';
    connections.forEach((entry) => {
        const tr = document.createElement('tr');

        const name = document.createElement('td');
        name.style.cssText = 'padding: 0.25rem 0.9rem 0.25rem 0; font-weight: 500; white-space: nowrap; vertical-align: top;';
        name.innerText = entry.name;
        tr.appendChild(name);

        const stats = document.createElement('td');
        stats.style.cssText = 'padding: 0.25rem 0.9rem 0.25rem 0; opacity: 0.75; white-space: nowrap; vertical-align: top;';
        const bits = [];
        if (entry.connections != null) bits.push(`${entry.connections} conn${entry.connections === 1 ? '' : 's'}`);
        if (entry.listening) bits.push(`${entry.listening} listening`);
        stats.innerText = bits.join(' · ');
        tr.appendChild(stats);

        const detail = document.createElement('td');
        detail.style.cssText = 'padding: 0.25rem 0; opacity: 0.65; word-break: break-word;';
        detail.innerText = entry.detail || '';
        tr.appendChild(detail);

        table.appendChild(tr);
    });
    chatLog.appendChild(table);
}

const EXPOSURE_LABELS = {
    'all-interfaces': 'reachable from your network',
    local: 'this machine only',
    unknown: 'exposure unknown',
};

function renderListeningTable(ports) {
    const table = document.createElement('table');
    table.style.cssText = 'font-family: \'Inter\', sans-serif; font-size: 0.78rem; margin: 0.4rem 0.9rem; border-collapse: collapse; width: calc(100% - 1.8rem);';
    ports.forEach((entry) => {
        const tr = document.createElement('tr');

        const port = document.createElement('td');
        port.style.cssText = 'padding: 0.15rem 0.6rem 0.15rem 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; vertical-align: top;';
        port.innerText = [entry.protocol, entry.port].filter((v) => v != null && v !== '').join('/');
        tr.appendChild(port);

        const name = document.createElement('td');
        name.style.cssText = 'padding: 0.15rem 0.9rem 0.15rem 0; font-weight: 500; vertical-align: top;';
        name.innerText = entry.process || '';
        tr.appendChild(name);

        // Whether a port is reachable from outside is the security-relevant half of the row, so it
        // is spelled out rather than left as a bind address the reader has to interpret.
        const exposure = document.createElement('td');
        exposure.style.cssText = 'padding: 0.15rem 0; opacity: 0.75; word-break: break-word;';
        const label = EXPOSURE_LABELS[entry.exposure] || '';
        exposure.innerText = [entry.address, label].filter(Boolean).join(' · ');
        if (entry.exposure === 'all-interfaces') {
            exposure.style.color = NETWORK_SEVERITY_COLORS.degraded;
            exposure.style.opacity = '1';
        }
        tr.appendChild(exposure);

        table.appendChild(tr);
    });
    chatLog.appendChild(table);
}

function renderNetworkReport(report) {
    if (!report) return;

    if (report.summary) appendMessage('assistant', report.summary);
    if (report.salvaged) appendSalvagedNotice();
    if (report.explanation) {
        appendBlock(report.explanation, 'font-size: 0.82rem; line-height: 1.5; padding: 0 0.9rem; opacity: 0.9;');
    }

    // The ladder goes first: where it broke is the answer, and everything below is supporting detail.
    if (report.connectivity) renderConnectivityLadder(report.connectivity);

    if (report.interfaces && report.interfaces.length > 0) {
        appendBlock('Interfaces', 'font-size: 0.72rem; padding: 0.3rem 0.9rem 0; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.03em;');
        renderInterfacesTable(report.interfaces);
    }

    if (report.connections && report.connections.length > 0) {
        appendBlock('Connections by application', 'font-size: 0.72rem; padding: 0.3rem 0.9rem 0; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.03em;');
        renderConnectionsTable(report.connections);

        // Stated directly beneath the list it qualifies, so the caveat is read with the data rather
        // than after it.
        if (report.confidence === 'degraded') {
            appendBlock(
                'Some sockets could not be matched to a program, which needs root, so the owners of those connections are unknown. The counts, ports and remote addresses above are accurate.',
                'font-size: 0.75rem; padding: 0.3rem 0.9rem 0; opacity: 0.7; font-style: italic;',
            );
        }
    }

    if (report.listening && report.listening.length > 0) {
        appendBlock('Listening ports', 'font-size: 0.72rem; padding: 0.3rem 0.9rem 0; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.03em;');
        renderListeningTable(report.listening);
    }

    appendFactsTable(report.facts);

    if (report.standout) {
        appendBlock(report.standout, 'font-size: 0.8rem; padding: 0.4rem 0.9rem; line-height: 1.5; border-left: 2px solid var(--border); margin: 0.3rem 0.9rem; font-weight: 500;');
    }

    if (report.suggestion) {
        appendBlock(report.suggestion, 'font-size: 0.8rem; padding: 0.4rem 0.9rem; line-height: 1.5; border-left: 2px solid var(--border); margin: 0.3rem 0.9rem;');
    }
}

// One entry per agent that renders a structured report, keyed by the orchestrator's `mode`. Adding a
// fifth agent means adding a render function and a line here, not another branch in the switch below.
const REPORT_RENDERERS = { disk: renderDiskReport, process: renderProcessReport, network: renderNetworkReport };

function handleOrchestratorEvent(rawEvent) {
    let data;
    try {
        data = JSON.parse(rawEvent.data);
    } catch (e) {
        return;
    }

    switch (data.type) {
        case 'started':
            setTurnInProgress(true);
            // The failed turn's card is replaced by the retry's own trace, so the transcript shows
            // one attempt rather than a stack of dead ends.
            if (retryingCard) {
                retryingCard.card.remove();
                retryingCard = null;
            }
            startTrace();
            break;
        case 'model_loading':
            // Local-provider only: a model not already resident in Ollama can take a while to load
            // before the first token arrives. Purely additive to the trace header - a cloud turn
            // never emits this.
            setTraceHeader(`Loading ${data.model_id}…`);
            break;
        case 'session_created':
            currentSessionId = data.session_id;
            sessionsById[data.session_id] = {
                session_id: data.session_id,
                session_name: data.session_name,
                is_active: true,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };
            renderSessionList();
            break;
        case 'session_renamed':
            if (sessionsById[data.session_id]) {
                sessionsById[data.session_id].session_name = data.session_name;
                renderSessionList();
            }
            break;
        case 'already_running':
            turnPending = false;
            // Nothing was attempted, so the failure card stays exactly as it was, button and all -
            // the retry is still available once the other chat finishes.
            if (retryingCard) {
                retryingCard.reset();
                retryingCard = null;
            }
            showRunningBanner(data.session_id, data.session_name);
            break;
        case 'classified': {
            const headers = {
                disk: 'Checking storage',
                process: "Checking what's running",
                network: 'Checking the network',
            };
            setTraceHeader(headers[data.mode] || 'Answering');
            break;
        }
        case 'thinking_delta':
            appendThinkingDelta(data.text);
            break;
        case 'rate_limited':
        case 'retrying': {
            const active = ensureTrace();
            active.details.open = true;
            startRetryCycling();
            break;
        }
        case 'permission_request':
            renderPermissionRequest(data);
            break;
        case 'permission_resolved':
            resolvePermissionRequest(data);
            break;
        case 'tool_call':
            startTraceRow(data);
            break;
        case 'tool_result':
            finishTraceRow(data);
            break;
        case 'final': {
            turnPending = false;
            setTurnInProgress(false);
            // The general path doesn't stream, so its thinking arrives whole; keep it in the panel.
            if (data.thinking && trace && !trace.thinking.innerText) {
                trace.thinking.innerText = data.thinking;
            }
            const report = data[`${data.mode}_report`];
            const salvaged = Boolean(report && report.salvaged);
            closeTrace(salvaged);
            const renderer = REPORT_RENDERERS[data.mode];
            if (renderer) {
                renderer(report);
            } else {
                appendMessage('assistant', data.content);
            }
            break;
        }
        case 'error':
            turnPending = false;
            setTurnInProgress(false);
            closeTrace(true);
            renderTurnFailure(data);
            break;
    }
}

// A socket that closes with a turn still outstanding is the one failure the backend cannot report,
// since its own error event would have travelled down this socket. Without this the UI would sit on
// a spinning trace forever; instead the turn ends the same way any other failure does, with a card
// that can send it again.
function handleSocketClose(event) {
    // A close from a socket that has already been replaced - a retry opens a fresh one the moment the
    // old connection drops - says nothing about the turn now in flight on its successor.
    if (event && event.target !== orchestratorSocket) return;
    if (!turnPending) return;
    turnPending = false;
    setTurnInProgress(false);
    closeTrace(true);
    renderTurnFailure({ detail: 'The connection to the backend closed before this turn finished.' });
}

function ensureSocket(onReady) {
    if (orchestratorSocket && orchestratorSocket.readyState === WebSocket.OPEN) {
        onReady();
        return;
    }
    // CLOSING counts as gone: a retry is sent right after the connection dropped, and waiting on
    // `open` from a socket that is on its way out would hang the turn forever.
    if (
        !orchestratorSocket
        || orchestratorSocket.readyState === WebSocket.CLOSED
        || orchestratorSocket.readyState === WebSocket.CLOSING
    ) {
        orchestratorSocket = new WebSocket(WS_URL);
        orchestratorSocket.addEventListener('message', handleOrchestratorEvent);
        // A socket error is always followed by a close, so a turn killed by the connection is
        // reported once, from the close handler, as a retryable failure rather than twice.
        orchestratorSocket.addEventListener('error', () => {
            if (!turnPending) appendMessage('error', 'Connection error.');
        });
        orchestratorSocket.addEventListener('close', handleSocketClose);
    }
    orchestratorSocket.addEventListener('open', onReady, { once: true });
}

// Both a first attempt and a retry go through here, so the retry sends byte-for-byte the same turn
// the user already saw fail - only `is_retry` differs, which tells the backend the failed attempt's
// unanswered user row is being replaced rather than added to. `session_id` is read at send time, not
// captured: a turn that failed on a brand new chat already created its session, and the retry has to
// land in that session instead of opening a second one.
function sendTurn(message, options = {}) {
    inFlightMessage = message;
    turnPending = true;

    ensureSocket(() => {
        orchestratorSocket.send(JSON.stringify({
            provider: selectedProvider,
            model_id: selectedModelId,
            message,
            session_id: currentSessionId,
            is_retry: Boolean(options.isRetry),
        }));

        if (currentSessionId && sessionsById[currentSessionId]) {
            sessionsById[currentSessionId].updated_at = new Date().toISOString();
            renderSessionList();
        }
    });
}

function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || !selectedProvider || !selectedModelId) return;

    chatInput.value = '';
    appendMessage('user', message);
    sendTurn(message);
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
});
