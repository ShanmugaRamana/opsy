const BACKEND_URL = 'http://localhost:8000';

// ---- Tab switcher (Local Models / Cloud Models) ----

const setupBtns = document.querySelectorAll('.setup-btn');
const slider = document.getElementById('setup-slider');
const localContent = document.getElementById('local-models-content');
const cloudContent = document.getElementById('cloud-models-content');

// Hover effects for inactive buttons
setupBtns.forEach(btn => {
    btn.addEventListener('mouseover', function () {
        if (!this.classList.contains('active')) {
            this.style.color = 'var(--text-main)';
        }
    });
    btn.addEventListener('mouseout', function () {
        if (!this.classList.contains('active')) {
            this.style.color = 'var(--text-muted)';
        }
    });
});

setupBtns[0].addEventListener('click', () => {
    if (setupBtns[0].classList.contains('active')) return;

    setupBtns[0].classList.add('active');
    setupBtns[0].style.color = '#ffffff';

    setupBtns[1].classList.remove('active');
    setupBtns[1].style.color = 'var(--text-muted)';

    slider.style.transform = 'translateX(0)';

    // Fade transition for content
    cloudContent.style.opacity = '0';
    setTimeout(() => {
        cloudContent.style.display = 'none';
        localContent.style.display = 'flex';
        // Trigger reflow
        void localContent.offsetWidth;
        localContent.style.opacity = '1';
    }, 150);
});

setupBtns[1].addEventListener('click', () => {
    if (setupBtns[1].classList.contains('active')) return;

    setupBtns[1].classList.add('active');
    setupBtns[1].style.color = '#ffffff';

    setupBtns[0].classList.remove('active');
    setupBtns[0].style.color = 'var(--text-muted)';

    slider.style.transform = 'translateX(140px)';

    localContent.style.opacity = '0';
    setTimeout(() => {
        localContent.style.display = 'none';
        cloudContent.style.display = 'flex';
        // Trigger reflow
        void cloudContent.offsetWidth;
        cloudContent.style.opacity = '1';
    }, 150);
});

// Set initial content transition styling
localContent.style.transition = 'opacity 0.15s ease';
cloudContent.style.transition = 'opacity 0.15s ease';
cloudContent.style.opacity = '0';

// ---- Dropdown logic ----

const dropdowns = document.querySelectorAll('.custom-dropdown');
dropdowns.forEach(dropdown => {
    const trigger = dropdown.querySelector('.custom-dropdown-trigger');
    const options = dropdown.querySelectorAll('.custom-option');
    const selectedText = dropdown.querySelector('.selected-text');

    // Set initial selected value
    if (dropdown.id === 'local-provider-dropdown') {
        dropdown.dataset.selectedValue = "ollama";
    } else {
        dropdown.dataset.selectedValue = "";
    }

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        // Close other dropdowns
        dropdowns.forEach(d => { if (d !== dropdown) d.classList.remove('open') });
        dropdown.classList.toggle('open');
    });

    options.forEach(option => {
        option.addEventListener('click', () => {
            selectedText.innerText = option.innerText;
            selectedText.style.color = 'var(--text-main)';
            const value = option.dataset.value;
            dropdown.dataset.selectedValue = value;
            dropdown.classList.remove('open');

            if (dropdown.id === 'cloud-provider-dropdown') {
                const apiKeyContainer = document.getElementById('cloud-api-key-container');
                const apiKeyLabel = document.getElementById('cloud-api-key-label');
                apiKeyContainer.style.display = 'flex';
                apiKeyLabel.innerText = `${option.innerText.trim()} API Key`;
            }
        });
    });
});

// Close dropdowns when clicking outside
document.addEventListener('click', () => {
    dropdowns.forEach(dropdown => dropdown.classList.remove('open'));
});

// ---- Hardware profile + insights (dynamic, replacing static fallback values) ----

function formatOsBadge(os) {
    document.getElementById('os-badge').innerText = os || 'Unknown OS';
}

