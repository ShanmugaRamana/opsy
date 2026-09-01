document.querySelectorAll('.custom-dropdown').forEach(dropdown => {
    const trigger = dropdown.querySelector('.custom-dropdown-trigger');
    const options = dropdown.querySelectorAll('.custom-option');
    const selectedText = dropdown.querySelector('.selected-text');

    trigger.addEventListener('click', (e) => {
        document.querySelectorAll('.custom-dropdown').forEach(d => {
            if (d !== dropdown) d.classList.remove('open');
        });
        dropdown.classList.toggle('open');
        e.stopPropagation();
    });

    options.forEach(option => {
        option.addEventListener('click', () => {
            selectedText.textContent = option.textContent;
            dropdown.dataset.selectedValue = option.dataset.value;
            dropdown.classList.remove('open');
        });
    });
});

document.addEventListener('click', () => {
    document.querySelectorAll('.custom-dropdown').forEach(d => d.classList.remove('open'));
});

const BACKEND_URL = 'http://localhost:8000';
const errorText = document.getElementById('onboarding-error');

document.getElementById('continue-btn').addEventListener('click', async () => {
    const name = document.getElementById('user-name').value.trim();
    const linuxExperience = document.getElementById('linux-exp-dropdown').dataset.selectedValue;
    const roleUseCase = document.getElementById('role-use-case-dropdown').dataset.selectedValue;

    if (!name || !linuxExperience || !roleUseCase) {
        errorText.innerText = 'Please fill in your name and both selections before continuing.';
        errorText.style.display = 'block';
        return;
    }

    errorText.style.display = 'none';

    try {
        const res = await fetch(`${BACKEND_URL}/linux/onboarding/user`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                linux_experience: linuxExperience,
                role_use_case: roleUseCase
            })
        });

        if (!res.ok) {
            throw new Error(`Request failed with status ${res.status}`);
        }

        window.location.href = '/';
    } catch (e) {
        errorText.innerText = 'Could not save your details. Please try again.';
        errorText.style.display = 'block';
    }
});
