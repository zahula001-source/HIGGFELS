/*
 * MV3-safe completion verification for fallback_api watermark-free MP4 files.
 * The download is acknowledged immediately. A single short Range probe runs
 * only after Chrome reports a terminal state, so the service worker is never
 * held in a long polling loop before replying to the content script.
 */
(function installReliableBrandAiDownloader() {
  'use strict';

  if (globalThis.__brandAiReliableDownloaderInstalled) return;
  globalThis.__brandAiReliableDownloaderInstalled = true;

  const MESSAGE_TYPE = 'BRANDAI_RAW_VIDEO_DOWNLOAD';
  const BATCH_MESSAGE_TYPE = 'BRANDAI_RAW_VIDEO_BATCH_DOWNLOAD';
  const ZIP_BUILD_MESSAGE_TYPE = 'BRANDAI_BUILD_VIDEO_ZIP';
  const ZIP_RELEASE_MESSAGE_TYPE = 'BRANDAI_RELEASE_VIDEO_ZIP';
  const ZIP_BUILD_PROGRESS_MESSAGE_TYPE = 'BRANDAI_VIDEO_ZIP_BUILD_PROGRESS';
  const ZIP_TAB_PROGRESS_MESSAGE_TYPE = 'BRANDAI_VIDEO_ZIP_PROGRESS';
  const JOB_PREFIX = '__brandAiRawDownloadJobV2_';
  const ZIP_JOB_PREFIX = '__brandAiVideoZipJob_';
  const LEGACY_JOB_PREFIX = '__brandAiRawDownloadJob_';
  const INDIVIDUAL_DOWNLOAD_LIMIT = 5;
  const MAX_ATTEMPTS = 3;
  const SIZE_TOLERANCE_BYTES = 256 * 1024;
  const SIZE_TOLERANCE_RATIO = 0.995;
  const PROBE_TIMEOUT_MS = 5000;
  const JOB_MAX_AGE_MS = 24 * 60 * 60 * 1000;
  const activeJobs = new Map();
  const activeZipJobs = new Map();
  const activeZipBuilds = new Map();
  const lockedKeys = new Set();
  const cancelledBuildIds = new Set();
  const cancelledKeys = new Set();
  const handlingDownloads = new Set();
  const handlingZipDownloads = new Set();
  let creatingOffscreenDocument = null;

  function positiveInteger(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0;
  }

  function expectedBytesFromVideo(video) {
    return Math.max(...[
      video?.expectedBytes,
      video?.fileSize,
      video?.file_size,
      video?.filesize,
      video?.contentLength,
      video?.content_length,
      video?.videoSize,
      video?.video_size
    ].map(positiveInteger));
  }

  function isOriginalVideo(video) {
    const url = String(video?.url || '').trim();
    return video?.source === 'fallback_api' && /^https?:\/\//i.test(url);
  }

  function videoIdentity(video) {
    return String(video?.vid || video?.url || '');
  }

  function compareVideoQuality(left, right) {
    const leftPixels = positiveInteger(left?.width) * positiveInteger(left?.height);
    const rightPixels = positiveInteger(right?.width) * positiveInteger(right?.height);
    if (leftPixels !== rightPixels) return leftPixels - rightPixels;

    const leftBitrate = Math.max(positiveInteger(left?.bitrate), positiveInteger(left?.real_bitrate));
    const rightBitrate = Math.max(positiveInteger(right?.bitrate), positiveInteger(right?.real_bitrate));
    if (leftBitrate !== rightBitrate) return leftBitrate - rightBitrate;
    return expectedBytesFromVideo(left) - expectedBytesFromVideo(right);
  }

  function highestQualityVideos(videos) {
    const bestByIdentity = new Map();
    for (const candidate of videos || []) {
      if (!isOriginalVideo(candidate)) continue;
      const video = { ...candidate, url: String(candidate.url).trim() };
      const identity = videoIdentity(video);
      const current = bestByIdentity.get(identity);
      if (!current || compareVideoQuality(video, current) > 0) {
        bestByIdentity.set(identity, video);
      }
    }
    return Array.from(bestByIdentity.values());
  }

  function safeVideoBaseName(video) {
    const rawPrompt = String(video?.prompt || video?.topicTitle || video?.title || '').trim();
    const strippedPrompt = rawPrompt
      .replace(/^(?:generated\s+videos?|generated|create\s+videos?|prompt|video)\s*[:\uFF1A\-\u2013\u2014]\s*/i, '')
      .trim();
    const cleanPrompt = (strippedPrompt || rawPrompt)
      .replace(/[\r\n\t]+/g, ' ')
      .replace(/[<>:"/\\|?*\x00-\x1F]/g, '')
      .trim();
    return (cleanPrompt || 'video')
      .slice(0, 60)
      .trim()
      .replace(/\s+/g, '_')
      .replace(/^_+|_+$/g, '') || 'video';
  }

  function videoFilename(video) {
    return `TheBrandAI_Videos/${safeVideoBaseName(video)}.mp4`;
  }

  function zipFilename(videoCount) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    return `TheBrandAI_Videos/TheBrandAI_${videoCount}_Videos_${timestamp}.zip`;
  }

  function totalBytesFromHeaders(response) {
    const contentRange = response.headers.get('content-range') || '';
    const rangeMatch = contentRange.match(/\/\s*(\d+)\s*$/);
    if (rangeMatch) return positiveInteger(rangeMatch[1]);

    // A server that ignores Range and returns 200 exposes the full length.
    // For a 206 response without Content-Range, Content-Length is only the
    // requested chunk and must not be treated as the full object size.
    return response.status === 200
      ? positiveInteger(response.headers.get('content-length'))
      : 0;
  }

  async function probeRemoteSize(url) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: { Range: 'bytes=0-0', 'Cache-Control': 'no-cache' },
        redirect: 'follow',
        cache: 'no-store',
        credentials: 'include',
        signal: controller.signal
      });
      const size = response.ok ? totalBytesFromHeaders(response) : 0;
      try {
        await response.body?.cancel();
      } catch {}
      return size;
    } catch {
      return 0;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  const jobKey = downloadId => `${JOB_PREFIX}${downloadId}`;
  const zipJobKey = downloadId => `${ZIP_JOB_PREFIX}${downloadId}`;

  function storageGet(key) {
    return new Promise(resolve => chrome.storage.local.get(key, result => {
      void chrome.runtime.lastError;
      resolve(result?.[key] || null);
    }));
  }

  function storageSet(key, value) {
    return new Promise(resolve => chrome.storage.local.set({ [key]: value }, () => {
      void chrome.runtime.lastError;
      resolve();
    }));
  }

  function storageRemove(key) {
    return new Promise(resolve => chrome.storage.local.remove(key, () => {
      void chrome.runtime.lastError;
      resolve();
    }));
  }

  function chromeDownload(options) {
    return new Promise((resolve, reject) => chrome.downloads.download(options, id => {
      const error = chrome.runtime.lastError;
      if (error || !Number.isInteger(id)) reject(new Error(error?.message || 'Download did not start'));
      else resolve(id);
    }));
  }

  function runtimeMessage(message) {
    return new Promise((resolve, reject) => chrome.runtime.sendMessage(message, response => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve(response);
    }));
  }

  async function hasOffscreenDocument() {
    if (typeof chrome.offscreen?.hasDocument === 'function') {
      return chrome.offscreen.hasDocument();
    }
    if (typeof chrome.runtime.getContexts === 'function') {
      const contexts = await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT'],
        documentUrls: [chrome.runtime.getURL('video-zip-offscreen.html')]
      });
      return contexts.length > 0;
    }
    return false;
  }

  async function ensureOffscreenDocument() {
    if (!chrome.offscreen?.createDocument) {
      throw new Error('This Chrome version does not support background ZIP creation');
    }
    if (await hasOffscreenDocument()) return;
    if (!creatingOffscreenDocument) {
      creatingOffscreenDocument = chrome.offscreen.createDocument({
        url: 'video-zip-offscreen.html',
        reasons: ['BLOBS'],
        justification: 'Build a ZIP from more than five maximum-quality videos found on one page'
      }).finally(() => {
        creatingOffscreenDocument = null;
      });
    }
    await creatingOffscreenDocument;
  }

  async function releaseZipBlob(blobUrl) {
    if (!blobUrl) return;
    try {
      await runtimeMessage({ type: ZIP_RELEASE_MESSAGE_TYPE, blobUrl });
    } catch {}
  }

  function findDownload(id) {
    return new Promise(resolve => chrome.downloads.search({ id }, items => {
      void chrome.runtime.lastError;
      resolve(items?.[0] || null);
    }));
  }

  function hasInProgressDownload(url) {
    return new Promise(resolve => chrome.downloads.search({ state: 'in_progress' }, items => {
      void chrome.runtime.lastError;
      resolve((items || []).some(item => item.url === url || item.finalUrl === url));
    }));
  }

  function removeDownloadFile(id) {
    return new Promise(resolve => chrome.downloads.removeFile(id, () => {
      void chrome.runtime.lastError;
      chrome.downloads.erase({ id }, () => {
        void chrome.runtime.lastError;
        resolve();
      });
    }));
  }

  function resumeDownload(id) {
    return new Promise((resolve, reject) => chrome.downloads.resume(id, () => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve();
    }));
  }

  async function saveJob(id, job) {
    activeJobs.set(id, job);
    await storageSet(jobKey(id), job);
  }

  async function deleteJob(id) {
    activeJobs.delete(id);
    await storageRemove(jobKey(id));
  }

  async function loadJob(id) {
    return activeJobs.get(id) || storageGet(jobKey(id));
  }

  async function saveZipJob(id, job) {
    activeZipJobs.set(id, job);
    await storageSet(zipJobKey(id), job);
  }

  async function deleteZipJob(id) {
    activeZipJobs.delete(id);
    await storageRemove(zipJobKey(id));
  }

  async function loadZipJob(id) {
    const job = activeZipJobs.get(id) || await storageGet(zipJobKey(id));
    if (job) activeZipJobs.set(id, job);
    return job;
  }

  function releaseLock(job) {
    if (!job) return;
    lockedKeys.delete(job.key);
    lockedKeys.delete(job.url);
  }

  function releaseVideoLocks(videos) {
    for (const video of videos || []) releaseLock(video);
  }

  function notifyTab(job, message) {
    if (!Number.isInteger(job?.tabId)) return;
    try {
      chrome.tabs.sendMessage(job.tabId, message, () => void chrome.runtime.lastError);
    } catch {}
  }

  function isIncomplete(actualBytes, expectedBytes) {
    if (!actualBytes || !expectedBytes || actualBytes >= expectedBytes) return false;
    return expectedBytes - actualBytes > SIZE_TOLERANCE_BYTES
      && actualBytes < expectedBytes * SIZE_TOLERANCE_RATIO;
  }

  async function startAttempt(job) {
    const id = await chromeDownload({
      url: job.url,
      filename: job.filename,
      saveAs: false,
      conflictAction: 'uniquify'
    });
    job.downloadId = id;
    job.attemptStartedAt = Date.now();
    await saveJob(id, job);
    console.info(`[BrandAI Raw Downloader] Attempt ${job.attempt}/${MAX_ATTEMPTS} started`, {
      id,
      expectedBytes: job.expectedBytes
    });
    return id;
  }

  function individualJob(video, tabId) {
    const url = String(video.url).trim();
    return {
      key: videoIdentity(video),
      url,
      filename: videoFilename(video),
      expectedBytes: expectedBytesFromVideo(video),
      attempt: 1,
      resumeCount: 0,
      tabId,
      createdAt: Date.now()
    };
  }

  async function startIndividualVideo(video, tabId) {
    if (!isOriginalVideo(video)) {
      return { ok: false, downloaded: false, reason: 'Rejected non-original stream' };
    }

    const job = individualJob(video, tabId);
    if (lockedKeys.has(job.key) || lockedKeys.has(job.url)) {
      return { ok: true, downloaded: false, reason: 'Download already started' };
    }
    lockedKeys.add(job.key);
    lockedKeys.add(job.url);

    try {
      if (await hasInProgressDownload(job.url)) {
        releaseLock(job);
        return { ok: true, downloaded: false, reason: 'Download already in progress' };
      }

      const downloadId = await startAttempt(job);
      return {
        ok: true,
        downloaded: true,
        state: 'in_progress',
        downloadId,
        filename: job.filename,
        expectedBytes: job.expectedBytes
      };
    } catch (error) {
      releaseLock(job);
      return { ok: false, downloaded: false, error: error?.message || String(error) };
    }
  }

  function zipEntries(videos) {
    const digits = Math.max(2, String(videos.length).length);
    return videos.map((video, index) => ({
      url: video.url,
      name: `${String(index + 1).padStart(digits, '0')}_${safeVideoBaseName(video)}.mp4`,
      expectedBytes: expectedBytesFromVideo(video)
    }));
  }

  async function startVideoZip(videos, tabId, pageUrl) {
    const unhandledVideos = (videos || []).filter(v => {
      const k = videoIdentity(v);
      const u = String(v.url).trim();
      return !lockedKeys.has(k) && !lockedKeys.has(u);
    });

    if (!unhandledVideos.length) {
      return { ok: true, downloaded: false, mode: 'zip', reason: 'All videos already downloaded' };
    }

    if (unhandledVideos.length <= INDIVIDUAL_DOWNLOAD_LIMIT) {
      const results = await Promise.all(
        unhandledVideos.map(video => startIndividualVideo(video, tabId))
      );
      const accepted = results.filter(r => r.ok);
      return {
        ok: accepted.length > 0,
        downloaded: results.some(r => r.downloaded),
        mode: 'individual',
        videoCount: unhandledVideos.length,
        downloads: accepted
      };
    }

    const lockRecords = unhandledVideos.map(video => ({
      key: videoIdentity(video),
      url: String(video.url).trim()
    }));

    for (const video of lockRecords) {
      lockedKeys.add(video.key);
      lockedKeys.add(video.url);
    }

    let blobUrl = '';
    const buildId = `video-zip-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const buildJob = { tabId, videoCount: unhandledVideos.length };
    activeZipBuilds.set(buildId, buildJob);
    notifyTab(buildJob, {
      type: ZIP_TAB_PROGRESS_MESSAGE_TYPE,
      stage: 'starting',
      completed: 0,
      total: unhandledVideos.length,
      percent: 0
    });
    try {
      await ensureOffscreenDocument();
      const zipResult = await runtimeMessage({
        type: ZIP_BUILD_MESSAGE_TYPE,
        buildId,
        entries: zipEntries(unhandledVideos)
      });
      if (cancelledBuildIds.has(buildId)) {
        throw new Error('ZIP download cancelled by user');
      }
      if (!zipResult?.ok || !zipResult.blobUrl) {
        throw new Error(zipResult?.error || 'ZIP creation failed');
      }
      blobUrl = zipResult.blobUrl;
      if (cancelledBuildIds.has(buildId)) {
        await releaseZipBlob(blobUrl);
        throw new Error('ZIP download cancelled by user');
      }
      notifyTab(buildJob, {
        type: ZIP_TAB_PROGRESS_MESSAGE_TYPE,
        stage: 'saving',
        buildId,
        completed: videos.length,
        total: videos.length,
        percent: 100
      });

      const filename = zipFilename(videos.length);
      const downloadId = await chromeDownload({
        url: blobUrl,
        filename,
        saveAs: false,
        conflictAction: 'uniquify'
      });
      const job = {
        buildId,
        downloadId,
        blobUrl,
        filename,
        videos: lockRecords,
        videoCount: videos.length,
        tabId,
        pageUrl: String(pageUrl || ''),
        resumeCount: 0,
        createdAt: Date.now()
      };
      if (cancelledBuildIds.has(buildId)) {
        try {
          await new Promise(r => chrome.downloads.cancel(downloadId, () => {
            void chrome.runtime.lastError;
            r();
          }));
          await removeDownloadFile(downloadId);
          await releaseZipBlob(blobUrl);
        } catch {}
        throw new Error('ZIP download cancelled by user');
      }
      await saveZipJob(downloadId, job);
      const currentItem = await findDownload(downloadId);
      if (currentItem?.state === 'complete' || currentItem?.state === 'interrupted') {
        void handleTerminalZipDownload(downloadId, currentItem.state);
      }
      console.info('[BrandAI Raw Downloader] Video ZIP started', {
        downloadId,
        videoCount: videos.length,
        filename
      });
      return {
        ok: true,
        downloaded: true,
        mode: 'zip',
        state: 'in_progress',
        downloadId,
        filename,
        videoCount: videos.length,
        zipBytes: positiveInteger(zipResult.size)
      };
    } catch (error) {
      const isCancelled = cancelledBuildIds.has(buildId) ||
        error?.message?.toLowerCase().includes('cancel') ||
        error?.message?.toLowerCase().includes('abort');

      if (!isCancelled) {
        releaseVideoLocks(lockRecords);
      } else {
        for (const video of lockRecords) {
          cancelledKeys.add(video.key);
          cancelledKeys.add(video.url);
        }
      }
      await releaseZipBlob(blobUrl);
      return {
        ok: false,
        downloaded: false,
        cancelled: isCancelled,
        mode: 'zip',
        error: error?.message || String(error)
      };
    } finally {
      activeZipBuilds.delete(buildId);
    }
  }

  async function failJob(id, job, reason) {
    await deleteJob(id);
    releaseLock(job);
    console.error('[BrandAI Raw Downloader] Full MP4 could not be verified:', reason);
    notifyTab(job, {
      type: 'BRANDAI_RAW_VIDEO_DOWNLOAD_FAILED',
      key: job.key,
      url: job.url,
      error: reason
    });
  }

  async function retryJob(id, job, reason) {
    await removeDownloadFile(id);
    await deleteJob(id);

    if (job.attempt >= MAX_ATTEMPTS) {
      await failJob(id, job, reason);
      return;
    }

    job.attempt += 1;
    job.resumeCount = 0;
    try {
      await startAttempt(job);
    } catch (error) {
      await failJob(id, job, error?.message || String(error));
    }
  }

  async function completeJob(id, job, actualBytes, expectedBytes) {
    await deleteJob(id);
    releaseLock(job);
    console.info('[BrandAI Raw Downloader] Full MP4 verified:', {
      id,
      actualBytes,
      expectedBytes
    });
    notifyTab(job, {
      type: 'BRANDAI_RAW_VIDEO_DOWNLOAD_VERIFIED',
      key: job.key,
      url: job.url,
      downloadId: id,
      actualBytes,
      expectedBytes,
      filename: job.filename
    });
  }

  async function handleTerminalDownload(id, state) {
    if (handlingDownloads.has(id)) return;
    handlingDownloads.add(id);
    let job = null;
    try {
      job = await loadJob(id);
      if (!job) return;

      const item = await findDownload(id);
      if (!item) {
        await failJob(id, job, 'Download record disappeared before verification');
        return;
      }

      if (state === 'interrupted') {
        if (item.canResume && positiveInteger(job.resumeCount) < 1) {
          job.resumeCount = positiveInteger(job.resumeCount) + 1;
          await saveJob(id, job);
          try {
            await resumeDownload(id);
            return;
          } catch {}
        }
        await retryJob(id, job, item.error || 'Chrome reported an interrupted download');
        return;
      }

      const actualBytes = Math.max(
        positiveInteger(item.fileSize),
        positiveInteger(item.bytesReceived)
      );
      const remoteBytes = await probeRemoteSize(job.url);
      const browserBytes = positiveInteger(item.totalBytes);

      // A fresh remote Range result is authoritative when available. The API
      // hint is only a fallback, preventing a bad metadata value from causing
      // repeated downloads when the CDN reports its real object length.
      const expectedBytes = remoteBytes
        ? Math.max(remoteBytes, browserBytes)
        : Math.max(browserBytes, positiveInteger(job.expectedBytes));

      if (isIncomplete(actualBytes, expectedBytes)) {
        const reason = `Received ${actualBytes} of ${expectedBytes} bytes`;
        job.expectedBytes = expectedBytes;
        console.warn('[BrandAI Raw Downloader] Partial MP4 detected; retrying:', reason);
        await retryJob(id, job, reason);
        return;
      }

      await completeJob(id, job, actualBytes, expectedBytes);
    } catch (error) {
      // Verification/bookkeeping errors must never create a redownload loop.
      console.error('[BrandAI Raw Downloader] Verification stopped safely:', error);
      if (job) {
        await deleteJob(id);
        releaseLock(job);
      }
    } finally {
      handlingDownloads.delete(id);
    }
  }

  async function finishZipJob(id, job, error = '') {
    await deleteZipJob(id);
    releaseVideoLocks(job.videos);
    await releaseZipBlob(job.blobUrl);

    if (error) {
      console.error('[BrandAI Raw Downloader] Video ZIP download failed:', error);
      notifyTab(job, {
        type: 'BRANDAI_RAW_VIDEO_BATCH_DOWNLOAD_FAILED',
        videos: job.videos,
        error
      });
      return;
    }

    console.info('[BrandAI Raw Downloader] Video ZIP completed:', {
      id,
      videoCount: job.videoCount,
      filename: job.filename
    });
    notifyTab(job, {
      type: 'BRANDAI_RAW_VIDEO_ZIP_VERIFIED',
      downloadId: id,
      videoCount: job.videoCount,
      filename: job.filename
    });
  }

  async function handleTerminalZipDownload(id, state) {
    if (handlingZipDownloads.has(id)) return;
    handlingZipDownloads.add(id);
    let job = null;
    try {
      job = await loadZipJob(id);
      if (!job) return;

      const item = await findDownload(id);
      if (!item) {
        await finishZipJob(id, job, 'ZIP download record disappeared');
        return;
      }

      if (state === 'interrupted') {
        if (item.canResume && positiveInteger(job.resumeCount) < 1) {
          job.resumeCount = positiveInteger(job.resumeCount) + 1;
          await saveZipJob(id, job);
          try {
            await resumeDownload(id);
            return;
          } catch {}
        }
        await finishZipJob(id, job, item.error || 'Chrome reported an interrupted ZIP download');
        return;
      }

      await finishZipJob(id, job);
    } catch (error) {
      console.error('[BrandAI Raw Downloader] ZIP bookkeeping stopped safely:', error);
      if (job) {
        await deleteZipJob(id);
        releaseVideoLocks(job.videos);
        await releaseZipBlob(job.blobUrl);
      }
    } finally {
      handlingZipDownloads.delete(id);
    }
  }

  chrome.downloads.onChanged.addListener(delta => {
    const state = delta?.state?.current;
    if (state === 'complete' || state === 'interrupted') {
      void handleTerminalDownload(delta.id, state);
      void handleTerminalZipDownload(delta.id, state);
    }
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || message.type !== ZIP_BUILD_PROGRESS_MESSAGE_TYPE) return false;

    const buildJob = activeZipBuilds.get(String(message.buildId || ''));
    if (buildJob) {
      notifyTab(buildJob, {
        type: ZIP_TAB_PROGRESS_MESSAGE_TYPE,
        stage: message.stage,
        completed: positiveInteger(message.completed),
        total: positiveInteger(message.total) || buildJob.videoCount,
        currentIndex: positiveInteger(message.currentIndex),
        filename: String(message.filename || ''),
        currentBytes: positiveInteger(message.currentBytes),
        currentTotal: positiveInteger(message.currentTotal),
        concurrency: positiveInteger(message.concurrency) || 10,
        isPaused: Boolean(message.isPaused),
        percent: Math.min(100, Math.max(0, Number(message.percent) || 0))
      });
    }
    sendResponse({ ok: Boolean(buildJob) });
    return false;
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || message.type !== MESSAGE_TYPE) return false;

    const video = message.video || {};
    const url = String(video.url || '').trim();
    if (video.source !== 'fallback_api' || !/^https?:\/\//i.test(url)) {
      sendResponse({ ok: false, downloaded: false, reason: 'Rejected non-original stream' });
      return false;
    }

    const key = String(video.vid || url);
    if (lockedKeys.has(key) || lockedKeys.has(url)) {
      sendResponse({ ok: true, downloaded: false, reason: 'Download already started' });
      return false;
    }

    lockedKeys.add(key);
    lockedKeys.add(url);

    void (async () => {
      try {
        if (await hasInProgressDownload(url)) {
          releaseLock({ key, url });
          sendResponse({ ok: true, downloaded: false, reason: 'Download already in progress' });
          return;
        }

        const rawPrompt = String(video.prompt || video.topicTitle || video.title || '').trim();
        const strippedPrompt = rawPrompt.replace(/^(?:generated\s+videos?|generated|create\s+videos?|prompt|video)\s*[:：\-–—]\s*/i, '').trim();
        const cleanPrompt = (strippedPrompt || rawPrompt).replace(/[\r\n\t]+/g, ' ').replace(/[<>:"/\\|?*\x00-\x1F]/g, '').trim();
        const promptSlice = (cleanPrompt || 'video').slice(0, 38).trim();
        const safeName = promptSlice.replace(/\s+/g, '_').replace(/^_+|_+$/g, '') || 'video';
        const job = {
          key,
          url,
          filename: `TheBrandAI_Videos/${safeName}.mp4`,
          expectedBytes: expectedBytesFromVideo(video),
          attempt: 1,
          resumeCount: 0,
          tabId: sender?.tab?.id,
          createdAt: Date.now()
        };
        const downloadId = await startAttempt(job);
        sendResponse({
          ok: true,
          downloaded: true,
          state: 'in_progress',
          downloadId,
          filename: job.filename,
          expectedBytes: job.expectedBytes
        });
      } catch (error) {
        lockedKeys.delete(key);
        lockedKeys.delete(url);
        sendResponse({ ok: false, downloaded: false, error: error?.message || String(error) });
      }
    })();
    return true;
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || message.type !== BATCH_MESSAGE_TYPE) return false;

    void (async () => {
      const videos = highestQualityVideos(message.videos);
      if (!videos.length) {
        sendResponse({ ok: false, downloaded: false, reason: 'No original videos were found' });
        return;
      }

      if (videos.length <= INDIVIDUAL_DOWNLOAD_LIMIT) {
        const results = await Promise.all(
          videos.map(video => startIndividualVideo(video, sender?.tab?.id))
        );
        const failed = results.flatMap((result, index) => result.ok ? [] : [{
          key: videoIdentity(videos[index]),
          url: videos[index].url,
          error: result.error || result.reason || 'Download did not start'
        }]);
        const accepted = results.filter(result => result.ok);
        sendResponse({
          ok: accepted.length > 0,
          downloaded: results.some(result => result.downloaded),
          mode: 'individual',
          videoCount: videos.length,
          downloads: accepted,
          failed
        });
        return;
      }

      const result = await startVideoZip(videos, sender?.tab?.id, message.pageUrl);
      if (!result.ok && !result.cancelled && !result.error?.toLowerCase().includes('cancel')) {
        notifyTab({ tabId: sender?.tab?.id }, {
          type: 'BRANDAI_RAW_VIDEO_BATCH_DOWNLOAD_FAILED',
          videos: videos.map(video => ({ key: videoIdentity(video), url: video.url })),
          error: result.error || result.reason
        });
      }
      sendResponse(result);
    })().catch(error => {
      sendResponse({ ok: false, downloaded: false, error: error?.message || String(error) });
    });
    return true;
  });

  // Remove metadata from the previous long-polling implementation and stale
  // V2 jobs. This does not remove any user download or browser history entry.
  chrome.storage.local.get(null, stored => {
    void chrome.runtime.lastError;
    const now = Date.now();
    const keysToRemove = Object.keys(stored || {}).filter(key => {
      if (key.startsWith(LEGACY_JOB_PREFIX) && !key.startsWith(JOB_PREFIX)) return true;
      if (!key.startsWith(JOB_PREFIX) && !key.startsWith(ZIP_JOB_PREFIX)) return false;
      const createdAt = positiveInteger(stored[key]?.createdAt);
      return !createdAt || now - createdAt > JOB_MAX_AGE_MS;
    });
    if (keysToRemove.length) {
      chrome.storage.local.remove(keysToRemove, () => void chrome.runtime.lastError);
    }
  });
})();


  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message) return false;
    if (message.type === 'BRANDAI_PAUSE_VIDEO_ZIP' || message.type === 'BRANDAI_RESUME_VIDEO_ZIP' || message.type === 'BRANDAI_CANCEL_VIDEO_ZIP') {
      void (async () => {
        try {
          await ensureOffscreenDocument();
          const buildId = String(message.buildId || '');
          if (message.type === 'BRANDAI_CANCEL_VIDEO_ZIP') {
            if (buildId) cancelledBuildIds.add(buildId);
            const buildJob = activeZipBuilds.get(buildId);
            if (buildJob) {
              notifyTab(buildJob, { type: ZIP_TAB_PROGRESS_MESSAGE_TYPE, stage: 'cancelled', buildId, isPaused: false });
              activeZipBuilds.delete(buildId);
            }
            // Check any active zip jobs in downloads and cancel them
            for (const [downloadId, job] of Array.from(activeZipJobs.entries())) {
              if (job.buildId === buildId || !buildId) {
                try {
                  await new Promise(r => chrome.downloads.cancel(downloadId, () => {
                    void chrome.runtime.lastError;
                    r();
                  }));
                  await removeDownloadFile(downloadId);
                  await deleteZipJob(downloadId);
                  await releaseZipBlob(job.blobUrl);
                } catch {}
              }
            }
          }
          const res = await runtimeMessage(message);
          sendResponse(res || { ok: true, cancelled: message.type === 'BRANDAI_CANCEL_VIDEO_ZIP' });
        } catch (e) {
          sendResponse({ ok: false, error: e?.message });
        }
      })();
      return true;
    }
    return false;
  });
