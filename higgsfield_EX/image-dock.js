(() => {
    'use strict';

    const INSTALL_FLAG = '__studioRelayImageDockInstalled';
    const ROOT_ID = 'studio-relay-page-overlays';
    const SUMMARY_STORAGE_KEY = 'studio_relay_image_overlay_summary';
    const GET_SUMMARY_ACTION = 'studioRelayGetImageQueueSummary';
    const UPLOAD_ACTION = 'studioRelayUploadImageFromOverlay';

    if (globalThis[INSTALL_FLAG]) return;
    globalThis[INSTALL_FLAG] = true;

    const state = {
        images: [],
        total: 0,
        queued: 0,
        done: 0,
        query: '',
        expanded: false,
        busy: false,
        contextInvalid: false,
        healthTimer: null
    };

    const refs = {};
    let retryTimer = null;

    function initialize() {
        const root = document.getElementById(ROOT_ID);
        const oldToggle = document.getElementById('studio-relay-images-overlay-toggle');
        const card = oldToggle?.closest('.studio-relay-page-overlay-card');

        if (!root || !oldToggle || !card) {
            retryTimer = window.setTimeout(initialize, 100);
            return;
        }

        if (document.getElementById('studio-relay-image-dock-list')) return;

        const oldPanel = document.getElementById('studio-relay-images-overlay-panel');
        const toggle = createToggle();
        const panel = createDockPanel();

        oldToggle.replaceWith(toggle);
        oldPanel?.remove();
        card.append(panel);

        Object.assign(refs, {
            root,
            card,
            toggle,
            label: toggle.querySelector('.studio-relay-page-overlay-label'),
            arrow: toggle.querySelector('.studio-relay-page-overlay-arrow'),
            panel,
            doneBadge: panel.querySelector('#studio-relay-image-dock-done'),
            search: panel.querySelector('#studio-relay-image-dock-search'),
            refresh: panel.querySelector('#studio-relay-image-dock-refresh'),
            uploadAll: panel.querySelector('#studio-relay-image-dock-upload-all'),
            list: panel.querySelector('#studio-relay-image-dock-list'),
            status: panel.querySelector('#studio-relay-image-dock-status')
        });

        installInteractions();
        render();
        loadStoredSummary();
        refreshFromBackground(true);
    }

    function createToggle() {
        const toggle = document.createElement('button');
        toggle.id = 'studio-relay-images-overlay-toggle';
        toggle.className = 'studio-relay-page-overlay-pill';
        toggle.type = 'button';
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', 'studio-relay-images-overlay-panel');

        const label = document.createElement('span');
        label.className = 'studio-relay-page-overlay-label';
        label.textContent = '🖼️ Images (0/0)';

        const arrow = document.createElement('span');
        arrow.className = 'studio-relay-page-overlay-arrow';
        arrow.setAttribute('aria-hidden', 'true');
        arrow.textContent = '◀';

        toggle.append(label, arrow);
        return toggle;
    }

    function createDockPanel() {
        const panel = document.createElement('section');
        panel.id = 'studio-relay-images-overlay-panel';
        panel.className = 'studio-relay-page-overlay-panel studio-relay-image-dock';
        panel.hidden = true;
        panel.setAttribute('aria-label', 'Image Dock');

        const header = document.createElement('header');
        header.className = 'studio-relay-image-dock-header';

        const title = document.createElement('strong');
        title.textContent = '⚡ Image Dock';

        const doneBadge = document.createElement('span');
        doneBadge.id = 'studio-relay-image-dock-done';
        doneBadge.className = 'studio-relay-image-dock-done';
        doneBadge.textContent = '✅ 0 Done';
        header.append(title, doneBadge);

        const divider = document.createElement('div');
        divider.className = 'studio-relay-image-dock-divider';

        const search = document.createElement('input');
        search.id = 'studio-relay-image-dock-search';
        search.type = 'search';
        search.placeholder = '🔍 Search images...';
        search.autocomplete = 'off';

        const actions = document.createElement('div');
        actions.className = 'studio-relay-image-dock-actions';

        const refresh = document.createElement('button');
        refresh.id = 'studio-relay-image-dock-refresh';
        refresh.type = 'button';
        refresh.textContent = '↻ Refresh';

        const uploadAll = document.createElement('button');
        uploadAll.id = 'studio-relay-image-dock-upload-all';
        uploadAll.className = 'studio-relay-image-dock-primary';
        uploadAll.type = 'button';
        uploadAll.textContent = '⚡ Upload All Tabs';
        actions.append(refresh, uploadAll);

        const list = document.createElement('div');
        list.id = 'studio-relay-image-dock-list';
        list.className = 'studio-relay-image-dock-list';
        list.setAttribute('role', 'list');

        const status = document.createElement('p');
        status.id = 'studio-relay-image-dock-status';
        status.className = 'studio-relay-image-dock-status';
        status.setAttribute('aria-live', 'polite');

        panel.append(header, divider, search, actions, list, status);
        return panel;
    }

    function installInteractions() {
        refs.toggle.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            state.expanded = !state.expanded;
            refs.panel.hidden = !state.expanded;
            refs.toggle.setAttribute('aria-expanded', String(state.expanded));
            refs.arrow.textContent = state.expanded ? '▼' : '◀';
            refs.root.classList.toggle('images-expanded', state.expanded);
            if (state.expanded) refreshFromBackground(true);
        });

        refs.panel.addEventListener('click', event => event.stopPropagation());

        refs.search.addEventListener('input', event => {
            state.query = String(event.target.value || '').trim().toLowerCase();
            renderRows();
        });

        refs.refresh.addEventListener('click', () => {
            if (state.contextInvalid || !hasLiveExtensionContext()) {
                window.location.reload();
                return;
            }
            refreshFromBackground(false);
        });
        refs.uploadAll.addEventListener('click', () => requestUpload('all'));

        refs.list.addEventListener('click', event => {
            const button = event.target.closest('[data-image-upload-id]');
            if (!button) return;
            requestUpload('current', button.dataset.imageUploadId);
        });

        try {
            if (ensureLiveExtensionContext()) {
                chrome.storage.onChanged.addListener((changes, areaName) => {
                    if (areaName !== 'local' || !changes[SUMMARY_STORAGE_KEY]) return;
                    applySummary(changes[SUMMARY_STORAGE_KEY].newValue);
                });
            }
        } catch (error) {
            normalizeRuntimeError(error);
        }

        state.healthTimer = window.setInterval(() => {
            if (!hasLiveExtensionContext()) enterInvalidContextState();
        }, 1500);

        window.addEventListener('unload', () => {
            if (retryTimer) window.clearTimeout(retryTimer);
            if (state.healthTimer) window.clearInterval(state.healthTimer);
        });
    }

    function loadStoredSummary() {
        if (!ensureLiveExtensionContext()) return;
        try {
            chrome.storage.local.get([SUMMARY_STORAGE_KEY], result => {
                try {
                    if (!ensureLiveExtensionContext() || chrome.runtime.lastError) return;
                    applySummary(result?.[SUMMARY_STORAGE_KEY]);
                } catch (error) {
                    normalizeRuntimeError(error);
                }
            });
        } catch (error) {
            normalizeRuntimeError(error);
        }
    }

    async function refreshFromBackground(quiet) {
        if (state.busy) return;
        if (!ensureLiveExtensionContext()) return;
        if (!quiet) setStatus('Refreshing image queue…', 'working');

        try {
            const response = await sendRuntimeMessage({action: GET_SUMMARY_ACTION});
            if (!response?.success) throw new Error(response?.error || 'Image queue could not be loaded.');
            applySummary(response.summary);
            if (!quiet) setStatus('Image queue refreshed.', 'success');
        } catch (error) {
            const normalized = normalizeRuntimeError(error);
            if (!quiet && !state.contextInvalid) setStatus(friendlyError(normalized), 'error');
        }
    }

    async function requestUpload(mode, imageId = '') {
        if (state.busy) return;
        if (!ensureLiveExtensionContext()) return;
        if (mode === 'all' && state.queued < 1) {
            setStatus('No queued images are available.', 'error');
            return;
        }

        const record = state.images.find(image => image.id === imageId);
        if (mode === 'current' && !record) {
            setStatus('That image is no longer in the queue.', 'error');
            return;
        }

        setBusy(true);
        setStatus(
            mode === 'all'
                ? 'Uploading queued images serially across open tabs…'
                : `Uploading ${record.name} to this tab…`,
            'working'
        );

        try {
            const response = await sendRuntimeMessage({
                action: UPLOAD_ACTION,
                mode,
                imageId
            });
            if (response?.summary) applySummary(response.summary);
            if (!response?.success) throw new Error(response?.error || 'Image upload failed.');
            setStatus(response.message || 'Image upload completed.', 'success');
        } catch (error) {
            const normalized = normalizeRuntimeError(error);
            if (!state.contextInvalid) setStatus(friendlyError(normalized), 'error');
        } finally {
            setBusy(false);
        }
    }

    function applySummary(value) {
        const summary = value && typeof value === 'object' ? value : {};
        const images = Array.isArray(summary.images)
            ? summary.images.map(normalizeImage).filter(Boolean).sort(sortByOrder)
            : [];

        state.images = images;
        state.total = safeCount(summary.total ?? images.length);
        state.done = safeCount(summary.done ?? images.filter(image => image.status === 'done').length);
        state.queued = safeCount(summary.queued ?? Math.max(0, state.total - state.done));
        render();
    }

    function normalizeImage(value) {
        if (!value || typeof value !== 'object' || !value.id) return null;
        return {
            id: String(value.id),
            name: String(value.name || 'Untitled image'),
            status: value.status === 'done' ? 'done' : 'queued',
            order: safeCount(value.order),
            size: safeCount(value.size),
            error: String(value.error || '')
        };
    }

    function render() {
        if (!refs.label) return;
        refs.label.textContent = `🖼️ Images (${state.done}/${state.total})`;
        refs.doneBadge.textContent = `✅ ${state.done} Done`;
        refs.uploadAll.disabled = state.contextInvalid || state.busy || state.queued < 1;
        refs.refresh.disabled = state.busy && !state.contextInvalid;
        refs.refresh.textContent = state.contextInvalid ? '↻ Reload Page' : '↻ Refresh';
        renderRows();
    }

    function renderRows() {
        if (!refs.list) return;
        refs.list.replaceChildren();

        const filtered = state.images.filter(image => !state.query || image.name.toLowerCase().includes(state.query));
        if (!filtered.length) {
            const empty = document.createElement('p');
            empty.className = 'studio-relay-image-dock-empty';
            empty.textContent = state.images.length ? 'No matching images.' : 'No images added yet. Add them from the Images tab.';
            refs.list.append(empty);
            return;
        }

        filtered.forEach((image, index) => {
            const row = document.createElement('article');
            row.className = `studio-relay-image-dock-row${image.status === 'done' ? ' is-done' : ''}`;
            row.setAttribute('role', 'listitem');

            const dot = document.createElement('span');
            dot.className = 'studio-relay-image-dock-dot';
            dot.setAttribute('aria-hidden', 'true');

            const number = document.createElement('span');
            number.className = 'studio-relay-image-dock-number';
            number.textContent = `#${String(index + 1).padStart(2, '0')}`;

            const info = document.createElement('span');
            info.className = 'studio-relay-image-dock-info';
            const name = document.createElement('strong');
            name.textContent = image.name;
            name.title = image.name;
            const meta = document.createElement('small');
            meta.textContent = image.error || `${formatBytes(image.size)} · ${image.status === 'done' ? 'Done' : 'Queued'}`;
            if (image.error) meta.title = image.error;
            info.append(name, meta);

            const upload = document.createElement('button');
            upload.type = 'button';
            upload.dataset.imageUploadId = image.id;
            upload.textContent = image.status === 'done' ? 'Re-upload' : 'Upload';
            upload.disabled = state.contextInvalid || state.busy;

            row.append(dot, number, info, upload);
            refs.list.append(row);
        });
    }

    function setBusy(value) {
        state.busy = Boolean(value);
        render();
    }

    function setStatus(message, type = '') {
        refs.status.textContent = message || '';
        if (type) refs.status.dataset.state = type;
        else delete refs.status.dataset.state;
    }

    function sendRuntimeMessage(message) {
        return new Promise((resolve, reject) => {
            if (!ensureLiveExtensionContext()) {
                reject(createInvalidContextError());
                return;
            }

            try {
                chrome.runtime.sendMessage(message, response => {
                    try {
                        if (!ensureLiveExtensionContext()) {
                            reject(createInvalidContextError());
                            return;
                        }
                        const error = chrome.runtime.lastError;
                        if (error) reject(normalizeRuntimeError(new Error(error.message)));
                        else resolve(response);
                    } catch (error) {
                        reject(normalizeRuntimeError(error));
                    }
                });
            } catch (error) {
                reject(normalizeRuntimeError(error));
            }
        });
    }

    function hasLiveExtensionContext() {
        try {
            return Boolean(globalThis.chrome?.runtime?.id);
        } catch {
            return false;
        }
    }

    function ensureLiveExtensionContext() {
        if (hasLiveExtensionContext()) return true;
        enterInvalidContextState();
        return false;
    }

    function normalizeRuntimeError(error) {
        const normalized = error instanceof Error ? error : new Error(String(error));
        if (/extension context invalidated/i.test(normalized.message) || !hasLiveExtensionContext()) {
            enterInvalidContextState();
            return createInvalidContextError();
        }
        return normalized;
    }

    function createInvalidContextError() {
        return new Error('StudioRelay was reloaded. Reload this Dola page once to reconnect the extension.');
    }

    function enterInvalidContextState() {
        if (state.contextInvalid) return;
        state.contextInvalid = true;
        state.busy = false;
        refs.root?.classList.add('studio-relay-context-invalid');
        render();
        refs.refresh.disabled = false;
        refs.refresh.title = 'Reload this Dola page to reconnect StudioRelay';
        setStatus('StudioRelay was reloaded. Click Reload Page once to reconnect this tab.', 'error');
    }

    function friendlyError(error) {
        const message = error?.message || String(error);
        if (/receiving end does not exist|could not establish connection/i.test(message)) {
            return 'Refresh the target Dola tab once, then retry.';
        }
        return message;
    }

    function formatBytes(bytes) {
        if (!bytes) return '0 KB';
        if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function safeCount(value) {
        const number = Number(value);
        return Number.isFinite(number) && number >= 0 ? Math.floor(number) : 0;
    }

    function sortByOrder(left, right) {
        return (left.order - right.order) || left.name.localeCompare(right.name);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, {once: true});
    } else {
        initialize();
    }
})();