function formatCpuCard(cpu) {
    const valueEl = document.getElementById('cpu-usage-value');
    const labelEl = document.getElementById('cpu-sub-label');
    const cardEl = document.getElementById('cpu-card');

    const parts = [];
    if (cpu.model) parts.push(cpu.model);
    if (cpu.cores !== null && cpu.cores !== undefined) parts.push(`${cpu.cores} Cores`);

    if (cpu.usage_percent !== null && cpu.usage_percent !== undefined) {
        valueEl.innerHTML = `${Math.round(cpu.usage_percent)}<span style="font-size: 0.9rem; color: var(--text-muted); margin-left: 2px;">%</span>`;
    } else {
        valueEl.innerText = '—';
        cardEl.classList.add('hw-card-unavailable');
        parts.push('Utilization unavailable');
    }

    labelEl.innerText = parts.length ? parts.join(' · ') : 'CPU stats unavailable';
}

function formatRamCard(ram) {
    const valueEl = document.getElementById('ram-usage-value');
    const labelEl = document.getElementById('ram-sub-label');
    const cardEl = document.getElementById('ram-card');

    if (ram && ram.used_gb !== null && ram.used_gb !== undefined) {
        valueEl.innerHTML = `${ram.used_gb}<span style="font-size: 0.9rem; color: var(--text-muted); margin-left: 2px;">GB</span>`;
        labelEl.innerText = (ram.total_gb !== null && ram.total_gb !== undefined)
            ? `of ${ram.total_gb} GB Total`
            : 'Total capacity unavailable';
    } else {
        valueEl.innerText = '—';
        cardEl.classList.add('hw-card-unavailable');
        labelEl.innerText = 'RAM stats unavailable';
    }
}

function formatGpuCard(gpu) {
    const valueEl = document.getElementById('gpu-usage-value');
    const labelEl = document.getElementById('gpu-sub-label');
    const cardEl = document.getElementById('gpu-card');

    if (!gpu) {
        valueEl.innerText = '—';
        labelEl.innerText = 'GPU stats unavailable';
        cardEl.classList.add('hw-card-unavailable');
        return;
    }

    const vramSuffix = (gpu.vram_gb !== null && gpu.vram_gb !== undefined) ? ` · ${gpu.vram_gb} GB` : '';

    if (gpu.usage_percent !== null && gpu.usage_percent !== undefined) {
        valueEl.innerHTML = `${Math.round(gpu.usage_percent)}<span style="font-size: 0.9rem; color: var(--text-muted); margin-left: 2px;">%</span>`;
        labelEl.innerText = (gpu.model || 'GPU') + vramSuffix;
    } else {
        valueEl.innerText = '—';
        cardEl.classList.add('hw-card-unavailable');
        labelEl.innerText = gpu.model ? `${gpu.model} · utilization unavailable${vramSuffix}` : 'Utilization unavailable';
    }
}

function formatStorageCard(storage) {
    const valueEl = document.getElementById('storage-value');
    const labelEl = document.getElementById('storage-sub-label');
    const cardEl = document.getElementById('storage-card');

    if (storage && storage.free_gb !== null && storage.free_gb !== undefined) {
        valueEl.innerHTML = `${storage.free_gb}<span style="font-size: 0.9rem; color: var(--text-muted); margin-left: 2px;">GB</span>`;
        labelEl.innerText = 'Available Free';
    } else {
        valueEl.innerText = '—';
        cardEl.classList.add('hw-card-unavailable');
        labelEl.innerText = 'Storage stats unavailable';
    }
}

async function loadHardwareProfile() {
    try {
        const res = await fetch(`${BACKEND_URL}/linux/hardware/profile`);
        if (!res.ok) throw new Error(`profile fetch failed: ${res.status}`);
        const profile = await res.json();

        formatOsBadge(profile.os);
        formatCpuCard(profile.cpu);
        formatRamCard(profile.ram);
        formatGpuCard(profile.gpu);
        formatStorageCard(profile.storage);
    } catch (e) {
        console.error('Could not load hardware profile, keeping static fallback:', e);
    }
}

