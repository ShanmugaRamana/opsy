const BACKEND_URL = 'http://localhost:8000';

// ---- Left nav switching ----

const navItems = document.querySelectorAll('.settings-nav-item');
const panels = document.querySelectorAll('.settings-panel');

navItems.forEach(item => {
    item.addEventListener('click', () => {
        if (item.classList.contains('active')) return;

        navItems.forEach(i => i.classList.remove('active'));
        item.classList.add('active');

        const section = item.dataset.section;
        panels.forEach(panel => {
            panel.classList.toggle('active', panel.id === `panel-${section}`);
        });
    });
});

// ---- Profile: read-only display of the onboarded user ----

const ROLE_LABELS = {
    'developer': 'Developer',
    'sysadmin': 'Sysadmin',
    'homelab': 'Homelab / Self-hoster',
    'student': 'Student',
    'desktop-user': 'Just a regular desktop user',
};

const EXPERIENCE_LABELS = {
    'beginner': 'Beginner',
    'intermediate': 'Intermediate',
    'power-user': 'Power User',
    'sysadmin-pro': 'Sysadmin-Pro',
};

function formatDate(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

async function loadProfile() {
    const errorEl = document.getElementById('profile-error');

    try {
        const res = await fetch(`${BACKEND_URL}/linux/users`);
        if (!res.ok) throw new Error(`users fetch failed: ${res.status}`);

        const users = await res.json();
        const user = users[0];
        if (!user) {
            errorEl.innerText = 'No profile found — this machine has not been set up yet.';
            errorEl.style.display = 'block';
            return;
        }

        document.getElementById('profile-avatar').src = `/${user.profile_pic}`;
        document.getElementById('profile-name').innerText = user.name;
        document.getElementById('profile-role').innerText = ROLE_LABELS[user.role_use_case] || user.role_use_case;
        document.getElementById('profile-experience').innerText =
            EXPERIENCE_LABELS[user.linux_experience] || user.linux_experience;
        document.getElementById('profile-created').innerText = formatDate(user.created_at);
        document.getElementById('profile-card').style.display = 'flex';
    } catch (e) {
        console.error('Could not load profile:', e);
        errorEl.innerText = 'Could not reach the backend to load your profile.';
        errorEl.style.display = 'block';
    }
}

loadProfile();

// ---- Preferences ----

// The toggle starts disabled and only becomes usable once the stored value has been read, so it can
// never show a default that isn't what the backend actually has.
const alwaysApproveToggle = document.getElementById('pref-always-approve');

async function loadPreferences() {
    const errorEl = document.getElementById('pref-error');

    try {
        const res = await fetch(`${BACKEND_URL}/linux/users/preferences`);
        if (!res.ok) throw new Error(`preferences fetch failed: ${res.status}`);

        const prefs = await res.json();
        alwaysApproveToggle.checked = Boolean(prefs.always_approve_commands);
        alwaysApproveToggle.disabled = false;
    } catch (e) {
        console.error('Could not load preferences:', e);
        errorEl.innerText = 'Could not load your preferences. Reload the page to try again.';
        errorEl.style.display = 'block';
    }
}

alwaysApproveToggle.addEventListener('change', async () => {
    const errorEl = document.getElementById('pref-error');
    const desired = alwaysApproveToggle.checked;

    errorEl.style.display = 'none';
    alwaysApproveToggle.disabled = true;

    try {
        const res = await fetch(`${BACKEND_URL}/linux/users/preferences`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ always_approve_commands: desired }),
        });
        if (!res.ok) throw new Error(`preferences save failed: ${res.status}`);

        const saved = await res.json();
        alwaysApproveToggle.checked = Boolean(saved.always_approve_commands);
    } catch (e) {
        // Never leave the switch showing a setting that didn't persist.
        console.error('Could not save preference:', e);
        alwaysApproveToggle.checked = !desired;
        errorEl.innerText = "Couldn't save that preference. Please try again.";
        errorEl.style.display = 'block';
    } finally {
        alwaysApproveToggle.disabled = false;
    }
});

loadPreferences();

// ---- Local models: installed (with delete) + hardware-matched suggestions (with download) ----

const FIT_LABELS = {
    recommended: { label: 'Recommended', color: '#10b981' },
    possible: { label: 'Possible', color: 'var(--text-muted)' },
};

