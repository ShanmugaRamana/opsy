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