const SEVERITY_STYLES = {
    good: {
        color: '#10b981', bg: 'rgba(16, 185, 129, 0.1)',
        icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>'
    },
    info: {
        color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)',
        icon: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>'
    },
    warn: {
        color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)',
        icon: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>'
    },
    unknown: {
        color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.1)',
        icon: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'
    }
};

function renderInsights(insightList) {
    const container = document.getElementById('system-insights-list');
    container.innerHTML = insightList.map(insight => {
        const style = SEVERITY_STYLES[insight.severity] || SEVERITY_STYLES.unknown;
        return `
            <div style="background-color: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: clamp(0.75rem, 2vh, 1rem); display: flex; gap: 0.75rem; align-items: flex-start;">
                <div style="background-color: ${style.bg}; border-radius: 8px; padding: 0.4rem; display: flex; align-items: center; justify-content: center;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="${style.color}" stroke-width="2" style="width: 16px; height: 16px;">${style.icon}</svg>
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.2rem;">
                    <span style="font-family: 'Clash Display', sans-serif; font-size: 0.9rem; font-weight: 500; color: var(--text-main);">${insight.title}</span>
                    <span style="font-family: 'Inter', sans-serif; font-size: 0.8rem; color: var(--text-muted); line-height: 1.4;">${insight.detail}</span>
                </div>
            </div>
        `;
    }).join('');
}

async function loadInsights() {
    try {
        const res = await fetch(`${BACKEND_URL}/linux/hardware/profile/insights`);
        if (!res.ok) throw new Error(`insights fetch failed: ${res.status}`);
        const data = await res.json();
        renderInsights(data.insights);
    } catch (e) {
        console.error('Could not load system insights, keeping static fallback:', e);
    }
}

loadHardwareProfile();
loadInsights();

// ---- Local models (Ollama): environment check, hardware-matched recommendations, download ----

const FIT_LABELS = {
    recommended: { label: 'Recommended', color: '#10b981' },
    possible: { label: 'Possible', color: 'var(--text-muted)' },
    too_large: { label: 'Too large', color: '#f59e0b' },
    no_disk_space: { label: 'Not enough disk space', color: '#f59e0b' },
    unknown: { label: 'Unknown fit', color: '#94a3b8' },
};