function formatSize(gb) {
    return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(gb * 1024)} MB`;
}

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return null;
    return formatSize(bytes / (1024 ** 3));
}

function showEnvBanner(detail) {
    const banner = document.getElementById('local-env-banner');
    document.getElementById('local-env-detail').innerText = detail;
    banner.style.display = 'flex';
}

function hideEnvBanner() {
    document.getElementById('local-env-banner').style.display = 'none';
}

// Same self-healing idea as the setup page: while Ollama isn't reachable, keep quietly re-checking
// instead of asking the user to click something.
const LOCAL_RETRY_INTERVAL_MS = 4000;
let localRetryTimer = null;
let suggestedLoadInFlight = false;
let suggestedHasRendered = false;

function scheduleLocalRetry() {
    if (localRetryTimer !== null || document.hidden) return;
    localRetryTimer = setInterval(loadSuggestedModels, LOCAL_RETRY_INTERVAL_MS);
}

function stopLocalRetry() {
    if (localRetryTimer === null) return;
    clearInterval(localRetryTimer);
    localRetryTimer = null;
}

function renderInstalledModels(models) {
    const loader = document.getElementById('installed-models-loader');
    const list = document.getElementById('installed-models-list');
    const empty = document.getElementById('installed-models-empty');
    loader.style.display = 'none';

    if (!models.length) {
        list.style.display = 'none';
        list.innerHTML = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';

    list.innerHTML = models.map(model => {
        const parts = [];
        if (model.params_b !== null && model.params_b !== undefined) parts.push(`${model.params_b}B`);
        if (model.quantization) parts.push(model.quantization);
        const size = formatBytes(model.size_bytes);
        if (size) parts.push(size);

        return `
            <div class="settings-model-row">
                <div style="display: flex; flex-direction: column; gap: 0.15rem;">
                    <span style="font-family: 'Clash Display', sans-serif; font-size: 1.05rem; font-weight: 500; color: var(--text-main);">${model.display_name}</span>
                    <span style="font-family: 'Clash Display', sans-serif; font-size: 0.85rem; color: var(--text-muted);">${parts.join(' · ')}</span>
                </div>
                <button class="settings-pill-btn danger local-delete-btn" data-model-key="${model.model_key}" data-display-name="${model.display_name}">Delete</button>
            </div>
        `;
    }).join('');

    list.style.display = 'flex';
}

async function loadInstalledModels() {
    const errorEl = document.getElementById('local-installed-error');
    errorEl.style.display = 'none';

    try {
        const res = await fetch(`${BACKEND_URL}/linux/local-models/`);
        if (!res.ok) throw new Error(`installed fetch failed: ${res.status}`);
        const models = await res.json();
        renderInstalledModels(models.filter(m => m.status === 'ready'));
    } catch (e) {
        console.error('Could not load installed local models:', e);
        document.getElementById('installed-models-loader').style.display = 'none';
        errorEl.innerText = 'Could not reach the backend to load installed models.';
        errorEl.style.display = 'block';
    }
}

function renderSuggestedModels(category, models, note) {
    const blurb = document.getElementById('suggested-models-blurb');
    blurb.innerText = category ? `${category.label} — ${category.blurb}` : '';

    const list = document.getElementById('suggested-models-list');
    const noteEl = document.getElementById('suggested-models-note');

    if (!models.length) {
        list.style.display = 'none';
        list.innerHTML = '';
    } else {
        list.innerHTML = models.map(model => {
            const fit = FIT_LABELS[model.fit] || FIT_LABELS.possible;
            const buttonLabel = model.installed ? 'Installed' : 'Download';
            const detail = `${model.params_b}B · ${model.quantization} · ${formatSize(model.size_gb)}`;

            return `
                <div class="settings-model-row">
                    <div style="display: flex; flex-direction: column; gap: 0.15rem;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span style="font-family: 'Clash Display', sans-serif; font-size: 1.05rem; font-weight: 500; color: var(--text-main);">${model.display_name}</span>
                            <span style="font-family: 'Inter', sans-serif; font-size: 0.7rem; color: ${fit.color}; text-transform: uppercase; letter-spacing: 0.05em;">${fit.label}</span>
                        </div>
                        <span style="font-family: 'Clash Display', sans-serif; font-size: 0.85rem; color: var(--text-muted);">${detail}</span>
                    </div>
                    <button class="settings-pill-btn local-download-btn" data-model-key="${model.model_key}" data-display-name="${model.display_name}" ${model.installed ? 'disabled' : ''}>${buttonLabel}</button>
                </div>
            `;
        }).join('');
        list.style.display = 'flex';
    }

    if (note) {
        noteEl.innerText = note;
        noteEl.style.display = 'block';
    } else {
        noteEl.style.display = 'none';
    }
}

async function loadSuggestedModels() {
    if (suggestedLoadInFlight) return;
    suggestedLoadInFlight = true;

    if (!suggestedHasRendered) {
        document.getElementById('suggested-models-loader').style.display = 'flex';
    }

    try {
        const res = await fetch(`${BACKEND_URL}/linux/local-models/recommendations`);
        if (!res.ok) throw new Error(`recommendations fetch failed: ${res.status}`);
        const data = await res.json();

        if (data.environment.running) {
            hideEnvBanner();
            stopLocalRetry();
        } else {
            showEnvBanner(data.environment.detail);
            scheduleLocalRetry();
        }

        renderSuggestedModels(data.category, data.models, data.note);
        suggestedHasRendered = true;
    } catch (e) {
        console.error('Could not load local model recommendations:', e);
        renderSuggestedModels(null, [], 'Could not reach the backend to load suggested models. Retrying…');
        suggestedHasRendered = true;
        scheduleLocalRetry();
    } finally {
        suggestedLoadInFlight = false;
        document.getElementById('suggested-models-loader').style.display = 'none';
    }
}

document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopLocalRetry();
    } else if (document.getElementById('local-env-banner').style.display !== 'none') {
        loadSuggestedModels();
        scheduleLocalRetry();
    }
});

document.getElementById('suggested-models-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('.local-download-btn');
    if (!btn || btn.disabled) return;

    const modelKey = btn.dataset.modelKey;
    const errorEl = document.getElementById('local-download-error');
    errorEl.style.display = 'none';

    btn.disabled = true;
    btn.innerText = 'Starting…';

    let res;
    try {
        res = await fetch(`${BACKEND_URL}/linux/local-models/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_key: modelKey }),
        });
    } catch (err) {
        errorEl.innerText = "Couldn't reach the backend to start the download.";
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerText = 'Download';
        return;
    }

    if (res.status === 202) {
        window.location.href = `/download?key=${encodeURIComponent(modelKey)}`;
        return;
    }

    let detail = 'Something went wrong starting the download.';
    try {
        const body = await res.json();
        detail = body.detail || detail;
    } catch (err) {
        // Response body wasn't JSON - fall back to the generic message above.
    }

    if (res.status === 409) {
        errorEl.innerHTML = `${detail} <a href="/download" style="color: var(--text-main); text-decoration: underline;">View progress</a>`;
    } else if (res.status === 503) {
        showEnvBanner(detail);
        scheduleLocalRetry();
        errorEl.innerText = detail;
    } else {
        errorEl.innerText = detail;
    }
    errorEl.style.display = 'block';
    btn.disabled = false;
    btn.innerText = 'Download';
});

