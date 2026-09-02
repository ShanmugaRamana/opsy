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