function formatSize(gb) {
    return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(gb * 1024)} MB`;
}

function renderLocalModels(recommendations) {
    const container = document.getElementById('local-models-list');

    if (!recommendations.length) {
        container.innerHTML = '<p style="font-family: \'Inter\', sans-serif; font-size: 0.85rem; color: var(--text-muted);">No models available.</p>';
        return;
    }

    container.innerHTML = recommendations.map(model => {
        const fit = FIT_LABELS[model.fit] || FIT_LABELS.unknown;
        const disabled = model.installed || model.fit === 'too_large' || model.fit === 'no_disk_space' || model.fit === 'unknown';
        const muted = model.fit === 'too_large' || model.fit === 'no_disk_space' || model.fit === 'unknown';
        const buttonLabel = model.installed ? 'Installed' : 'Download';
        const detail = `${model.params_b}B · ${model.quantization} · ${formatSize(model.size_gb)}`;

        return `
            <div class="model-item" style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; border: 1px solid var(--border); border-radius: 12px; background: transparent; transition: border-color 0.2s ease; ${muted ? 'opacity: 0.55;' : ''}">
                <div style="display: flex; flex-direction: column; gap: 0.15rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-family: 'Clash Display', sans-serif; font-size: 1.05rem; font-weight: 500; color: var(--text-main);">${model.display_name}</span>
                        <span style="font-family: 'Inter', sans-serif; font-size: 0.7rem; color: ${fit.color}; text-transform: uppercase; letter-spacing: 0.05em;">${fit.label}</span>
                    </div>
                    <span style="font-family: 'Clash Display', sans-serif; font-size: 0.85rem; color: var(--text-muted);">${model.reason || detail}</span>
                </div>
                <button
                    class="local-download-btn"
                    data-model-key="${model.model_key}"
                    data-display-name="${model.display_name}"
                    ${disabled ? 'disabled' : ''}
                    style="background: transparent; border: 1px solid var(--border); padding: 0.4rem 0.8rem; border-radius: 9999px; font-family: 'Clash Display', sans-serif; font-size: 0.85rem; cursor: ${disabled ? 'default' : 'pointer'}; color: var(--text-main); transition: background-color 0.2s ease; opacity: ${disabled ? '0.6' : '1'};"
                    ${disabled ? '' : `onmouseover="this.style.backgroundColor='var(--bg-color)'" onmouseout="this.style.backgroundColor='transparent'"`}
                >${buttonLabel}</button>
            </div>
        `;
    }).join('');
}

function showEnvBanner(detail) {
    const banner = document.getElementById('local-env-banner');
    document.getElementById('local-env-detail').innerText = detail;
    banner.style.display = 'flex';
}

function hideEnvBanner() {
    document.getElementById('local-env-banner').style.display = 'none';
}

async function loadLocalModels() {
    try {
        const res = await fetch(`${BACKEND_URL}/linux/local-models/recommendations`);
        if (!res.ok) throw new Error(`recommendations fetch failed: ${res.status}`);
        const data = await res.json();

        if (!data.environment.running) {
            showEnvBanner(data.environment.detail);
        } else {
            hideEnvBanner();
        }

        renderLocalModels(data.recommendations);
    } catch (e) {
        console.error('Could not load local model recommendations:', e);
        document.getElementById('local-models-list').innerHTML =
            '<p style="font-family: \'Inter\', sans-serif; font-size: 0.85rem; color: var(--text-muted);">Could not reach the backend to load local models.</p>';
    }
}

document.getElementById('local-env-recheck-btn').addEventListener('click', loadLocalModels);

document.getElementById('local-models-list').addEventListener('click', async (e) => {
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
        errorEl.innerText = detail;
    } else {
        errorEl.innerText = detail;
    }
    errorEl.style.display = 'block';
    btn.disabled = false;
    btn.innerText = 'Download';
});

loadLocalModels();

// ---- Cloud provider API key: verify, store, then fade to home ----

document.getElementById('save-api-key-btn').addEventListener('click', async () => {
    const provider = document.getElementById('cloud-provider-dropdown').dataset.selectedValue;
    const apiKeyInput = document.getElementById('cloud-api-key-input');
    const apiKey = apiKeyInput.value.trim();
    const btn = document.getElementById('save-api-key-btn');
    const errorEl = document.getElementById('cloud-api-key-error');
    const successEl = document.getElementById('setup-complete-message');

    errorEl.style.display = 'none';

    if (!provider) {
        errorEl.innerText = 'Please select a provider first.';
        errorEl.style.display = 'block';
        return;
    }
    if (!apiKey) {
        errorEl.innerText = 'Please enter an API key.';
        errorEl.style.display = 'block';
        return;
    }

    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = 'Verifying…';

    let res;
    try {
        res = await fetch(`${BACKEND_URL}/linux/byok/key`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: provider, api_key: apiKey })
        });
    } catch (e) {
        errorEl.innerText = `Couldn't reach ${provider} — check your connection.`;
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerText = originalText;
        return;
    }

    if (res.status === 401) {
        errorEl.innerText = `That key was rejected by ${provider}.`;
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerText = originalText;
        return;
    }
    if (res.status === 503) {
        errorEl.innerText = `Couldn't reach ${provider} — check your connection.`;
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerText = originalText;
        return;
    }
    if (!res.ok) {
        errorEl.innerText = 'Something went wrong. Please try again.';
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerText = originalText;
        return;
    }

    // Success: show the info message, then fade the page and go home.
    btn.innerText = 'Verified';
    successEl.style.display = 'block';

    setTimeout(() => {
        document.body.style.transition = 'opacity 0.8s ease';
        document.body.style.opacity = '0';
        setTimeout(() => {
            window.location.href = '/';
        }, 800);
    }, 1200);
});