document.getElementById('installed-models-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('.local-delete-btn');
    if (!btn || btn.disabled) return;

    const modelKey = btn.dataset.modelKey;
    const displayName = btn.dataset.displayName;
    const errorEl = document.getElementById('local-installed-error');
    errorEl.style.display = 'none';

    if (!confirm(`Delete ${displayName}? This removes it from disk.`)) return;

    btn.disabled = true;
    btn.innerText = 'Deleting…';

    try {
        const res = await fetch(`${BACKEND_URL}/linux/local-models/${encodeURIComponent(modelKey)}`, {
            method: 'DELETE',
        });
        if (!res.ok) throw new Error(`delete failed: ${res.status}`);

        btn.closest('.settings-model-row').remove();

        const list = document.getElementById('installed-models-list');
        if (!list.querySelector('.settings-model-row')) {
            list.style.display = 'none';
            document.getElementById('installed-models-empty').style.display = 'block';
        }

        // The suggested list's "Installed" state and Download buttons depend on this model's status.
        loadSuggestedModels();
    } catch (err) {
        console.error('Could not delete local model:', err);
        errorEl.innerText = `Could not delete ${displayName}. Please try again.`;
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerText = 'Delete';
    }
});

loadInstalledModels();
loadSuggestedModels();

// ---- Cloud models: per-provider add/update key ----

const CLOUD_PROVIDERS = [
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'openai', label: 'OpenAI' },
    { value: 'gemini', label: 'Gemini' },
    { value: 'groq', label: 'Groq' },
];

