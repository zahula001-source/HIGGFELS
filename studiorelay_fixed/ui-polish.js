(function () {
    'use strict';

    const confirmationCopy = {
        'btn-clear-session': {
            title: 'Reset current session?',
            description: 'This clears the active session and refreshes its account state.',
            confirmLabel: 'Reset session'
        },
        'btn-clear-prompts': {
            title: 'Clear all prompts?',
            description: 'Every saved prompt and its progress state will be removed.',
            confirmLabel: 'Clear prompts'
        },
        'btn-clear-all-accounts': {
            title: 'Clear all accounts?',
            description: 'Every saved account profile will be removed from this extension.',
            confirmLabel: 'Clear accounts'
        },
        'btn-reset-progress': {
            title: 'Reset prompt progress?',
            description: 'All completed prompts will return to the queued state.',
            confirmLabel: 'Reset progress'
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        disableStudioFeature();
        syncTabAccessibility();
        installTabStateObserver();
        installLicenseStateObserver();
        installRuntimeCopyPolish();
        installConfirmationDialog();
    });

    function disableStudioFeature() {
        const studioTab = document.getElementById('tab-generator');
        const studioView = document.getElementById('view-generator');
        const promptsTab = document.getElementById('tab-prompts');
        if (!studioTab || !studioView || !promptsTab) return;

        studioTab.hidden = true;
        studioTab.tabIndex = -1;
        studioTab.setAttribute('aria-hidden', 'true');
        studioTab.setAttribute('aria-selected', 'false');
        studioView.hidden = true;
        studioView.classList.add('hidden');
        studioView.setAttribute('aria-hidden', 'true');

        const redirectFromStudio = () => {
            const hasVisibleActiveTab = document.querySelector('.nav-btn.active:not([hidden])');
            if (studioTab.classList.contains('active') || !hasVisibleActiveTab) promptsTab.click();
        };

        redirectFromStudio();
        const observer = new MutationObserver(redirectFromStudio);
        observer.observe(studioTab, { attributes: true, attributeFilter: ['class'] });
        observer.observe(studioView, { attributes: true, attributeFilter: ['class', 'style'] });
    }

    function syncTabAccessibility() {
        document.querySelectorAll('.nav-btn').forEach((button) => {
            if (button.hidden) {
                button.setAttribute('aria-selected', 'false');
                button.tabIndex = -1;
                const hiddenPanelId = button.getAttribute('aria-controls');
                const hiddenPanel = hiddenPanelId ? document.getElementById(hiddenPanelId) : null;
                if (hiddenPanel) hiddenPanel.setAttribute('aria-hidden', 'true');
                return;
            }
            const isActive = button.classList.contains('active');
            button.setAttribute('aria-selected', String(isActive));
            button.tabIndex = isActive ? 0 : -1;

            const panelId = button.getAttribute('aria-controls');
            const panel = panelId ? document.getElementById(panelId) : null;
            if (panel) panel.setAttribute('aria-hidden', String(!isActive));
        });
    }

    function installTabStateObserver() {
        const tabs = document.querySelector('.nav-tabs');
        if (!tabs) return;

        tabs.addEventListener('keydown', (event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            const buttons = Array.from(tabs.querySelectorAll('.nav-btn:not([hidden])'));
            const currentIndex = buttons.indexOf(document.activeElement);
            if (currentIndex < 0) return;

            event.preventDefault();
            let nextIndex = currentIndex;
            if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % buttons.length;
            if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
            if (event.key === 'Home') nextIndex = 0;
            if (event.key === 'End') nextIndex = buttons.length - 1;
            buttons[nextIndex].focus();
            buttons[nextIndex].click();
        });

        new MutationObserver(syncTabAccessibility).observe(tabs, {
            attributes: true,
            attributeFilter: ['class'],
            subtree: true
        });
    }

    function installLicenseStateObserver() {
        const lock = document.getElementById('view-license-lock');
        const main = document.getElementById('main-unlocked-ui');
        if (!lock || !main) return;

        const sync = () => {
            const isLocked = lock.style.display !== 'none' && main.style.display === 'none';
            document.body.classList.toggle('license-locked', isLocked);
        };
        const observer = new MutationObserver(sync);
        observer.observe(lock, { attributes: true, attributeFilter: ['style'] });
        observer.observe(main, { attributes: true, attributeFilter: ['style'] });
        sync();
    }

    function installRuntimeCopyPolish() {
        const accountBadge = document.getElementById('header-active-account');
        const copyButton = document.getElementById('btn-copy-machine-id');
        const fetchButton = document.getElementById('btn-fetch');
        const licenseInfo = document.getElementById('settings-license-info');
        const activationStatus = document.getElementById('activation-error');
        const prompts = document.getElementById('prompts-container');
        const profiles = document.getElementById('profiles-container');

        const polishAccount = () => {
            if (!accountBadge) return;
            const cleaned = accountBadge.textContent
                .replace(/^\s*(?:🟢|ðŸŸ¢)\s*/u, '')
                .trim();
            if (cleaned && cleaned !== accountBadge.textContent.trim()) accountBadge.textContent = cleaned;
        };

        const polishCopyButton = () => {
            if (!copyButton) return;
            const current = copyButton.textContent.trim();
            let next = current;
            if (/copied/i.test(current)) next = 'Device ID copied';
            else if (/copy machine id|copy device id/i.test(current)) next = 'Copy device ID';
            if (next !== current) copyButton.textContent = next;
        };

        const polishFetchButton = () => {
            if (!fetchButton) return;
            const label = fetchButton.querySelector('span');
            if (!label || label.querySelector('strong')) return;
            const current = label.textContent.trim();
            if (/fetching|downloading/i.test(current)) {
                label.className = 'button-copy';
                label.innerHTML = '<strong>Downloading…</strong><small>Reading the active video stream</small>';
            } else if (/fast download video|download video/i.test(current)) {
                label.className = 'button-copy';
                label.innerHTML = '<strong>Download video</strong><small>Save the active video in its source quality</small>';
            }
        };

        const polishLicenseInfo = () => {
            if (!licenseInfo) return;
            const current = licenseInfo.textContent.trim();
            if (!current) return;
            if (/lifetime/i.test(current) && /activated|active|vip/i.test(current)) {
                licenseInfo.textContent = 'Lifetime license · Active';
            } else if (/activated/i.test(current) && current !== 'This device is activated.') {
                licenseInfo.textContent = 'This device is activated.';
            }
        };

        const polishActivationStatus = () => {
            if (!activationStatus) return;
            const current = activationStatus.textContent.trim();
            let next = current;
            let success = false;
            if (/please enter a vip license key/i.test(current)) next = 'Enter your license key.';
            if (/license activated successfully/i.test(current)) {
                next = 'License activated. Opening StudioRelay…';
                success = true;
            }
            if (/invalid vip key/i.test(current)) next = 'This key is not valid for this device.';
            if (next !== current) activationStatus.textContent = next;
            activationStatus.classList.toggle('success', success || /activated|opening/i.test(next));
            activationStatus.style.removeProperty('color');
        };

        const polishDynamicCards = (root) => {
            if (!root) return;
            const setButtonText = (button, text) => {
                if (button.textContent !== text) button.textContent = text;
            };
            root.querySelectorAll('.btn-prompt-paste').forEach((button) => {
                setButtonText(button, 'Paste');
                button.setAttribute('aria-label', 'Paste prompt');
            });
            root.querySelectorAll('.btn-mini-tab').forEach((button) => {
                setButtonText(button, 'Open');
                button.setAttribute('aria-label', 'Open account');
            });
            root.querySelectorAll('.btn-mini-newtab').forEach((button) => {
                setButtonText(button, 'New tab');
                button.setAttribute('aria-label', 'Open account in a new tab');
            });
            root.querySelectorAll('.btn-mini-switch').forEach((button) => {
                setButtonText(button, 'Switch');
                button.setAttribute('aria-label', 'Switch to account');
            });
            root.querySelectorAll('.btn-prompt-del').forEach((button) => {
                setButtonText(button, '×');
                button.setAttribute('aria-label', 'Delete');
                button.setAttribute('title', 'Delete');
            });
            root.querySelectorAll('.btn-toggle-done').forEach((button) => {
                const isDone = Boolean(button.closest('.prompt-done'));
                setButtonText(button, isDone ? '✓' : '○');
                button.setAttribute('aria-label', isDone ? 'Mark as queued' : 'Mark as done');
            });
        };

        const observe = (element, callback, options) => {
            if (!element) return;
            callback();
            new MutationObserver(callback).observe(element, options || {
                childList: true,
                characterData: true,
                subtree: true
            });
        };

        observe(accountBadge, polishAccount);
        observe(copyButton, polishCopyButton);
        observe(fetchButton, polishFetchButton);
        observe(licenseInfo, polishLicenseInfo);
        observe(activationStatus, polishActivationStatus);
        observe(prompts, () => polishDynamicCards(prompts));
        observe(profiles, () => polishDynamicCards(profiles));
    }

    function installConfirmationDialog() {
        const dialog = document.getElementById('confirm-dialog');
        const title = document.getElementById('confirm-dialog-title');
        const description = document.getElementById('confirm-dialog-description');
        const cancelButton = document.getElementById('confirm-dialog-cancel');
        const acceptButton = document.getElementById('confirm-dialog-accept');
        if (!dialog || typeof dialog.showModal !== 'function' || !title || !description || !cancelButton || !acceptButton) return;

        const nativeConfirm = window.confirm.bind(window);
        let pendingTarget = null;
        let confirmedTarget = null;
        let bypassNextNativeConfirm = false;

        window.confirm = (message) => {
            if (bypassNextNativeConfirm) {
                bypassNextNativeConfirm = false;
                return true;
            }
            return nativeConfirm(message);
        };

        document.addEventListener('click', (event) => {
            const button = event.target.closest('button');
            if (!button) return;
            if (button === confirmedTarget) {
                confirmedTarget = null;
                return;
            }

            const copy = confirmationCopy[button.id];
            if (!copy) return;

            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            pendingTarget = button;
            title.textContent = copy.title;
            description.textContent = copy.description;
            acceptButton.textContent = copy.confirmLabel;
            dialog.showModal();
            cancelButton.focus();
        }, true);

        const closeDialog = () => {
            pendingTarget = null;
            if (dialog.open) dialog.close();
        };

        cancelButton.addEventListener('click', closeDialog);
        dialog.addEventListener('cancel', (event) => {
            event.preventDefault();
            closeDialog();
        });
        dialog.addEventListener('click', (event) => {
            if (event.target === dialog) closeDialog();
        });

        acceptButton.addEventListener('click', () => {
            const target = pendingTarget;
            if (!target) return closeDialog();

            pendingTarget = null;
            dialog.close();
            confirmedTarget = target;
            bypassNextNativeConfirm = true;
            target.click();
            window.setTimeout(() => {
                confirmedTarget = null;
                bypassNextNativeConfirm = false;
            }, 0);
        });
    }
})();
