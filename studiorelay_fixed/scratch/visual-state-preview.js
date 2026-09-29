(function () {
    'use strict';

    const iframe = document.getElementById('preview');
    const previewParams = new URLSearchParams(window.location.search);
    const requestedState = previewParams.get('state') || 'prompts';
    const mapping = {
        studio: ['tab-generator', 'view-generator'],
        prompts: ['tab-prompts', 'view-prompts'],
        accounts: ['tab-accounts', 'view-accounts'],
        settings: ['tab-settings', 'view-settings'],
        activity: ['tab-logs', 'view-logs']
    };

    iframe.addEventListener('load', () => {
        const doc = iframe.contentDocument;
        if (!doc) return;

        const lock = doc.getElementById('view-license-lock');
        const main = doc.getElementById('main-unlocked-ui');
        if (requestedState === 'license') {
            if (lock) lock.style.display = 'flex';
            if (main) main.style.display = 'none';
            return;
        }

        if (lock) lock.style.display = 'none';
        if (main) main.style.display = 'flex';
        doc.querySelectorAll('.nav-btn').forEach((button) => button.classList.remove('active'));
        doc.querySelectorAll('[role="tabpanel"]').forEach((panel) => panel.classList.add('hidden'));

        const state = mapping[requestedState] || mapping.prompts;
        doc.getElementById(state[0])?.classList.add('active');
        doc.getElementById(state[1])?.classList.remove('hidden');

        if (previewParams.get('dialog') === '1') {
            const dialog = doc.getElementById('confirm-dialog');
            doc.getElementById('confirm-dialog-title').textContent = 'Clear all prompts?';
            doc.getElementById('confirm-dialog-description').textContent = 'Every saved prompt and its progress state will be removed.';
            doc.getElementById('confirm-dialog-accept').textContent = 'Clear prompts';
            dialog?.showModal();
        }
    });
})();