function formatVerifiedAt(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function providerRowHtml(provider, configured) {
    const statusHtml = configured
        ? `<span style="font-family: 'Inter', sans-serif; font-size: 0.8rem; color: #10b981;">Connected · ••••${configured.key_last4} · verified ${formatVerifiedAt(configured.verified_at)}</span>`
        : `<span style="font-family: 'Inter', sans-serif; font-size: 0.8rem; color: var(--text-muted);">Not configured</span>`;
    const btnLabel = configured ? 'Update Key' : 'Add Key';
    const removeBtnHtml = configured
        ? `<button class="settings-pill-btn danger cloud-remove-btn" data-provider="${provider.value}" data-label="${provider.label}">Remove</button>`
        : '';

    return `
        <div class="settings-provider-row">
            <div style="display: flex; flex-direction: column; gap: 0.2rem;">
                <span style="font-family: 'Clash Display', sans-serif; font-size: 1.05rem; font-weight: 500; color: var(--text-main);">${provider.label}</span>
                ${statusHtml}
            </div>
            <div style="display: flex; gap: 0.5rem; flex-shrink: 0;">
                ${removeBtnHtml}
                <button class="settings-pill-btn cloud-toggle-btn" data-provider="${provider.value}">${btnLabel}</button>
            </div>
        </div>
        <div class="settings-provider-form" data-provider-form="${provider.value}">
            <label style="font-family: 'Clash Display', sans-serif; font-size: 0.9rem; color: var(--text-main);">${provider.label} API Key</label>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
                <input type="password" class="settings-key-input cloud-key-input" placeholder="Enter your API key">
                <button class="settings-pill-btn cloud-save-btn" data-provider="${provider.value}" style="background: var(--text-main); color: var(--bg-color); border-color: var(--text-main);">Verify</button>
            </div>
            <p class="cloud-provider-error" style="display:none; color:#dc2626; margin:0; font-size:0.85rem;"></p>
        </div>
    `;
}

async function loadCloudProviders() {
    const loader = document.getElementById('cloud-provider-loader');
    const list = document.getElementById('cloud-provider-list');

    let configuredByProvider = {};
    try {
        const res = await fetch(`${BACKEND_URL}/linux/byok/keys`);
        if (!res.ok) throw new Error(`keys fetch failed: ${res.status}`);
        const rows = await res.json();
        configuredByProvider = Object.fromEntries(rows.map(r => [r.provider, r]));
    } catch (e) {
        console.error('Could not load configured cloud providers, showing all as not configured:', e);
    }

    list.innerHTML = CLOUD_PROVIDERS.map(p => providerRowHtml(p, configuredByProvider[p.value])).join('');
    loader.style.display = 'none';
    list.style.display = 'flex';
}

document.getElementById('cloud-provider-list').addEventListener('click', async (e) => {
    const removeBtn = e.target.closest('.cloud-remove-btn');
    if (removeBtn) {
        const provider = removeBtn.dataset.provider;
        const label = removeBtn.dataset.label;
        if (!confirm(`Remove the saved ${label} key? You'll need to re-enter it to use ${label} again.`)) return;

        removeBtn.disabled = true;
        removeBtn.innerText = 'Removing…';

        try {
            const res = await fetch(`${BACKEND_URL}/linux/byok/key/${encodeURIComponent(provider)}`, {
                method: 'DELETE',
            });
            if (!res.ok) throw new Error(`delete failed: ${res.status}`);
            loadCloudProviders();
        } catch (err) {
            console.error('Could not remove cloud provider key:', err);
            removeBtn.disabled = false;
            removeBtn.innerText = 'Remove';
            alert(`Could not remove the ${label} key. Please try again.`);
        }
        return;
    }

    const toggleBtn = e.target.closest('.cloud-toggle-btn');
    if (toggleBtn) {
        const provider = toggleBtn.dataset.provider;
        const form = document.querySelector(`.settings-provider-form[data-provider-form="${provider}"]`);
        form.classList.toggle('open');
        if (form.classList.contains('open')) form.querySelector('.cloud-key-input').focus();
        return;
    }

    const saveBtn = e.target.closest('.cloud-save-btn');
    if (!saveBtn) return;

    const provider = saveBtn.dataset.provider;
    const form = document.querySelector(`.settings-provider-form[data-provider-form="${provider}"]`);
    const input = form.querySelector('.cloud-key-input');
    const errorEl = form.querySelector('.cloud-provider-error');
    const apiKey = input.value.trim();

    errorEl.style.display = 'none';
    if (!apiKey) {
        errorEl.innerText = 'Please enter an API key.';
        errorEl.style.display = 'block';
        return;
    }

    const originalText = saveBtn.innerText;
    saveBtn.disabled = true;
    saveBtn.innerText = 'Verifying…';

    let res;
    try {
        res = await fetch(`${BACKEND_URL}/linux/byok/key`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, api_key: apiKey }),
        });
    } catch (err) {
        errorEl.innerText = `Couldn't reach ${provider} — check your connection.`;
        errorEl.style.display = 'block';
        saveBtn.disabled = false;
        saveBtn.innerText = originalText;
        return;
    }

    if (res.status === 401) {
        errorEl.innerText = `That key was rejected by ${provider}.`;
    } else if (res.status === 503) {
        errorEl.innerText = `Couldn't reach ${provider} — check your connection.`;
    } else if (!res.ok) {
        errorEl.innerText = 'Something went wrong. Please try again.';
    }

    if (!res.ok) {
        errorEl.style.display = 'block';
        saveBtn.disabled = false;
        saveBtn.innerText = originalText;
        return;
    }

    input.value = '';
    form.classList.remove('open');
    saveBtn.disabled = false;
    saveBtn.innerText = originalText;
    loadCloudProviders();
});

loadCloudProviders();
