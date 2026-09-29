(() => {
    'use strict';

    const DB_NAME = 'studio-relay-image-queue';
    const DB_VERSION = 1;
    const STORE_NAME = 'images';
    const MAX_IMAGE_BYTES = 25 * 1024 * 1024;
    const MAX_QUEUE_LENGTH = 200;
    const SUPPORTED_MIME_TYPES = new Set([
        'image/avif',
        'image/gif',
        'image/jpeg',
        'image/png',
        'image/webp'
    ]);
    const SUPPORTED_HOSTS = ['dola.com', 'seaart.ai'];
    const UPLOAD_ACTION = 'studioRelayUploadImage';
    const MANUAL_DRAG_RECORD_TYPE = 'application/x-studio-relay-image-id';
    const OVERLAY_SUMMARY_STORAGE_KEY = 'studio_relay_image_overlay_summary';

    const state = {
        images: [],
        filter: 'all',
        selectedId: null,
        busy: false,
        cardUrls: new Set(),
        dialogUrl: null
    };

    const refs = {};
    let databasePromise;
    let lastOverlaySummarySignature = '';
    let queueReloadTimer = null;
    let suppressGalleryClickUntil = 0;

    function initialize() {
        Object.assign(refs, {
            tab: document.getElementById('tab-images'),
            view: document.getElementById('view-images'),
            input: document.getElementById('file-upload-images'),
            selectButton: document.getElementById('btn-trigger-upload-images'),
            clearButton: document.getElementById('btn-clear-images'),
            picker: document.getElementById('image-picker-dropzone'),
            queueButton: document.getElementById('btn-open-image-upload-options'),
            container: document.getElementById('images-container'),
            counter: document.getElementById('images-counter'),
            countAll: document.getElementById('image-count-all'),
            countQueued: document.getElementById('image-count-queued'),
            countDone: document.getElementById('image-count-done'),
            filterPills: document.getElementById('image-filter-pills'),
            status: document.getElementById('image-upload-status'),
            dialog: document.getElementById('image-upload-dialog'),
            dialogPreview: document.getElementById('image-upload-dialog-preview'),
            dialogName: document.getElementById('image-upload-dialog-name'),
            dialogDescription: document.getElementById('image-upload-dialog-description'),
            cancelDialog: document.getElementById('image-upload-dialog-cancel'),
            uploadActive: document.getElementById('image-upload-active-tab'),
            uploadAll: document.getElementById('image-upload-all-tabs')
        });

        if (!refs.tab || !refs.view || !refs.input || !refs.container || !refs.dialog) return;

        installNavigation();
        installFileSelection();
        installFilters();
        installDialog();
        installOverlayRefresh();

        refs.clearButton?.addEventListener('click', clearQueue);
        refs.queueButton?.addEventListener('click', openQueueDialog);

        loadQueue();
    }

    function installNavigation() {
        const mappings = {
            'tab-prompts': 'view-prompts',
            'tab-images': 'view-images',
            'tab-accounts': 'view-accounts',
            'tab-settings': 'view-settings',
            'tab-logs': 'view-logs'
        };

        const nav = document.querySelector('.nav-tabs');
        if (nav) nav.setAttribute('role', 'tablist');

        Object.entries(mappings).forEach(([tabId, viewId]) => {
            const button = document.getElementById(tabId);
            const panel = document.getElementById(viewId);
            if (!button || !panel) return;

            button.setAttribute('role', 'tab');
            button.setAttribute('aria-controls', viewId);
            panel.setAttribute('role', 'tabpanel');

            if (button === refs.tab) {
                button.addEventListener('click', activateImagesView);
            } else {
                button.addEventListener('click', () => {
                    refs.tab.classList.remove('active');
                    refs.tab.setAttribute('aria-selected', 'false');
                    refs.view.classList.add('hidden');
                    refs.view.setAttribute('aria-hidden', 'true');
                });
            }
        });
    }

    function activateImagesView(event) {
        event?.preventDefault();

        document.querySelectorAll('.nav-btn').forEach(button => {
            const isImageTab = button === refs.tab;
            button.classList.toggle('active', isImageTab);
            button.setAttribute('aria-selected', String(isImageTab));
            button.tabIndex = isImageTab ? 0 : -1;
        });

        document.querySelectorAll('.tab-content').forEach(panel => {
            const isImageView = panel === refs.view;
            panel.classList.toggle('hidden', !isImageView);
            panel.setAttribute('aria-hidden', String(!isImageView));
        });
    }

    function installFileSelection() {
        const openPicker = () => {
            if (!state.busy) refs.input.click();
        };

        refs.selectButton?.addEventListener('click', openPicker);
        refs.picker?.addEventListener('click', openPicker);
        refs.picker?.addEventListener('keydown', event => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            openPicker();
        });

        refs.input.addEventListener('change', async event => {
            const files = Array.from(event.target.files || []);
            event.target.value = '';
            await addFiles(files);
        });

        ['dragenter', 'dragover'].forEach(type => {
            refs.picker?.addEventListener(type, event => {
                event.preventDefault();
                if (!state.busy) refs.picker.classList.add('is-dragging');
            });
        });

        ['dragleave', 'drop'].forEach(type => {
            refs.picker?.addEventListener(type, event => {
                event.preventDefault();
                refs.picker.classList.remove('is-dragging');
            });
        });

        refs.picker?.addEventListener('drop', async event => {
            if (state.busy) return;
            await addFiles(Array.from(event.dataTransfer?.files || []));
        });
    }

    function installFilters() {
        refs.filterPills?.addEventListener('click', event => {
            const button = event.target.closest('[data-image-filter]');
            if (!button) return;
            state.filter = button.dataset.imageFilter || 'all';
            renderQueue();
        });
    }

    function installDialog() {
        refs.cancelDialog?.addEventListener('click', closeDialog);
        refs.uploadActive?.addEventListener('click', () => uploadImageToActiveTab(state.selectedId));
        refs.uploadAll?.addEventListener('click', uploadQueueSerially);
        refs.dialog.addEventListener('close', releaseDialogPreview);
        refs.dialog.addEventListener('click', event => {
            if (event.target === refs.dialog && !state.busy) closeDialog();
        });
    }

    function installOverlayRefresh() {
        if (!chrome?.storage?.onChanged) return;
        chrome.storage.onChanged.addListener((changes, areaName) => {
            if (areaName !== 'local' || !changes[OVERLAY_SUMMARY_STORAGE_KEY]) return;
            const summary = changes[OVERLAY_SUMMARY_STORAGE_KEY].newValue;
            if (summary?.source !== 'background' || state.busy) return;
            const manualDrop = summary.manualDrop;
            if (queueReloadTimer) window.clearTimeout(queueReloadTimer);
            queueReloadTimer = window.setTimeout(async () => {
                queueReloadTimer = null;
                await loadQueue();
                if (manualDrop?.status === 'done') {
                    setStatus(`${manualDrop.name || 'Image'} verified and attached on Dola.`, 'success');
                } else if (manualDrop?.status === 'error') {
                    setStatus(`${manualDrop.name || 'Image'} was not attached: ${manualDrop.error || 'Dola did not accept it.'}`, 'error');
                }
            }, 80);
        });
    }

    async function loadQueue() {
        try {
            const records = await getAllRecords();
            const legacyDone = records.filter(record => record.status === 'done' && !Number(record.attachmentVerifiedAt));
            legacyDone.forEach(record => {
                record.status = 'queued';
                record.error = 'Previous Done status was not attachment-verified. Retry the upload.';
                record.uploadedAt = null;
                record.attachmentVerifiedAt = null;
                record.attachmentEvidence = '';
            });
            if (legacyDone.length) await putRecords(legacyDone);
            state.images = records;
            sortImages();
            renderQueue();
        } catch (error) {
            setStatus(`Could not open the image queue: ${error.message}`, 'error');
        }
    }

    async function addFiles(files) {
        if (!files.length || state.busy) return;

        const availableSlots = Math.max(0, MAX_QUEUE_LENGTH - state.images.length);
        const candidates = files.slice(0, availableSlots);
        const accepted = [];
        const rejected = [];

        candidates.forEach(file => {
            if (!isImageFile(file)) {
                rejected.push(`${file.name}: not a supported image`);
                return;
            }
            if (file.size > MAX_IMAGE_BYTES) {
                rejected.push(`${file.name}: larger than 25 MB`);
                return;
            }
            accepted.push(file);
        });

        if (files.length > availableSlots) {
            rejected.push(`${files.length - availableSlots} image(s): queue limit is ${MAX_QUEUE_LENGTH}`);
        }

        if (!accepted.length) {
            setStatus(rejected[0] || 'No supported images were selected.', 'error');
            return;
        }

        setBusy(true);
        try {
            const highestOrder = state.images.reduce((max, record) => Math.max(max, record.order || 0), 0);
            const now = Date.now();
            const records = accepted.map((file, index) => ({
                id: createId(),
                name: file.name || `image-${now + index}`,
                type: file.type || guessMimeType(file.name),
                size: file.size,
                lastModified: file.lastModified || now,
                blob: file,
                status: 'queued',
                error: '',
                order: highestOrder + index + 1,
                addedAt: now + index,
                uploadedAt: null
            }));

            await putRecords(records);
            state.images.push(...records);
            sortImages();
            renderQueue();

            const rejectionCopy = rejected.length ? ` ${rejected.length} file(s) skipped.` : '';
            setStatus(`${records.length} image(s) added in selection order.${rejectionCopy}`, rejected.length ? 'working' : 'success');
        } catch (error) {
            setStatus(`Could not save selected images: ${error.message}`, 'error');
        } finally {
            setBusy(false);
        }
    }

    function renderQueue() {
        releaseCardPreviews();
        refs.container.replaceChildren();

        const queuedCount = state.images.filter(image => image.status !== 'done').length;
        const doneCount = state.images.length - queuedCount;
        refs.counter.textContent = String(state.images.length);
        refs.countAll.textContent = String(state.images.length);
        refs.countQueued.textContent = String(queuedCount);
        refs.countDone.textContent = String(doneCount);
        publishOverlaySummary(queuedCount, doneCount);

        refs.filterPills?.querySelectorAll('[data-image-filter]').forEach(button => {
            button.classList.toggle('active', button.dataset.imageFilter === state.filter);
        });

        const visible = state.images.filter(image => {
            if (state.filter === 'done') return image.status === 'done';
            if (state.filter === 'queued') return image.status !== 'done';
            return true;
        });

        if (!visible.length) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.id = 'images-empty-dropzone';
            empty.textContent = state.images.length
                ? `No ${state.filter} images in this queue.`
                : '📁 Select multiple images to build the upload queue.';
            empty.addEventListener('click', () => refs.input.click());
            refs.container.append(empty);
        } else {
            visible.forEach(record => refs.container.append(createImageCard(record)));
        }

        if (refs.queueButton) refs.queueButton.disabled = state.busy || queuedCount === 0;
    }

    function createImageCard(record) {
        const absoluteIndex = state.images.findIndex(image => image.id === record.id) + 1;
        const item = document.createElement('article');
        item.className = `image-queue-item${record.status === 'done' ? ' image-done' : ''}`;
        item.dataset.imageId = record.id;
        item.draggable = !state.busy;
        item.tabIndex = 0;
        item.setAttribute('role', 'group');
        item.setAttribute('aria-roledescription', 'draggable image');
        item.setAttribute('aria-grabbed', 'false');
        item.setAttribute('aria-label', `${record.name}. Drag onto Dola or press Enter to upload to the current tab.`);
        item.title = `Click to upload ${record.name} to the current tab, or drag it onto Dola`;

        const thumbWrap = document.createElement('div');
        thumbWrap.className = 'image-gallery-thumb-wrap';

        const preview = document.createElement('img');
        preview.className = 'image-gallery-thumb';
        preview.alt = record.name;
        preview.loading = 'lazy';
        preview.draggable = false;
        const previewUrl = URL.createObjectURL(record.blob);
        state.cardUrls.add(previewUrl);
        preview.src = previewUrl;

        const index = document.createElement('span');
        index.className = 'image-gallery-index';
        index.textContent = `#${absoluteIndex}`;

        const status = document.createElement('span');
        status.className = `image-gallery-status${record.status === 'done' ? ' is-done' : ''}${record.error ? ' has-error' : ''}`;
        status.title = record.error || (record.status === 'done' ? 'Verified Done' : 'Queued');
        status.setAttribute('aria-label', status.title);

        const name = document.createElement('div');
        name.className = 'image-gallery-name';
        name.title = record.name;
        name.textContent = record.name;

        const deleteButton = document.createElement('button');
        deleteButton.className = 'image-gallery-delete';
        deleteButton.type = 'button';
        deleteButton.title = `Remove ${record.name}`;
        deleteButton.setAttribute('aria-label', `Remove ${record.name}`);
        deleteButton.textContent = '×';
        deleteButton.disabled = state.busy;
        deleteButton.addEventListener('click', event => {
            event.stopPropagation();
            removeRecord(record.id);
        });

        thumbWrap.append(preview, index, status, name, deleteButton);
        item.append(thumbWrap);
        item.addEventListener('click', () => {
            if (Date.now() < suppressGalleryClickUntil) return;
            uploadImageToActiveTab(record.id);
        });
        item.addEventListener('keydown', event => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            uploadImageToActiveTab(record.id);
        });
        item.addEventListener('dragstart', event => beginGalleryDrag(event, record, item, preview));
        item.addEventListener('dragend', event => finishGalleryDrag(event, record, item));
        return item;
    }

    function beginGalleryDrag(event, record, item, preview) {
        const transfer = event.dataTransfer;
        if (!event.isTrusted || state.busy || !transfer || !(record.blob instanceof Blob)) {
            event.preventDefault();
            setStatus('This image is not ready to drag. Try selecting it again.', 'error');
            return;
        }

        const recordId = String(record.id);
        const operationId = createId();
        const dragPayload = JSON.stringify({v: 3, recordId, operationId});
        transfer.effectAllowed = 'copy';

        // The physical drag is a trigger only. No File, filename, URL, or image
        // bytes cross into Dola, so the page cannot paste the filename as text.
        try { transfer.clearData(); } catch {}
        try {
            for (let index = (transfer.items?.length || 0) - 1; index >= 0; index -= 1) {
                transfer.items.remove(index);
            }
        } catch {}
        try { transfer.setData(MANUAL_DRAG_RECORD_TYPE, dragPayload); } catch {}

        const items = Array.from(transfer.items || []);
        const types = new Set(Array.from(transfer.types || []).map(type => String(type).toLowerCase()));
        const fileItems = items.filter(entry => entry.kind === 'file');
        const textItems = items.filter(entry => entry.kind === 'string');
        if (!types.has(MANUAL_DRAG_RECORD_TYPE) || fileItems.length !== 0 || textItems.length !== 1) {
            event.preventDefault();
            try { transfer.clearData(); } catch {}
            setStatus('Chrome could not prepare the private StudioRelay image trigger.', 'error');
            return;
        }

        try {
            if (preview.complete && preview.naturalWidth) {
                transfer.setDragImage(preview, Math.round(preview.clientWidth / 2), Math.round(preview.clientHeight / 2));
            }
        } catch {}

        item.classList.add('is-dragging');
        item.setAttribute('aria-grabbed', 'true');
        setStatus('Dragging ' + record.name + ' — drop anywhere on the Dola page.', 'working');
    }
    function finishGalleryDrag(event, record, item) {
        suppressGalleryClickUntil = Date.now() + 300;
        item.classList.remove('is-dragging');
        item.setAttribute('aria-grabbed', 'false');

        if (event.dataTransfer?.dropEffect === 'copy') {
            setStatus(`${record.name} dropped. Waiting for Dola attachment verification…`, 'working');
        } else {
            setStatus(`Drag cancelled for ${record.name}.`, '');
        }
    }

    function openQueueDialog() {
        const firstQueued = state.images.find(image => image.status !== 'done');
        if (!firstQueued) {
            setStatus('Add at least one queued image first.', 'error');
            return;
        }
        openDialogFor(firstQueued.id);
    }

    function openDialogFor(id) {
        if (state.busy) return;
        const record = state.images.find(image => image.id === id);
        if (!record) return;

        releaseDialogPreview();
        state.selectedId = id;
        state.dialogUrl = URL.createObjectURL(record.blob);
        refs.dialogPreview.src = state.dialogUrl;
        refs.dialogName.textContent = record.name;

        const queued = state.images.filter(image => image.status !== 'done').length;
        refs.dialogDescription.textContent = `Current tab uploads this image. All tabs maps ${queued} queued image(s) to supported tabs in queue order.`;

        if (typeof refs.dialog.showModal === 'function') refs.dialog.showModal();
        else refs.dialog.setAttribute('open', '');
    }

    function closeDialog() {
        if (state.busy) return;
        if (refs.dialog.open && typeof refs.dialog.close === 'function') refs.dialog.close();
        else {
            refs.dialog.removeAttribute('open');
            releaseDialogPreview();
        }
    }

    function releaseDialogPreview() {
        if (state.dialogUrl) URL.revokeObjectURL(state.dialogUrl);
        state.dialogUrl = null;
        if (refs.dialogPreview) refs.dialogPreview.removeAttribute('src');
        state.selectedId = null;
    }

    async function uploadImageToActiveTab(imageId) {
        if (state.busy) return;
        const record = state.images.find(image => String(image.id) === String(imageId || ''));
        if (!record) return;

        setBusy(true);
        setStatus(`Preparing ${record.name} for the active tab…`, 'working');

        try {
            const tabs = await queryTabs({active: true, currentWindow: true});
            const tab = tabs[0];
            if (!tab?.id || !isSupportedUrl(tab.url)) {
                throw new Error('The active tab is not a supported Dola or SeaArt page.');
            }

            const uploadResult = await sendImageToTab(tab.id, record);
            const verifiedAt = Date.now();
            await patchRecord(record.id, {
                status: 'done',
                error: '',
                uploadedAt: verifiedAt,
                attachmentVerifiedAt: verifiedAt,
                attachmentEvidence: String(uploadResult.evidence || 'composer-ui-evidence')
            }, false);
            closeDialogAfterWork();
            renderQueue();
            setStatus(`${record.name} verified and attached to the active tab.`, 'success');
        } catch (error) {
            await patchRecord(record.id, {
                status: 'queued',
                error: friendlyError(error),
                uploadedAt: null,
                attachmentVerifiedAt: null,
                attachmentEvidence: ''
            }, false);
            renderQueue();
            setStatus(`Upload failed: ${friendlyError(error)}`, 'error');
        } finally {
            setBusy(false);
        }
    }

    async function uploadQueueSerially() {
        if (state.busy) return;
        const queued = state.images.filter(image => image.status !== 'done');
        if (!queued.length) {
            setStatus('There are no queued images to upload.', 'error');
            return;
        }

        setBusy(true);
        closeDialogAfterWork();

        let successCount = 0;
        let failureCount = 0;

        try {
            const tabs = (await queryTabs({}))
                .filter(tab => tab.id && isSupportedUrl(tab.url))
                .sort((left, right) => (left.windowId - right.windowId) || (left.index - right.index));

            if (!tabs.length) throw new Error('No open Dola or SeaArt tabs were found.');

            const pairCount = Math.min(queued.length, tabs.length);
            for (let index = 0; index < pairCount; index += 1) {
                const record = queued[index];
                const tab = tabs[index];
                setStatus(`Uploading ${index + 1}/${pairCount}: ${record.name} → ${tab.title || 'supported tab'}…`, 'working');

                try {
                    const uploadResult = await sendImageToTab(tab.id, record);
                    const verifiedAt = Date.now();
                    await patchRecord(record.id, {
                        status: 'done',
                        error: '',
                        uploadedAt: verifiedAt,
                        attachmentVerifiedAt: verifiedAt,
                        attachmentEvidence: String(uploadResult.evidence || 'composer-ui-evidence')
                    }, false);
                    successCount += 1;
                } catch (error) {
                    await patchRecord(record.id, {
                        status: 'queued',
                        error: friendlyError(error),
                        uploadedAt: null,
                        attachmentVerifiedAt: null,
                        attachmentEvidence: ''
                    }, false);
                    failureCount += 1;
                }

                renderQueue();
                if (index + 1 < pairCount) await delay(180);
            }

            const unmatched = queued.length - pairCount;
            const summary = `${successCount} image(s) uploaded${failureCount ? `, ${failureCount} failed` : ''}${unmatched > 0 ? `, ${unmatched} left queued (not enough tabs)` : ''}.`;
            setStatus(summary, failureCount ? 'working' : 'success');
        } catch (error) {
            setStatus(`Serial upload could not start: ${friendlyError(error)}`, 'error');
        } finally {
            setBusy(false);
            renderQueue();
        }
    }

    async function sendImageToTab(tabId, record) {
        const dataUrl = await blobToDataUrl(record.blob);
        const response = await sendTabMessage(tabId, {
            action: UPLOAD_ACTION,
            image: {
                name: record.name,
                type: record.type || guessMimeType(record.name),
                size: record.size,
                lastModified: record.lastModified,
                dataUrl
            }
        });

        if (!response?.success || response?.verified !== true) {
            throw new Error(response?.error || 'Dola did not confirm an attached image preview.');
        }
        return response;
    }

    async function removeRecord(id) {
        if (state.busy) return;
        try {
            await deleteRecord(id);
            state.images = state.images.filter(image => image.id !== id);
            renderQueue();
            setStatus('Image removed from the queue.', 'success');
        } catch (error) {
            setStatus(`Could not remove image: ${error.message}`, 'error');
        }
    }

    async function clearQueue() {
        if (state.busy || !state.images.length) return;
        if (!window.confirm('Clear every image and its upload status?')) return;

        try {
            await clearRecords();
            state.images = [];
            renderQueue();
            setStatus('Image queue cleared.', 'success');
        } catch (error) {
            setStatus(`Could not clear the image queue: ${error.message}`, 'error');
        }
    }

    async function patchRecord(id, patch, shouldRender = true) {
        const record = state.images.find(image => image.id === id);
        if (!record) return;
        Object.assign(record, patch);
        await putRecords([record]);
        if (shouldRender) renderQueue();
    }

    function setBusy(isBusy) {
        state.busy = isBusy;
        [refs.input, refs.selectButton, refs.clearButton, refs.queueButton, refs.uploadActive, refs.uploadAll]
            .filter(Boolean)
            .forEach(control => {
                control.disabled = isBusy || (control === refs.queueButton && !state.images.some(image => image.status !== 'done'));
            });
        refs.container?.querySelectorAll('button').forEach(button => {
            button.disabled = isBusy;
        });
        refs.container?.querySelectorAll('.image-queue-item').forEach(item => {
            item.draggable = !isBusy;
            item.setAttribute('aria-disabled', String(isBusy));
        });
    }

    function setStatus(message, status = '') {
        refs.status.textContent = message || '';
        if (status) refs.status.dataset.state = status;
        else delete refs.status.dataset.state;
    }

    function publishOverlaySummary(queuedCount, doneCount) {
        if (!chrome?.storage?.local) return;
        const lastUploaded = state.images
            .filter(image => image.status === 'done' && image.uploadedAt)
            .sort((left, right) => right.uploadedAt - left.uploadedAt)[0];
        const coreSummary = {
            total: state.images.length,
            queued: queuedCount,
            done: doneCount,
            lastUploadedName: lastUploaded?.name || '',
            images: state.images.map(image => ({
                id: String(image.id),
                name: String(image.name || 'Untitled image'),
                status: image.status === 'done' ? 'done' : 'queued',
                order: Number(image.order) || 0,
                size: Number(image.size) || 0,
                error: String(image.error || '')
            })),
            source: 'popup'
        };
        const signature = JSON.stringify(coreSummary);
        if (signature === lastOverlaySummarySignature) return;
        lastOverlaySummarySignature = signature;
        chrome.storage.local.set({
            [OVERLAY_SUMMARY_STORAGE_KEY]: {
                ...coreSummary,
                updatedAt: Date.now()
            }
        });
    }
    function closeDialogAfterWork() {
        if (refs.dialog.open && typeof refs.dialog.close === 'function') refs.dialog.close();
        else {
            refs.dialog.removeAttribute('open');
            releaseDialogPreview();
        }
    }

    function releaseCardPreviews() {
        state.cardUrls.forEach(url => URL.revokeObjectURL(url));
        state.cardUrls.clear();
    }

    function sortImages() {
        state.images.sort((left, right) => (left.order - right.order) || (left.addedAt - right.addedAt));
    }

    function isImageFile(file) {
        if (!file) return false;
        const mimeType = String(file.type || '').toLowerCase();
        return SUPPORTED_MIME_TYPES.has(mimeType) || (
            !mimeType && /\.(?:avif|gif|jpe?g|png|webp)$/i.test(file.name || '')
        );
    }

    function guessMimeType(name) {
        const extension = String(name || '').split('.').pop()?.toLowerCase();
        return ({
            avif: 'image/avif',
            gif: 'image/gif',
            jpeg: 'image/jpeg',
            jpg: 'image/jpeg',
            png: 'image/png',
            webp: 'image/webp'
        })[extension] || 'image/png';
    }

    function isSupportedUrl(value) {
        try {
            const url = new URL(value);
            return ['http:', 'https:'].includes(url.protocol) && SUPPORTED_HOSTS.some(host => (
                url.hostname === host || url.hostname.endsWith(`.${host}`)
            ));
        } catch {
            return false;
        }
    }

    function formatBytes(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function createId() {
        if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
        return `image-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function delay(milliseconds) {
        return new Promise(resolve => window.setTimeout(resolve, milliseconds));
    }

    function blobToDataUrl(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error || new Error('Could not read the image file.'));
            reader.readAsDataURL(blob);
        });
    }

    function queryTabs(query) {
        return new Promise((resolve, reject) => {
            chrome.tabs.query(query, tabs => {
                const error = chrome.runtime.lastError;
                if (error) reject(new Error(error.message));
                else resolve(tabs || []);
            });
        });
    }

    function sendTabMessage(tabId, message) {
        return new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tabId, message, response => {
                const error = chrome.runtime.lastError;
                if (error) reject(new Error(error.message));
                else resolve(response);
            });
        });
    }

    function friendlyError(error) {
        const message = error?.message || String(error);
        if (/receiving end does not exist|could not establish connection/i.test(message)) {
            return 'Refresh the target page once so the image uploader can connect.';
        }
        if (/message length|native message host/i.test(message)) {
            return 'This image is too large to send to the page.';
        }
        return message;
    }

    function openDatabase() {
        if (databasePromise) return databasePromise;
        databasePromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains(STORE_NAME)) {
                    const store = database.createObjectStore(STORE_NAME, {keyPath: 'id'});
                    store.createIndex('order', 'order', {unique: false});
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('IndexedDB could not be opened.'));
        });
        return databasePromise;
    }

    async function getAllRecords() {
        const database = await openDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(STORE_NAME, 'readonly');
            const request = transaction.objectStore(STORE_NAME).getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error || new Error('Image queue could not be read.'));
        });
    }

    async function putRecords(records) {
        const database = await openDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(STORE_NAME, 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            records.forEach(record => store.put(record));
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error || new Error('Image queue could not be saved.'));
            transaction.onabort = () => reject(transaction.error || new Error('Image queue save was aborted.'));
        });
    }

    async function deleteRecord(id) {
        const database = await openDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(STORE_NAME, 'readwrite');
            transaction.objectStore(STORE_NAME).delete(id);
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error || new Error('Image could not be removed.'));
        });
    }

    async function clearRecords() {
        const database = await openDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(STORE_NAME, 'readwrite');
            transaction.objectStore(STORE_NAME).clear();
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error || new Error('Image queue could not be cleared.'));
        });
    }

    window.addEventListener('unload', () => {
        releaseCardPreviews();
        releaseDialogPreview();
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, {once: true});
    } else {
        initialize();
    }
})();
