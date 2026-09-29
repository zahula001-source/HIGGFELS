(() => {
    'use strict';

    const INSTALL_FLAG = '__studioRelayPageOverlaysInstalled';
    const ROOT_ID = 'studio-relay-page-overlays';
    const SUMMARY_STORAGE_KEY = 'studio_relay_image_overlay_summary';
    const ARM_EVENT = 'studio-relay:arm-click-sync';
    const SYNC_STATE_EVENT = 'studio-relay:click-sync-state';

    if (globalThis[INSTALL_FLAG]) return;
    globalThis[INSTALL_FLAG] = true;

    const state = {
        summary: {
            total: 0,
            queued: 0,
            done: 0,
            lastUploadedName: ''
        },
        imagesExpanded: false,
        syncArmed: false,
        positionTimer: null
    };

    const refs = {};

    function initialize() {
        if (document.getElementById(ROOT_ID)) return;
        createOverlay();
        installInteractions();
        loadImageSummary();
        updateImageSummaryUi();
        updateHitUi();
        positionBelowPrompts();

        state.positionTimer = window.setInterval(positionBelowPrompts, 1200);
        window.addEventListener('resize', positionBelowPrompts, {passive: true});
    }

    function createOverlay() {
        const root = document.createElement('aside');
        root.id = ROOT_ID;
        root.setAttribute('aria-label', 'StudioRelay page controls');

        const imagesCard = document.createElement('section');
        imagesCard.className = 'studio-relay-page-overlay-card';

        const imagesToggle = document.createElement('button');
        imagesToggle.id = 'studio-relay-images-overlay-toggle';
        imagesToggle.className = 'studio-relay-page-overlay-pill';
        imagesToggle.type = 'button';
        imagesToggle.setAttribute('aria-expanded', 'false');

        const imagesLabel = document.createElement('span');
        imagesLabel.id = 'studio-relay-images-overlay-label';
        imagesLabel.className = 'studio-relay-page-overlay-label';

        const imagesArrow = document.createElement('span');
        imagesArrow.className = 'studio-relay-page-overlay-arrow';
        imagesArrow.setAttribute('aria-hidden', 'true');
        imagesArrow.textContent = '◀';
        imagesToggle.append(imagesLabel, imagesArrow);

        const imagesPanel = document.createElement('div');
        imagesPanel.id = 'studio-relay-images-overlay-panel';
        imagesPanel.className = 'studio-relay-page-overlay-panel';
        imagesPanel.hidden = true;

        const panelTitle = document.createElement('strong');
        panelTitle.textContent = 'Image queue';

        const stats = document.createElement('div');
        stats.className = 'studio-relay-image-overlay-stats';
        const allStat = createStat('All', 'studio-relay-image-stat-all');
        const queuedStat = createStat('Queued', 'studio-relay-image-stat-queued');
        const doneStat = createStat('Done', 'studio-relay-image-stat-done');
        stats.append(allStat.wrapper, queuedStat.wrapper, doneStat.wrapper);

        const lastUpload = document.createElement('p');
        lastUpload.id = 'studio-relay-image-last-upload';
        lastUpload.className = 'studio-relay-image-last-upload';

        const hint = document.createElement('p');
        hint.className = 'studio-relay-page-overlay-hint';
        hint.textContent = 'Use the Images tab in StudioRelay to select and upload files.';

        imagesPanel.append(panelTitle, stats, lastUpload, hint);
        imagesCard.append(imagesToggle, imagesPanel);

        const hitButton = document.createElement('button');
        hitButton.id = 'studio-relay-hit-video-overlay';
        hitButton.className = 'studio-relay-page-overlay-pill studio-relay-hit-video-pill';
        hitButton.type = 'button';

        const hitLabel = document.createElement('span');
        hitLabel.id = 'studio-relay-hit-video-label';
        hitLabel.className = 'studio-relay-page-overlay-label';

        const hitState = document.createElement('span');
        hitState.id = 'studio-relay-hit-video-state';
        hitState.className = 'studio-relay-hit-video-state';
        hitButton.append(hitLabel, hitState);

        root.append(imagesCard, hitButton);
        (document.body || document.documentElement).append(root);

        Object.assign(refs, {
            root,
            imagesToggle,
            imagesLabel,
            imagesArrow,
            imagesPanel,
            allCount: allStat.value,
            queuedCount: queuedStat.value,
            doneCount: doneStat.value,
            lastUpload,
            hitButton,
            hitLabel,
            hitState
        });
    }

    function createStat(label, valueId) {
        const wrapper = document.createElement('span');
        const caption = document.createElement('small');
        caption.textContent = label;
        const value = document.createElement('strong');
        value.id = valueId;
        value.textContent = '0';
        wrapper.append(caption, value);
        return {wrapper, value};
    }

    function installInteractions() {
        refs.imagesToggle.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            state.imagesExpanded = !state.imagesExpanded;
            refs.imagesPanel.hidden = !state.imagesExpanded;
            refs.imagesToggle.setAttribute('aria-expanded', String(state.imagesExpanded));
            refs.imagesArrow.textContent = state.imagesExpanded ? '▼' : '◀';
            refs.root.classList.toggle('images-expanded', state.imagesExpanded);
            window.setTimeout(positionBelowPrompts, 0);
        });

        refs.hitButton.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            document.dispatchEvent(new CustomEvent(ARM_EVENT));
        });

        document.addEventListener(SYNC_STATE_EVENT, event => {
            state.syncArmed = Boolean(event.detail?.armed);
            updateHitUi();
        });

        if (chrome?.storage?.onChanged) {
            chrome.storage.onChanged.addListener((changes, areaName) => {
                if (areaName !== 'local' || !changes[SUMMARY_STORAGE_KEY]) return;
                applyImageSummary(changes[SUMMARY_STORAGE_KEY].newValue);
            });
        }

        window.addEventListener('unload', () => {
            if (state.positionTimer) window.clearInterval(state.positionTimer);
        });
    }

    function loadImageSummary() {
        if (!chrome?.storage?.local) return;
        chrome.storage.local.get([SUMMARY_STORAGE_KEY], result => {
            const error = chrome.runtime.lastError;
            if (error) return;
            applyImageSummary(result?.[SUMMARY_STORAGE_KEY]);
        });
    }

    function applyImageSummary(value) {
        const summary = value && typeof value === 'object' ? value : {};
        state.summary = {
            total: toSafeCount(summary.total),
            queued: toSafeCount(summary.queued),
            done: toSafeCount(summary.done),
            lastUploadedName: String(summary.lastUploadedName || '')
        };
        updateImageSummaryUi();
    }

    function updateImageSummaryUi() {
        if (!refs.imagesLabel) return;
        const {total, queued, done, lastUploadedName} = state.summary;
        refs.imagesLabel.textContent = `🖼️ Images (${done}/${total})`;
        refs.allCount.textContent = String(total);
        refs.queuedCount.textContent = String(queued);
        refs.doneCount.textContent = String(done);
        refs.lastUpload.textContent = lastUploadedName
            ? `Last uploaded: ${lastUploadedName}`
            : 'No image uploaded yet.';
        refs.lastUpload.title = lastUploadedName;
    }

    function updateHitUi() {
        if (!refs.hitButton) return;
        refs.hitLabel.textContent = state.syncArmed ? '🎯 Hit Video Active' : '🎯 Hit Video';
        refs.hitState.textContent = state.syncArmed ? 'ACTIVE' : 'READY';
        refs.hitButton.classList.toggle('is-active', state.syncArmed);
        refs.hitButton.setAttribute('aria-pressed', String(state.syncArmed));
        refs.hitButton.title = state.syncArmed
            ? 'Click sync is active. Click a page button to mirror it across Dola tabs.'
            : 'Arm click sync. No page action is triggered until you manually choose a target.';
    }

    function positionBelowPrompts() {
        if (!refs.root?.isConnected) return;
        const promptPill = findPromptPill();
        const rootWidth = Math.max(146, Math.min(220, promptPill?.getBoundingClientRect().width || 156));
        let left = 44;
        let top = 62;

        if (promptPill) {
            const rect = promptPill.getBoundingClientRect();
            left = rect.left;
            top = rect.bottom + 8;
        }

        left = clamp(left, 8, Math.max(8, window.innerWidth - rootWidth - 8));
        const rootHeight = Math.max(90, refs.root.offsetHeight || 90);
        top = clamp(top, 8, Math.max(8, window.innerHeight - rootHeight - 8));

        refs.root.style.width = `${rootWidth}px`;
        refs.root.style.left = `${Math.round(left)}px`;
        refs.root.style.top = `${Math.round(top)}px`;
    }

    function findPromptPill() {
        const candidates = Array.from(document.querySelectorAll('button, [role="button"], [id^="channa-"]'))
            .filter(element => !element.closest(`#${ROOT_ID}`))
            .filter(element => /^\s*(?:📝\s*)?Prompts\s*\(\s*\d+\s*\/\s*\d+\s*\)\s*[◀▶▼▲]?\s*$/i.test(element.textContent || ''))
            .filter(isVisible)
            .map(element => {
                const rect = element.getBoundingClientRect();
                return {element, area: rect.width * rect.height};
            })
            .filter(candidate => candidate.area > 0)
            .sort((left, right) => left.area - right.area);

        return candidates[0]?.element || null;
    }

    function isVisible(element) {
        const rect = element.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const style = getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0;
    }

    function toSafeCount(value) {
        const number = Number(value);
        return Number.isFinite(number) && number >= 0 ? Math.floor(number) : 0;
    }

    function clamp(value, minimum, maximum) {
        return Math.min(Math.max(value, minimum), maximum);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, {once: true});
    } else {
        initialize();
    }
})();
