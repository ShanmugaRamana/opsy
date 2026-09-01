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
