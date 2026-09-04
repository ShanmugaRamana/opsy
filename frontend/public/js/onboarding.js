document.addEventListener('DOMContentLoaded', () => {
    const splash = document.getElementById('onboarding-splash');
    const form = document.getElementById('onboarding-form');

    // Wait 2 seconds, fade out splash
    setTimeout(() => {
        splash.style.transition = 'opacity 0.8s ease';
        splash.style.opacity = '0';
        
        // After fade out completes (800ms)
        setTimeout(() => {
            splash.style.display = 'none';
            form.style.display = 'flex';
            
            // Trigger reflow
            void form.offsetWidth;
            
            form.style.transition = 'opacity 0.8s ease';
            form.style.opacity = '1';
        }, 800);
    }, 1500);
});

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

let selectedProfileSrc = null;
let selectedProfilePic = null;
const profileOptions = document.querySelectorAll('.profile-picker .profile-option');

profileOptions.forEach(option => {
    option.addEventListener('click', (e) => {
        // Remove selected from all
        profileOptions.forEach(opt => opt.classList.remove('selected'));
        // Add selected to clicked
        option.classList.add('selected');
        // Save selected profile src (for preview) and its relative path (for storage)
        selectedProfileSrc = e.target.src;
        selectedProfilePic = `assets/profile/${option.dataset.profile}`;
    });
});

document.getElementById('next-step-btn').addEventListener('click', () => {
    const errorText = document.getElementById('step-1-error');
    if (!selectedProfileSrc) {
        errorText.innerText = 'Please select a profile picture.';
        errorText.style.display = 'block';
        return;
    }
    
    errorText.style.display = 'none';
    
    // Transition to step 2
    document.getElementById('step-1').style.display = 'none';
    document.getElementById('selected-profile-display').src = selectedProfileSrc;
    document.getElementById('step-2').style.display = 'flex';
    document.getElementById('user-name').focus();
});

document.getElementById('back-to-step-1-btn').addEventListener('click', () => {
    document.getElementById('step-2').style.display = 'none';
    document.getElementById('step-1').style.display = 'flex';
});

const BACKEND_URL = 'http://localhost:8008';
const errorText = document.getElementById('onboarding-error');

document.getElementById('next-step-2-btn').addEventListener('click', () => {
    const name = document.getElementById('user-name').value.trim();
    const errorText = document.getElementById('step-2-error');

    if (!name) {
        errorText.innerText = 'Please enter a nickname before continuing.';
        errorText.style.display = 'block';
        return;
    }

    errorText.style.display = 'none';

    // Transition to step 3
    document.getElementById('step-2').style.display = 'none';
    document.getElementById('step-3').style.display = 'flex';
});

document.getElementById('back-to-step-2-btn').addEventListener('click', () => {
    document.getElementById('step-3').style.display = 'none';
    document.getElementById('step-2').style.display = 'flex';
    document.getElementById('user-name').focus();
});

document.querySelectorAll('.chip-group').forEach(group => {
    const chips = group.querySelectorAll('.chip');
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            chips.forEach(c => c.classList.remove('selected'));
            chip.classList.add('selected');
        });
    });
});

document.getElementById('final-continue-btn').addEventListener('click', async () => {
    const name = document.getElementById('user-name').value.trim();
    const selectedLinuxExp = document.querySelector('#linux-exp-group .chip.selected');
    const selectedRole = document.querySelector('#role-use-case-group .chip.selected');
    const errorText = document.getElementById('onboarding-error');

    if (!selectedLinuxExp || !selectedRole) {
        errorText.innerText = 'Please select an option for both before completing.';
        errorText.style.display = 'block';
        return;
    }

    const linuxExperience = selectedLinuxExp.dataset.value;
    const roleUseCase = selectedRole.dataset.value;

    errorText.style.display = 'none';

    try {
        const res = await fetch(`${BACKEND_URL}/linux/onboarding/user`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                profile_pic: selectedProfilePic,
                linux_experience: linuxExperience,
                role_use_case: roleUseCase
            })
        });

        if (!res.ok) {
            throw new Error(`Request failed with status ${res.status}`);
        }

        window.location.href = '/setup';
    } catch (e) {
        errorText.innerText = 'Could not save your details. Please try again.';
        errorText.style.display = 'block';
    }
});
