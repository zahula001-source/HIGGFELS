(function () {
  'use strict';

  if (window.__brandAiRawDownloaderInstalled) return;
  window.__brandAiRawDownloaderInstalled = true;

  const seenMedia = new Set();
  const cancelledMedia = new Set();
  const cancelledBuildIds = new Set();
  const pendingPageBatches = new Map();
  const extractedVideosPool = new Map();
  const BATCH_SETTLE_MS = 250;
  const ZIP_OVERLAY_ID = 'brandai-video-zip-overlay';
  const MINI_BADGE_ID = 'brandai-video-zip-minibadge';
  const TOAST_ID = 'brandai-individual-video-toast';
  const SCROLL_PILL_ID = 'brandai-chat-scroll-pill';
  let overlayHideTimer = 0;
  let toastTimer = 0;
  let currentBuildId = '';
  let isCurrentDownloadPaused = false;
  let lastProgressData = null;
  let isAutoScrolling = false;
  let autoScrollTimer = null;
  let autoScrollContainer = null;

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes <= 0) return '';
    if (bytes < 1024) return `${Math.round(bytes)} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function appendElement(parent, tag, properties = {}) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(properties)) {
      if (key === 'text') element.textContent = value;
      else if (key === 'html') element.innerHTML = value;
      else if (key === 'style') element.style.cssText = value;
      else element.setAttribute(key, value);
    }
    parent.appendChild(element);
    return element;
  }

  function ensureMiniBadge() {
    let badge = document.getElementById(MINI_BADGE_ID);
    if (badge) return badge;

    badge = appendElement(document.body || document.documentElement, 'div', {
      id: MINI_BADGE_ID,
      style: [
        'position:fixed',
        'bottom:24px',
        'right:24px',
        'z-index:2147483647',
        'display:none',
        'align-items:center',
        'gap:10px',
        'padding:10px 18px',
        'border-radius:30px',
        'background:rgba(17,24,39,0.94)',
        'backdrop-filter:blur(12px)',
        'border:1px solid rgba(129,140,248,0.5)',
        'box-shadow:0 12px 36px rgba(0,0,0,0.55)',
        'color:#f8fafc',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
        'font-size:13px',
        'font-weight:600',
        'cursor:pointer',
        'transition:all 0.2s ease',
        'user-select:none'
      ].join(';')
    });

    badge.addEventListener('click', () => {
      const overlay = document.getElementById(ZIP_OVERLAY_ID);
      if (overlay) overlay.style.display = 'flex';
      badge.style.display = 'none';
    });

    badge.addEventListener('mouseenter', () => {
      badge.style.transform = 'scale(1.04)';
      badge.style.borderColor = '#818cf8';
    });
    badge.addEventListener('mouseleave', () => {
      badge.style.transform = 'scale(1)';
    });

    return badge;
  }

  function updateMiniBadge(progress = {}) {
    const badge = ensureMiniBadge();
    const percent = Math.round(Math.min(100, Math.max(0, Number(progress.percent) || 0)));
    const stage = progress.stage || 'downloading';
    if (stage === 'complete' || stage === 'error' || stage === 'cancelled') {
      badge.style.display = 'none';
      return;
    }
    badge.innerHTML = `
      <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${progress.isPaused ? '#f59e0b' : '#6366f1'};box-shadow:0 0 8px ${progress.isPaused ? '#f59e0b' : '#6366f1'};"></span>
      <span>⚡ <b>Kartar's ZIP</b> ${progress.isPaused ? 'Paused' : 'Downloading'}: <b>${percent}%</b></span>
    `;
  }

  function ensureZipOverlay() {
    let overlay = document.getElementById(ZIP_OVERLAY_ID);
    if (overlay) return overlay;

    overlay = appendElement(document.body || document.documentElement, 'div', {
      id: ZIP_OVERLAY_ID,
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': 'brandai-video-zip-title',
      style: [
        'position:fixed',
        'inset:0',
        'z-index:2147483646',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'padding:20px',
        'background:rgba(15,23,42,.75)',
        'backdrop-filter:blur(6px)',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
        'user-select:none'
      ].join(';')
    });

    const card = appendElement(overlay, 'div', {
      style: [
        'position:relative',
        'width:min(500px,100%)',
        'box-sizing:border-box',
        'padding:26px 28px',
        'border:1px solid rgba(129,140,248,.45)',
        'border-radius:20px',
        'background:linear-gradient(145deg, #111827, #0f172a)',
        'color:#f8fafc',
        'box-shadow:0 24px 70px rgba(0,0,0,.65)'
      ].join(';')
    });

    // Branding Badge Pill
    const badgeRow = appendElement(card, 'div', {
      style: 'display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;'
    });

    appendElement(badgeRow, 'div', {
      html: '<span style="color:#818cf8;margin-right:4px;">⚡</span> Bulk Downloader by <b>Kartar</b>',
      style: [
        'display:inline-flex',
        'align-items:center',
        'padding:4px 12px',
        'border-radius:20px',
        'background:rgba(99,102,241,0.18)',
        'border:1px solid rgba(129,140,248,0.35)',
        'font-size:11.5px',
        'font-weight:600',
        'color:#c7d2fe',
        'letter-spacing:0.3px'
      ].join(';')
    });

    const closeBtn = appendElement(badgeRow, 'button', {
      id: 'brandai-video-zip-close-btn',
      text: '✕',
      title: 'Minimize / Close overlay (Download continues in background)',
      style: [
        'background:rgba(255,255,255,0.08)',
        'border:none',
        'color:#94a3b8',
        'font-size:15px',
        'font-weight:bold',
        'width:28px',
        'height:28px',
        'border-radius:50%',
        'cursor:pointer',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'transition:all 0.2s ease'
      ].join(';')
    });

    closeBtn.addEventListener('mouseenter', () => {
      closeBtn.style.background = 'rgba(255,255,255,0.18)';
      closeBtn.style.color = '#ffffff';
    });
    closeBtn.addEventListener('mouseleave', () => {
      closeBtn.style.background = 'rgba(255,255,255,0.08)';
      closeBtn.style.color = '#94a3b8';
    });
    closeBtn.addEventListener('click', () => {
      overlay.style.display = 'none';
      const badge = ensureMiniBadge();
      badge.style.display = 'flex';
    });

    // Title Row
    appendElement(card, 'div', {
      id: 'brandai-video-zip-title',
      text: 'Preparing video ZIP',
      style: 'font-size:21px;font-weight:750;line-height:1.25;margin-bottom:6px;'
    });

    // Subtitle / Status
    appendElement(card, 'div', {
      id: 'brandai-video-zip-status',
      text: 'Starting parallel downloads (10 in parallel)…',
      role: 'status',
      'aria-live': 'polite',
      style: 'font-size:14.5px;line-height:1.5;color:#cbd5e1;margin-bottom:16px'
    });

    // Progress Bar Track
    const track = appendElement(card, 'div', {
      role: 'progressbar',
      'aria-valuemin': '0',
      'aria-valuemax': '100',
      'aria-valuenow': '0',
      style: 'height:11px;overflow:hidden;border-radius:999px;background:#1e293b;border:1px solid rgba(255,255,255,0.05);'
    });
    appendElement(track, 'div', {
      id: 'brandai-video-zip-progress',
      style: [
        'width:0%',
        'height:100%',
        'border-radius:inherit',
        'background:linear-gradient(90deg,#6366f1,#a855f7)',
        'transition:width .2s ease'
      ].join(';')
    });

    // Percent & Bytes Row
    const statsRow = appendElement(card, 'div', {
      style: 'display:flex;align-items:center;justify-content:space-between;margin-top:8px;'
    });
    appendElement(statsRow, 'div', {
      id: 'brandai-video-zip-file',
      text: '10 Parallel Video Streams Active',
      style: 'font-size:12.5px;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:75%;'
    });
    appendElement(statsRow, 'div', {
      id: 'brandai-video-zip-percent',
      text: '0%',
      style: 'font-size:13.5px;font-weight:750;color:#a5b4fc'
    });

    // Action Controls Row: Pause / Resume & Cancel Buttons
    const actionsRow = appendElement(card, 'div', {
      id: 'brandai-video-zip-actions',
      style: 'display:flex;align-items:center;gap:12px;margin-top:20px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.08);'
    });

    const pauseBtn = appendElement(actionsRow, 'button', {
      id: 'brandai-video-zip-pause-btn',
      text: '⏸ Pause',
      style: [
        'flex:1',
        'padding:8px 16px',
        'border-radius:10px',
        'border:1px solid rgba(129,140,248,0.4)',
        'background:rgba(99,102,241,0.15)',
        'color:#e0e7ff',
        'font-size:13px',
        'font-weight:600',
        'cursor:pointer',
        'transition:all 0.2s ease'
      ].join(';')
    });

    pauseBtn.addEventListener('mouseenter', () => {
      pauseBtn.style.background = 'rgba(99,102,241,0.3)';
    });
    pauseBtn.addEventListener('mouseleave', () => {
      pauseBtn.style.background = isCurrentDownloadPaused ? 'rgba(245,158,11,0.2)' : 'rgba(99,102,241,0.15)';
    });

    pauseBtn.addEventListener('click', () => {
      isCurrentDownloadPaused = !isCurrentDownloadPaused;
      pauseBtn.textContent = isCurrentDownloadPaused ? '▶ Resume' : '⏸ Pause';
      pauseBtn.style.borderColor = isCurrentDownloadPaused ? 'rgba(245,158,11,0.5)' : 'rgba(129,140,248,0.4)';
      pauseBtn.style.background = isCurrentDownloadPaused ? 'rgba(245,158,11,0.2)' : 'rgba(99,102,241,0.15)';
      pauseBtn.style.color = isCurrentDownloadPaused ? '#fde68a' : '#e0e7ff';

      chrome.runtime.sendMessage({
        type: isCurrentDownloadPaused ? 'BRANDAI_PAUSE_VIDEO_ZIP' : 'BRANDAI_RESUME_VIDEO_ZIP',
        buildId: currentBuildId
      }).catch(() => {});
    });

    const cancelBtn = appendElement(actionsRow, 'button', {
      id: 'brandai-video-zip-cancel-btn',
      text: '⏹ Cancel Download',
      style: [
        'flex:1',
        'padding:8px 16px',
        'border-radius:10px',
        'border:1px solid rgba(239,68,68,0.4)',
        'background:rgba(239,68,68,0.12)',
        'color:#fca5a5',
        'font-size:13px',
        'font-weight:600',
        'cursor:pointer',
        'transition:all 0.2s ease'
      ].join(';')
    });

    cancelBtn.addEventListener('mouseenter', () => {
      cancelBtn.style.background = 'rgba(239,68,68,0.25)';
    });
    cancelBtn.addEventListener('mouseleave', () => {
      cancelBtn.style.background = 'rgba(239,68,68,0.12)';
    });

    cancelBtn.addEventListener('click', () => {
      const buildIdToCancel = currentBuildId;
      if (buildIdToCancel) {
        cancelledBuildIds.add(buildIdToCancel);
      }

      // Cancel and clear any pending debounce batches so no delayed downloads fire
      for (const batch of pendingPageBatches.values()) {
        clearTimeout(batch.timerId);
      }
      pendingPageBatches.clear();

      // Remember all currently seen media as cancelled so we do not re-queue them
      for (const key of seenMedia) {
        cancelledMedia.add(key);
      }

      chrome.runtime.sendMessage({
        type: 'BRANDAI_CANCEL_VIDEO_ZIP',
        buildId: buildIdToCancel
      }).catch(() => {});

      clearTimeout(overlayHideTimer);
      overlay.remove();
      const badge = document.getElementById(MINI_BADGE_ID);
      if (badge) badge.remove();
    });

    // Footer Hint with Kartar Branding
    const footer = appendElement(card, 'div', {
      style: 'margin-top:14px;font-size:11.5px;line-height:1.45;color:#64748b;display:flex;align-items:center;justify-content:space-between;'
    });
    appendElement(footer, 'span', {
      text: '⚡ Bulk Downloader by Kartar',
      style: 'color:#818cf8;font-weight:600;'
    });
    appendElement(footer, 'span', {
      text: 'ZIP auto-saves to Downloads'
    });

    return overlay;
  }

  function updateZipOverlay(progress = {}) {
    try {
      clearTimeout(overlayHideTimer);
      lastProgressData = progress;
      if (progress.buildId) currentBuildId = progress.buildId;

      if (progress.buildId && cancelledBuildIds.has(progress.buildId)) {
        const overlay = document.getElementById(ZIP_OVERLAY_ID);
        if (overlay) overlay.remove();
        const badge = document.getElementById(MINI_BADGE_ID);
        if (badge) badge.remove();
        return;
      }

      const overlay = ensureZipOverlay();
      const stage = String(progress.stage || 'downloading');
      const total = Math.max(0, Number(progress.total) || 0);
      const completed = Math.min(total, Math.max(0, Number(progress.completed) || 0));
      const percent = Math.min(100, Math.max(0, Number(progress.percent) || 0));
      const status = overlay.querySelector('#brandai-video-zip-status');
      const bar = overlay.querySelector('#brandai-video-zip-progress');
      const track = bar?.parentElement;
      const percentLabel = overlay.querySelector('#brandai-video-zip-percent');
      const fileLabel = overlay.querySelector('#brandai-video-zip-file');
      const title = overlay.querySelector('#brandai-video-zip-title');
      const actions = overlay.querySelector('#brandai-video-zip-actions');
      const pauseBtn = overlay.querySelector('#brandai-video-zip-pause-btn');

      if (progress.isPaused !== undefined && pauseBtn) {
        isCurrentDownloadPaused = Boolean(progress.isPaused);
        pauseBtn.textContent = isCurrentDownloadPaused ? '▶ Resume' : '⏸ Pause';
        pauseBtn.style.borderColor = isCurrentDownloadPaused ? 'rgba(245,158,11,0.5)' : 'rgba(129,140,248,0.4)';
        pauseBtn.style.background = isCurrentDownloadPaused ? 'rgba(245,158,11,0.2)' : 'rgba(99,102,241,0.15)';
        pauseBtn.style.color = isCurrentDownloadPaused ? '#fde68a' : '#e0e7ff';
      }

      const activeConcurrency = progress.concurrency || 10;
      let statusText = total
        ? `${completed} of ${total} videos downloaded (${activeConcurrency} in parallel)`
        : 'Starting video downloads in parallel…';

      if (progress.isPaused) {
        statusText = `⏸ Paused (${completed} of ${total} videos downloaded)`;
      } else if (stage === 'packing') {
        statusText = `All ${total} videos downloaded! Assembling ZIP…`;
      } else if (stage === 'saving') {
        statusText = 'ZIP is ready. Saving it to Downloads…';
      } else if (stage === 'complete') {
        statusText = `ZIP download completed! (${total} videos saved)`;
      } else if (stage === 'error') {
        statusText = progress.error || 'ZIP download could not be completed.';
      } else if (stage === 'cancelled') {
        statusText = 'ZIP download was cancelled.';
      }

      if (status) status.textContent = statusText;
      if (bar) bar.style.width = `${percent}%`;
      track?.setAttribute('aria-valuenow', String(Math.round(percent)));
      if (percentLabel) percentLabel.textContent = `${Math.round(percent)}%`;

      const byteText = progress.currentTotal
        ? `${formatBytes(progress.currentBytes)} / ${formatBytes(progress.currentTotal)}`
        : formatBytes(progress.currentBytes);
      if (fileLabel) {
        fileLabel.textContent = byteText ? `Downloading in parallel — ${byteText}` : (progress.filename || '10 Parallel Video Streams');
      }

      updateMiniBadge(progress);

      if (stage === 'complete') {
        if (title) title.textContent = '✅ Video ZIP Ready!';
        if (bar) bar.style.background = '#22c55e';
        if (actions) actions.style.display = 'none';
        overlayHideTimer = setTimeout(() => {
          overlay.remove();
          const badge = document.getElementById(MINI_BADGE_ID);
          if (badge) badge.remove();
        }, 2200);
      } else if (stage === 'error' || stage === 'cancelled') {
        if (stage === 'cancelled') {
          overlay.remove();
          const badge = document.getElementById(MINI_BADGE_ID);
          if (badge) badge.remove();
          return;
        }
        if (title) title.textContent = 'ZIP Download Failed';
        if (bar) bar.style.background = '#ef4444';
        if (actions) actions.style.display = 'none';
        overlayHideTimer = setTimeout(() => {
          overlay.remove();
          const badge = document.getElementById(MINI_BADGE_ID);
          if (badge) badge.remove();
        }, 4000);
      }
    } catch {}
  }

  function mediaKey(video) {
    return String(video?.key || video?.vid || video?.url || '');
  }

  function releaseVideo(video) {
    const key = mediaKey(video);
    const url = String(video?.url || '');
    if (cancelledMedia.has(key) || cancelledMedia.has(url)) return;
    if (key) seenMedia.delete(key);
    if (url) seenMedia.delete(url);
  }

  function queuePageVideo(video) {
    const pageUrl = String(video.pageUrl || location.href);
    const key = mediaKey(video);
    const url = String(video?.url || '');
    if (cancelledMedia.has(key) || cancelledMedia.has(url)) return;

    let batch = pendingPageBatches.get(pageUrl);
    if (!batch) {
      batch = { pageUrl, videos: new Map(), timerId: 0, forceTimerId: 0, pendingRemaining: 0 };
      pendingPageBatches.set(pageUrl, batch);
    }

    batch.videos.set(key, video);
    if (typeof video.pendingRemaining === 'number') {
      batch.pendingRemaining = video.pendingRemaining;
    }

    clearTimeout(batch.timerId);

    // If it's a standalone single video generation (batchTotal === 1 and pendingRemaining === 0)
    if (video.batchTotal === 1 && (!video.pendingRemaining || video.pendingRemaining === 0)) {
      batch.timerId = setTimeout(() => void flushPageBatch(pageUrl), 0);
      return;
    }

    // If there are still extractions pending (e.g. bulk chat history resolving over network),
    // wait for DOLA_VIDEO_EXTRACTIONS_COMPLETED or fallback to BATCH_SETTLE_MS
    if (batch.pendingRemaining > 0) {
      batch.timerId = setTimeout(() => void flushPageBatch(pageUrl), BATCH_SETTLE_MS);
      if (!batch.forceTimerId) {
        batch.forceTimerId = setTimeout(() => {
          if (pendingPageBatches.has(pageUrl)) {
            void flushPageBatch(pageUrl, true);
          }
        }, 1200);
      }
    } else {
      batch.timerId = setTimeout(() => void flushPageBatch(pageUrl), 50);
    }
  }

  window.addEventListener('DOLA_VIDEO_EXTRACTIONS_COMPLETED', event => {
    const pageUrl = String(event?.detail?.pageUrl || location.href);
    const batch = pendingPageBatches.get(pageUrl);
    if (batch && batch.videos.size > 0) {
      batch.pendingRemaining = 0;
      clearTimeout(batch.timerId);
      clearTimeout(batch.forceTimerId);
      batch.forceTimerId = 0;
      batch.timerId = setTimeout(() => void flushPageBatch(pageUrl), 20);
    }
  });

  const BULK_DOCK_ID = 'brandai-bulk-mode-dock';
  let isStorageInitialized = false;
  let isBulkModeActive = false;

  chrome.storage.local.get(['brandai_bulk_mode'], res => {
    isBulkModeActive = Boolean(res?.brandai_bulk_mode);
    isStorageInitialized = true;
    updateBulkDock();
    if (!isBulkModeActive) {
      for (const [pageUrl] of pendingPageBatches) {
        void flushPageBatch(pageUrl);
      }
    }
  });

  chrome.storage.onChanged.addListener(changes => {
    if (changes.brandai_bulk_mode) {
      isBulkModeActive = Boolean(changes.brandai_bulk_mode.newValue);
      isStorageInitialized = true;
      updateBulkDock();
    }
  });

  function setBulkMode(enabled) {
    isBulkModeActive = Boolean(enabled);
    isStorageInitialized = true;
    chrome.storage.local.set({ brandai_bulk_mode: isBulkModeActive });
    updateBulkDock();
  }

  async function flushPageBatch(pageUrl, force = false, isManualTrigger = false) {
    const batch = pendingPageBatches.get(pageUrl);
    if (!batch) return;

    // If storage hasn't answered yet, wait before making any auto-download decision:
    if (!isStorageInitialized && !isManualTrigger) {
      setTimeout(() => void flushPageBatch(pageUrl, force, isManualTrigger), 80);
      return;
    }

    // IF BULK MODE IS ACTIVE (AND NOT A MANUAL USER CLICK ON DOWNLOAD BUTTON):
    // STRICTLY SUPPRESS ALL AUTO-DOWNLOADS! Keep extracted videos ready in the pool and update the dock.
    if (isBulkModeActive && !isManualTrigger) {
      updateBulkDock();
      return;
    }

    if (!force && batch.pendingRemaining > 0) {
      clearTimeout(batch.timerId);
      batch.timerId = setTimeout(() => void flushPageBatch(pageUrl), BATCH_SETTLE_MS);
      return;
    }

    const videos = Array.from(batch.videos.values()).filter(v => {
      const k = mediaKey(v);
      const u = String(v?.url || '');
      return !cancelledMedia.has(k) && !cancelledMedia.has(u);
    });
    if (!videos.length) return;

    if (isBulkModeActive && !isManualTrigger) {
      updateBulkDock();
      return;
    }

    pendingPageBatches.delete(pageUrl);
    clearTimeout(batch.timerId);
    clearTimeout(batch.forceTimerId);

    try {
      const response = await chrome.runtime.sendMessage({
        type: 'BRANDAI_RAW_VIDEO_BATCH_DOWNLOAD',
        pageUrl,
        videos
      });

      if (!response?.ok) {
        const isCancelled = response?.cancelled ||
          response?.error?.toLowerCase().includes('cancel') ||
          response?.reason?.toLowerCase().includes('cancel') ||
          (currentBuildId && cancelledBuildIds.has(currentBuildId));

        if (!isCancelled) {
          videos.forEach(releaseVideo);
          if (videos.length > 5) {
            updateZipOverlay({
              stage: 'error',
              error: response?.error || response?.reason || 'ZIP download could not be started.'
            });
          }
          console.warn('[BrandAI Raw Downloader] Batch download failed:', response?.error || response?.reason);
        } else {
          for (const v of videos) {
            const k = mediaKey(v);
            const u = String(v?.url || '');
            if (k) cancelledMedia.add(k);
            if (u) cancelledMedia.add(u);
          }
        }
        return;
      }

      for (const failed of response.failed || []) {
        releaseVideo(failed);
      }
      if (response.mode === 'zip') updateZipOverlay({ stage: 'saving', percent: 100 });
    } catch (error) {
      const isCancelled = error?.message?.toLowerCase().includes('cancel') ||
        (currentBuildId && cancelledBuildIds.has(currentBuildId));

      if (!isCancelled) {
        videos.forEach(releaseVideo);
        if (videos.length > 5) {
          updateZipOverlay({ stage: 'error', error: error?.message || String(error) });
        }
        console.warn('[BrandAI Raw Downloader] Batch download unavailable:', error);
      } else {
        for (const v of videos) {
          const k = mediaKey(v);
          const u = String(v?.url || '');
          if (k) cancelledMedia.add(k);
          if (u) cancelledMedia.add(u);
        }
      }
    }
  }

  function injectScrollStyles() {
    if (document.getElementById('brandai-scroll-styles')) return;
    const style = document.createElement('style');
    style.id = 'brandai-scroll-styles';
    style.textContent = `
      @keyframes brandai-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function findChatScrollContainer() {
    const selectors = [
      '[class*="chat-scroll" i]',
      '[class*="chat-list" i]',
      '[class*="chat-body" i]',
      '[class*="chat-content" i]',
      '[class*="chat-container" i]',
      '[class*="message-list" i]',
      '[class*="messageList" i]',
      '[class*="message-container" i]',
      '[class*="messages" i]',
      '[class*="conversation" i]',
      '[class*="history" i]',
      '[data-testid*="chat" i]',
      '[data-testid*="message" i]',
      'main',
      '[role="main"]'
    ];

    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (!el) continue;
        const style = window.getComputedStyle(el);
        const isScrollable = (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll');
        if (isScrollable && el.scrollHeight > el.clientHeight + 30) {
          return el;
        }
      }
    }

    let best = null;
    let maxDelta = 30;
    const all = document.querySelectorAll('div, main, section, article');
    for (const el of all) {
      const delta = el.scrollHeight - el.clientHeight;
      if (delta > maxDelta) {
        const style = window.getComputedStyle(el);
        if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
          maxDelta = delta;
          best = el;
        }
      }
    }
    if (best) return best;

    return document.scrollingElement || document.documentElement || document.body || window;
  }

  function scanDomAndChatVideos() {
    try {
      const list = window.__dolaChatVideos || window.chatVideos || [];
      if (Array.isArray(list)) {
        for (const v of list) {
          if (v && v.url && /^https?:\/\//i.test(v.url)) {
            const k = String(v.vid || v.url);
            if (!extractedVideosPool.has(k)) {
              extractedVideosPool.set(k, {
                ...v,
                url: String(v.url),
                pageUrl: location.href,
                source: 'fallback_api'
              });
            }
          }
        }
      }

      const elements = document.querySelectorAll('video, [data-video-url], [data-play-url], [src*=".mp4"]');
      for (const el of elements) {
        const url = el.src || el.currentSrc || el.getAttribute('data-video-url') || el.getAttribute('data-play-url');
        if (url && /^https?:\/\//i.test(url) && !url.startsWith('blob:')) {
          const k = url;
          if (!extractedVideosPool.has(k)) {
            extractedVideosPool.set(k, {
              url,
              vid: k,
              pageUrl: location.href,
              source: 'fallback_api'
            });
          }
        }
      }
    } catch {}
  }

  function startAutoScrollChat() {
    if (isAutoScrolling) {
      stopAutoScrollChat(false);
      return;
    }

    const container = findChatScrollContainer();
    isAutoScrolling = true;
    autoScrollContainer = container;
    updateBulkDock();

    let unchangedCount = 0;
    let lastScrollHeight = (container && container.scrollHeight) || 0;
    let iterations = 0;

    if (autoScrollTimer) clearInterval(autoScrollTimer);
    autoScrollTimer = setInterval(() => {
      if (!isAutoScrolling) {
        clearInterval(autoScrollTimer);
        autoScrollTimer = null;
        return;
      }

      iterations++;

      try {
        if (container === window || container === document.body || container === document.documentElement) {
          window.scrollBy({ top: -Math.max(500, window.innerHeight * 0.8), behavior: 'smooth' });
          if (window.scrollY <= 10) window.scrollTo({ top: 0, behavior: 'smooth' });
        } else if (container) {
          container.scrollBy({ top: -Math.max(500, container.clientHeight * 0.8), behavior: 'smooth' });
          if (container.scrollTop <= 15) container.scrollTop = 0;
          container.dispatchEvent(new Event('scroll', { bubbles: true }));
        }

        const firstEl = container?.firstElementChild?.firstElementChild || container?.firstElementChild;
        if (firstEl && typeof firstEl.scrollIntoView === 'function') {
          firstEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      } catch (e) {}

      const currentHeight = (container && container.scrollHeight) || 0;
      const isAtTop = (container && (container.scrollTop <= 15 || window.scrollY <= 15));

      if (currentHeight > lastScrollHeight) {
        lastScrollHeight = currentHeight;
        unchangedCount = 0;
      } else if (isAtTop) {
        unchangedCount++;
      }

      updateBulkDock();

      if (unchangedCount >= 4 || iterations >= 60) {
        stopAutoScrollChat(true);
      }
    }, 700);
  }

  function stopAutoScrollChat(completed = false) {
    isAutoScrolling = false;
    if (autoScrollTimer) {
      clearInterval(autoScrollTimer);
      autoScrollTimer = null;
    }
    updateBulkDock(completed);
  }

  function triggerManualBulkDownload() {
    const pageUrl = location.href;
    let batch = pendingPageBatches.get(pageUrl);
    let videos = [];

    if (batch && batch.videos.size > 0) {
      videos = Array.from(batch.videos.values());
    } else if (extractedVideosPool.size > 0) {
      videos = Array.from(extractedVideosPool.values());
    }

    const filtered = videos.filter(v => {
      const k = mediaKey(v);
      const u = String(v?.url || '');
      return !cancelledMedia.has(k) && !cancelledMedia.has(u);
    });

    if (!filtered.length) {
      alert('No raw watermark-free videos extracted yet. Auto-scroll the chat to extract past videos first.');
      return;
    }

    pendingPageBatches.delete(pageUrl);

    void chrome.runtime.sendMessage({
      type: 'BRANDAI_RAW_VIDEO_BATCH_DOWNLOAD',
      pageUrl,
      videos: filtered
    });
  }

  function updateBulkDock(completed = false) {
    let dock = document.getElementById(BULK_DOCK_ID);

    // If bulk mode is NOT active, remove the dock and do nothing!
    if (!isBulkModeActive) {
      if (dock) dock.remove();
      return;
    }

    injectScrollStyles();
    scanDomAndChatVideos();

    const count = extractedVideosPool.size;

    if (!dock) {
      dock = appendElement(document.body || document.documentElement, 'div', {
        id: BULK_DOCK_ID
      });
    }

    dock.style.display = 'flex';

    if (isAutoScrolling) {
      dock.innerHTML = `
        <div style="width:32px;height:32px;border-radius:10px;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;box-shadow:0 0 12px rgba(99,102,241,0.5);">
          <span style="animation:brandai-spin 1s linear infinite;display:inline-block;">🔄</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:1px;">
          <span style="color:#93c5fd;font-weight:700;">Scrolling Chat Upwards...</span>
          <span style="color:#94a3b8;font-size:11.5px;">Extracted <b>${count}</b> unwatermarked videos</span>
        </div>
        <button id="brandai-dock-stop-btn" class="brandai-dock-btn" style="background:rgba(239,68,68,0.22);border:1px solid rgba(239,68,68,0.6);color:#fca5a5;margin-left:6px;">
          ⏹️ Stop
        </button>
      `;

      const stopBtn = dock.querySelector('#brandai-dock-stop-btn');
      if (stopBtn) {
        stopBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          stopAutoScrollChat(false);
        });
      }
      return;
    }

    if (completed) {
      dock.innerHTML = `
        <div style="width:32px;height:32px;border-radius:10px;background:linear-gradient(135deg,#10b981,#059669);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;box-shadow:0 0 12px rgba(16,185,129,0.5);">
          ✅
        </div>
        <div style="display:flex;flex-direction:column;gap:1px;">
          <span style="color:#86efac;font-weight:700;">All Chat Videos Loaded!</span>
          <span style="color:#94a3b8;font-size:11.5px;"><b>${count}</b> Raw 1080P videos ready</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-left:6px;">
          <button id="brandai-dock-download-btn" class="brandai-dock-btn brandai-dock-btn-download">
            📥 Download All as ZIP (${count})
          </button>
          <button id="brandai-dock-close-btn" class="brandai-dock-btn-close" title="Turn off Bulk Mode">✕</button>
        </div>
      `;
    } else {
      dock.innerHTML = `
        <div style="width:32px;height:32px;border-radius:10px;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;box-shadow:0 0 12px rgba(99,102,241,0.5);">
          📦
        </div>
        <div style="display:flex;flex-direction:column;gap:1px;">
          <span style="color:#f8fafc;font-weight:700;display:flex;align-items:center;gap:6px;">
            <span>Bulk Download Mode</span>
            <span style="background:rgba(99,102,241,0.25);color:#a5b4fc;padding:1px 6px;border-radius:6px;font-size:10.5px;border:1px solid rgba(99,102,241,0.4);"><b>${count}</b> Extracted</span>
          </span>
          <span style="color:#94a3b8;font-size:11.5px;">Auto-download paused • Scroll to extract past videos</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-left:6px;">
          <button id="brandai-dock-scroll-btn" class="brandai-dock-btn brandai-dock-btn-scroll">
            📜 Auto-Scroll Chat
          </button>
          <button id="brandai-dock-download-btn" class="brandai-dock-btn brandai-dock-btn-download">
            📥 Download ZIP (${count})
          </button>
          <button id="brandai-dock-close-btn" class="brandai-dock-btn-close" title="Turn off Bulk Mode">✕</button>
        </div>
      `;
    }

    const scrollBtn = dock.querySelector('#brandai-dock-scroll-btn');
    if (scrollBtn) {
      scrollBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        startAutoScrollChat();
      });
    }

    const dlBtn = dock.querySelector('#brandai-dock-download-btn');
    if (dlBtn) {
      dlBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        triggerManualBulkDownload();
      });
    }

    const closeBtn = dock.querySelector('#brandai-dock-close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        setBulkMode(false);
      });
    }
  }

  function showIndividualToast(videoName = 'Unwatermarked Video') {
    try {
      const existing = document.getElementById(TOAST_ID);
      if (existing) existing.remove();

      const toast = appendElement(document.body || document.documentElement, 'div', {
        id: TOAST_ID,
        style: [
          'position:fixed',
          'bottom:24px',
          'right:24px',
          'z-index:2147483647',
          'display:flex',
          'align-items:center',
          'gap:12px',
          'padding:12px 18px',
          'border-radius:14px',
          'background:rgba(17,24,39,0.96)',
          'backdrop-filter:blur(12px)',
          'border:1px solid rgba(129,140,248,0.5)',
          'box-shadow:0 14px 40px rgba(0,0,0,0.6)',
          'color:#f8fafc',
          'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
          'font-size:13px',
          'pointer-events:none',
          'transition:all 0.3s ease',
          'user-select:none'
        ].join(';')
      });

      toast.innerHTML = `
        <div style="width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0;box-shadow:0 0 12px rgba(99,102,241,0.5);">
          ⚡
        </div>
        <div style="display:flex;flex-direction:column;gap:2px;">
          <div style="font-weight:700;color:#f8fafc;display:flex;align-items:center;gap:6px;">
            <span>Instant Downloaded!</span>
            <span style="background:rgba(52,211,153,0.18);color:#34d399;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700;border:1px solid rgba(52,211,153,0.35);">1080P Raw</span>
          </div>
          <span style="color:#94a3b8;font-size:11.5px;max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
            ${String(videoName || 'Saved to Downloads/TheBrandAI_Videos').replace(/</g, '&lt;')}
          </span>
        </div>
      `;

      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(12px)';
        setTimeout(() => toast.remove(), 350);
      }, 3500);
    } catch {}
  }

  window.addEventListener('DOLA_VIDEO_EXTRACTED', event => {
    const video = event && event.detail;

    if (!video || video.source !== 'fallback_api' || !video.url) return;

    const url = String(video.url).trim();
    if (!/^https?:\/\//i.test(url)) return;

    const key = String(video.vid || url);
    extractedVideosPool.set(key, video);

    if (isBulkModeActive) {
      updateBulkDock();
      return; // STRICTLY PREVENT AUTO-DOWNLOAD IN BULK MODE!
    }

    if (seenMedia.has(key) || seenMedia.has(url) || cancelledMedia.has(key) || cancelledMedia.has(url)) return;

    seenMedia.add(key);
    seenMedia.add(url);

    queuePageVideo({
      ...video,
      url,
      pageUrl: location.href,
      prompt: video.prompt || video.topicTitle || video.title || ''
    });
  });

  chrome.runtime.onMessage.addListener(message => {
    if (message?.type === 'BRANDAI_START_CHAT_SCROLL') {
      if (!isBulkModeActive) {
        setBulkMode(true);
      }
      startAutoScrollChat();
      return;
    }

    if (message?.type === 'BRANDAI_SET_BULK_MODE') {
      setBulkMode(message.enabled);
      return;
    }

    if (message?.type === 'BRANDAI_RAW_VIDEO_DOWNLOAD_FAILED') {
      releaseVideo(message);
      console.warn('[BrandAI Raw Downloader] Full video could not be verified:', message.error);
      return;
    }

    if (message?.type === 'BRANDAI_RAW_VIDEO_DOWNLOAD_VERIFIED') {
      const cleanName = String(message.filename || 'TheBrandAI_Videos')
        .replace(/^TheBrandAI_Videos\//i, '')
        .replace(/\.mp4$/i, '');
      showIndividualToast(cleanName);
      return;
    }

    if (message?.type === 'BRANDAI_RAW_VIDEO_BATCH_DOWNLOAD_FAILED') {
      const isCancelled = message.cancelled ||
        message.error?.toLowerCase().includes('cancel') ||
        (message.buildId && cancelledBuildIds.has(message.buildId));

      if (isCancelled) {
        for (const video of message.videos || []) {
          const k = mediaKey(video);
          const u = String(video?.url || '');
          if (k) cancelledMedia.add(k);
          if (u) cancelledMedia.add(u);
        }
        return;
      }

      for (const video of message.videos || []) releaseVideo(video);
      updateZipOverlay({ stage: 'error', error: message.error });
      console.warn('[BrandAI Raw Downloader] Video ZIP could not be created:', message.error);
      return;
    }

    if (message?.type === 'BRANDAI_VIDEO_ZIP_PROGRESS') {
      if (message.buildId && cancelledBuildIds.has(message.buildId)) {
        clearTimeout(overlayHideTimer);
        const overlay = document.getElementById(ZIP_OVERLAY_ID);
        if (overlay) overlay.remove();
        const badge = document.getElementById(MINI_BADGE_ID);
        if (badge) badge.remove();
        return;
      }
      if (message.stage === 'cancelled') {
        clearTimeout(overlayHideTimer);
        const overlay = document.getElementById(ZIP_OVERLAY_ID);
        if (overlay) overlay.remove();
        const badge = document.getElementById(MINI_BADGE_ID);
        if (badge) badge.remove();
        return;
      }
      updateZipOverlay(message);
      return;
    }

    if (message?.type === 'BRANDAI_RAW_VIDEO_ZIP_VERIFIED') {
      if (message.buildId && cancelledBuildIds.has(message.buildId)) return;
      updateZipOverlay({ stage: 'complete', percent: 100 });
    }
  });

  setInterval(() => {
    if (isBulkModeActive) {
      updateBulkDock();
    }
  }, 1000);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      injectScrollStyles();
      if (isBulkModeActive) updateBulkDock();
    });
  } else {
    injectScrollStyles();
    if (isBulkModeActive) updateBulkDock();
  }
})();
