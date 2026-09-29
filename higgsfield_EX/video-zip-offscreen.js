(function installVideoZipBuilder() {
  'use strict';

  if (globalThis.__brandAiVideoZipBuilderInstalled) return;
  globalThis.__brandAiVideoZipBuilderInstalled = true;

  const BUILD_MESSAGE = 'BRANDAI_BUILD_VIDEO_ZIP';
  const RELEASE_MESSAGE = 'BRANDAI_RELEASE_VIDEO_ZIP';
  const PROGRESS_MESSAGE = 'BRANDAI_VIDEO_ZIP_BUILD_PROGRESS';
  const PAUSE_MESSAGE = 'BRANDAI_PAUSE_VIDEO_ZIP';
  const RESUME_MESSAGE = 'BRANDAI_RESUME_VIDEO_ZIP';
  const CANCEL_MESSAGE = 'BRANDAI_CANCEL_VIDEO_ZIP';
  const MAX_ZIP32_VALUE = 0xffffffff;
  const CONCURRENCY = 10; // 10 parallel video downloads for high-speed batch throughput

  const activeBlobUrls = new Set();
  const activeBuildControllers = new Map();
  const crcTable = createCrcTable();

  function reportProgress(buildId, progress) {
    if (!buildId) return;
    try {
      chrome.runtime.sendMessage({
        type: PROGRESS_MESSAGE,
        buildId,
        ...progress
      }, () => void chrome.runtime.lastError);
    } catch {}
  }

  function createCrcTable() {
    const table = new Uint32Array(256);
    for (let index = 0; index < 256; index += 1) {
      let value = index;
      for (let bit = 0; bit < 8; bit += 1) {
        value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
      }
      table[index] = value >>> 0;
    }
    return table;
  }

  function updateCrc(crc, bytes) {
    let value = crc;
    for (let index = 0; index < bytes.length; index += 1) {
      value = crcTable[(value ^ bytes[index]) & 0xff] ^ (value >>> 8);
    }
    return value >>> 0;
  }

  function dosDateTime(date = new Date()) {
    const year = Math.max(1980, date.getFullYear());
    return {
      time: ((date.getHours() & 0x1f) << 11)
        | ((date.getMinutes() & 0x3f) << 5)
        | ((Math.floor(date.getSeconds() / 2)) & 0x1f),
      date: (((year - 1980) & 0x7f) << 9)
        | (((date.getMonth() + 1) & 0x0f) << 5)
        | (date.getDate() & 0x1f)
    };
  }

  function localHeader(nameBytes, crc, size, timestamp) {
    const buffer = new ArrayBuffer(30);
    const view = new DataView(buffer);
    view.setUint32(0, 0x04034b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 0x0800, true);
    view.setUint16(8, 0, true);
    view.setUint16(10, timestamp.time, true);
    view.setUint16(12, timestamp.date, true);
    view.setUint32(14, crc, true);
    view.setUint32(18, size, true);
    view.setUint32(22, size, true);
    view.setUint16(26, nameBytes.length, true);
    view.setUint16(28, 0, true);
    return new Uint8Array(buffer);
  }

  function centralHeader(nameBytes, crc, size, offset, timestamp) {
    const buffer = new ArrayBuffer(46);
    const view = new DataView(buffer);
    view.setUint32(0, 0x02014b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 20, true);
    view.setUint16(8, 0x0800, true);
    view.setUint16(10, 0, true);
    view.setUint16(12, timestamp.time, true);
    view.setUint16(14, timestamp.date, true);
    view.setUint32(16, crc, true);
    view.setUint32(20, size, true);
    view.setUint32(24, size, true);
    view.setUint16(28, nameBytes.length, true);
    view.setUint16(30, 0, true);
    view.setUint16(32, 0, true);
    view.setUint16(34, 0, true);
    view.setUint16(36, 0, true);
    view.setUint32(38, 0, true);
    view.setUint32(42, offset, true);
    return new Uint8Array(buffer);
  }

  function endOfCentralDirectory(entryCount, centralSize, centralOffset) {
    const buffer = new ArrayBuffer(22);
    const view = new DataView(buffer);
    view.setUint32(0, 0x06054b50, true);
    view.setUint16(4, 0, true);
    view.setUint16(6, 0, true);
    view.setUint16(8, entryCount, true);
    view.setUint16(10, entryCount, true);
    view.setUint32(12, centralSize, true);
    view.setUint32(16, centralOffset, true);
    view.setUint16(20, 0, true);
    return new Uint8Array(buffer);
  }

  const FETCH_TIMEOUT_MS = 30000;

  async function fetchVideo(entry, onProgress, signal) {
    const timeoutController = new AbortController();
    let timeoutId = setTimeout(() => timeoutController.abort(), FETCH_TIMEOUT_MS);

    function onParentAbort() {
      timeoutController.abort();
    }
    if (signal) {
      if (signal.aborted) {
        clearTimeout(timeoutId);
        throw new Error('Download aborted');
      }
      signal.addEventListener('abort', onParentAbort, { once: true });
    }

    try {
      const response = await fetch(entry.url, {
        method: 'GET',
        redirect: 'follow',
        cache: 'no-store',
        credentials: 'omit',
        signal: timeoutController.signal
      });
      if (!response.ok || !response.body) {
        throw new Error(`Video fetch failed (${response.status || 'network error'})`);
      }

      const reader = response.body.getReader();
      const chunks = [];
      let size = 0;
      let crc = 0xffffffff;
      const totalBytes = Number(response.headers.get('content-length'))
        || Number(entry.expectedBytes)
        || 0;
      let lastProgressAt = 0;
      onProgress?.(0, totalBytes);

      while (true) {
        if (signal?.aborted) {
          try { reader.cancel(); } catch (e) {}
          throw new Error('Download aborted');
        }

        // Reset timeout whenever active data is flowing
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => timeoutController.abort(), FETCH_TIMEOUT_MS);

        const { done, value } = await reader.read();
        if (done) break;
        if (!value?.length) continue;
        chunks.push(value);
        size += value.length;
        if (size > MAX_ZIP32_VALUE) {
          throw new Error('A video is too large for a standard ZIP file');
        }
        crc = updateCrc(crc, value);
        const now = Date.now();
        if (now - lastProgressAt >= 150) {
          lastProgressAt = now;
          onProgress?.(size, totalBytes);
        }
      }
      onProgress?.(size, totalBytes || size);

      const headerBytes = Number(response.headers.get('content-length')) || 0;
      if (headerBytes && size < headerBytes) {
        throw new Error(`Incomplete video received (${size} of ${headerBytes} bytes)`);
      }

      return {
        blob: new Blob(chunks, { type: 'video/mp4' }),
        size,
        crc: (crc ^ 0xffffffff) >>> 0
      };
    } finally {
      clearTimeout(timeoutId);
      if (signal) signal.removeEventListener('abort', onParentAbort);
    }
  }

  async function fetchVideoWithRetry(entry, onProgress, signal, maxRetries = 3) {
    let lastError = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      if (signal?.aborted) throw new Error('Download aborted');
      try {
        return await fetchVideo(entry, onProgress, signal);
      } catch (err) {
        lastError = err;
        if (signal?.aborted) throw err;
        console.warn(`[Video Zip Worker] Video #${entry.name} attempt ${attempt + 1} failed:`, err?.message || err);
        if (attempt < maxRetries) {
          await new Promise(r => setTimeout(r, 800 * (attempt + 1)));
        }
      }
    }
    throw lastError;
  }

  async function buildZip(entries, buildId) {
    if (!Array.isArray(entries) || entries.length < 1 || entries.length > 0xffff) {
      throw new Error('Invalid ZIP entry count');
    }

    const encoder = new TextEncoder();
    const timestamp = dosDateTime();
    const total = entries.length;

    const buildState = {
      isPaused: false,
      isCancelled: false,
      abortController: new AbortController(),
      resumeResolve: null
    };
    activeBuildControllers.set(buildId, buildState);

    reportProgress(buildId, {
      stage: 'starting',
      completed: 0,
      total,
      percent: 0,
      isPaused: false
    });

    const results = new Array(total);
    const activeBytes = new Array(total).fill(0);
    const expectedBytes = new Array(total).fill(0);
    let completedCount = 0;
    let nextIndex = 0;
    let maxObservedPercent = 0;

    async function waitIfPaused() {
      while (buildState.isPaused && !buildState.isCancelled) {
        await new Promise(resolve => {
          buildState.resumeResolve = resolve;
        });
      }
      if (buildState.isCancelled) {
        throw new Error('ZIP download cancelled by user');
      }
    }

    function emitProgress() {
      if (buildState.isCancelled) return;
      const sumDownloaded = activeBytes.reduce((a, b) => a + b, 0);

      // Estimate the true total size of ALL videos:
      let sumExpected = 0;
      if (completedCount > 0) {
        let completedBytesSum = 0;
        for (let i = 0; i < total; i++) {
          if (results[i]?.file?.size) {
            completedBytesSum += results[i].file.size;
          }
        }
        const avgPerVideo = completedBytesSum / Math.max(1, completedCount);
        sumExpected = Math.max(sumDownloaded, Math.round(avgPerVideo * total));
      } else {
        const activeSum = expectedBytes.reduce((a, b) => a + b, 0);
        sumExpected = activeSum > 0 ? Math.max(sumDownloaded, Math.round((activeSum / Math.max(1, CONCURRENCY)) * total)) : total * 6 * 1024 * 1024;
      }

      // Smooth percent calculation: completed videos + active streaming fraction
      let activeStreamsBytes = 0;
      for (let i = 0; i < total; i++) {
        if (!results[i] && activeBytes[i] > 0) {
          activeStreamsBytes += activeBytes[i];
        }
      }
      const avgBytes = completedCount > 0 ? (sumDownloaded / completedCount) : (6 * 1024 * 1024);
      const inFlightFraction = Math.min(CONCURRENCY, activeStreamsBytes / Math.max(1, avgBytes)) / total;
      const rawPercent = ((completedCount / total) + inFlightFraction) * 100;

      maxObservedPercent = Math.max(maxObservedPercent, Math.min(99.5, rawPercent));
      const percent = maxObservedPercent;

      reportProgress(buildId, {
        stage: buildState.isPaused ? 'paused' : 'downloading',
        completed: completedCount,
        total,
        currentBytes: sumDownloaded,
        currentTotal: sumExpected,
        percent,
        isPaused: buildState.isPaused,
        concurrency: Math.min(CONCURRENCY, total - completedCount)
      });
    }

    async function worker() {
      while (nextIndex < total) {
        if (buildState.isCancelled) throw new Error('ZIP download cancelled by user');
        await waitIfPaused();

        const index = nextIndex++;
        if (index >= total) break;

        const entry = entries[index];
        const nameBytes = encoder.encode(String(entry.name || `video_${index + 1}.mp4`));
        if (nameBytes.length > 0xffff) throw new Error('ZIP filename is too long');

        try {
          const file = await fetchVideoWithRetry(entry, (curBytes, curTotal) => {
            activeBytes[index] = curBytes;
            if (curTotal > 0) expectedBytes[index] = curTotal;
            emitProgress();
          }, buildState.abortController.signal);

          results[index] = { entry, nameBytes, file };
          completedCount += 1;
          activeBytes[index] = file.size;
          expectedBytes[index] = file.size;
          emitProgress();
        } catch (err) {
          if (buildState.isCancelled) throw new Error('ZIP download cancelled by user');
          console.warn(`[Video Zip Worker] Video #${index + 1} (${entry.name}) skipped after retries:`, err);

          // Graceful fallback so single dead link does NOT freeze or crash the whole 120-video ZIP:
          const failNote = `Video #${index + 1} could not be downloaded (${err?.message || 'network/CDN error'}).\nURL: ${entry.url}\nPrompt: ${entry.prompt || ''}\n`;
          const failBytes = encoder.encode(failNote);
          const failBlob = new Blob([failNote], { type: 'text/plain' });
          const failNameBytes = encoder.encode(String(entry.name || `video_${index + 1}`).replace(/\.mp4$/i, '') + '_error.txt');
          results[index] = {
            entry,
            nameBytes: failNameBytes,
            file: {
              blob: failBlob,
              size: failBlob.size,
              crc: updateCrc(0xffffffff, failBytes) ^ 0xffffffff
            }
          };
          completedCount += 1;
          activeBytes[index] = failBlob.size;
          expectedBytes[index] = failBlob.size;
          emitProgress();
        }
      }
    }

    // Launch up to 10 parallel workers
    const workerPromises = [];
    const actualConcurrency = Math.min(CONCURRENCY, total);
    for (let i = 0; i < actualConcurrency; i++) {
      workerPromises.push(worker());
    }

    await Promise.all(workerPromises);

    if (buildState.isCancelled) throw new Error('ZIP download cancelled by user');

    reportProgress(buildId, {
      stage: 'packing',
      completed: total,
      total,
      percent: 100,
      isPaused: false
    });

    const zipParts = [];
    const centralParts = [];
    let offset = 0;
    let centralSize = 0;

    for (let i = 0; i < total; i++) {
      const item = results[i];
      if (!item) continue;
      const { nameBytes, file } = item;
      const local = localHeader(nameBytes, file.crc, file.size, timestamp);
      const central = centralHeader(nameBytes, file.crc, file.size, offset, timestamp);
      zipParts.push(local, nameBytes, file.blob);
      centralParts.push(central, nameBytes);
      offset += local.length + nameBytes.length + file.size;
      centralSize += central.length + nameBytes.length;
      if (offset > MAX_ZIP32_VALUE || centralSize > MAX_ZIP32_VALUE) {
        throw new Error('Combined videos are too large for a standard ZIP file');
      }
    }

    const centralOffset = offset;
    zipParts.push(...centralParts);
    zipParts.push(endOfCentralDirectory(entries.length, centralSize, centralOffset));
    const blob = new Blob(zipParts, { type: 'application/zip' });
    const blobUrl = URL.createObjectURL(blob);
    activeBlobUrls.add(blobUrl);
    activeBuildControllers.delete(buildId);
    return { blobUrl, size: blob.size };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === PAUSE_MESSAGE) {
      const ctrl = activeBuildControllers.get(String(message.buildId || ''));
      if (ctrl) {
        ctrl.isPaused = true;
        reportProgress(message.buildId, { stage: 'paused', isPaused: true });
        sendResponse({ ok: true, isPaused: true });
      } else {
        sendResponse({ ok: false });
      }
      return false;
    }

    if (message?.type === RESUME_MESSAGE) {
      const ctrl = activeBuildControllers.get(String(message.buildId || ''));
      if (ctrl) {
        ctrl.isPaused = false;
        if (typeof ctrl.resumeResolve === 'function') {
          ctrl.resumeResolve();
          ctrl.resumeResolve = null;
        }
        reportProgress(message.buildId, { stage: 'downloading', isPaused: false });
        sendResponse({ ok: true, isPaused: false });
      } else {
        sendResponse({ ok: false });
      }
      return false;
    }

    if (message?.type === CANCEL_MESSAGE) {
      const ctrl = activeBuildControllers.get(String(message.buildId || ''));
      if (ctrl) {
        ctrl.isCancelled = true;
        ctrl.isPaused = false;
        try { ctrl.abortController.abort(); } catch(e) {}
        if (typeof ctrl.resumeResolve === 'function') {
          ctrl.resumeResolve();
          ctrl.resumeResolve = null;
        }
        activeBuildControllers.delete(String(message.buildId || ''));
        sendResponse({ ok: true, cancelled: true });
      } else {
        sendResponse({ ok: false });
      }
      return false;
    }

    if (message?.type === RELEASE_MESSAGE) {
      const blobUrl = String(message.blobUrl || '');
      if (blobUrl && activeBlobUrls.delete(blobUrl)) URL.revokeObjectURL(blobUrl);
      sendResponse({ ok: true });
      return false;
    }

    if (message?.type !== BUILD_MESSAGE) return false;
    void buildZip(message.entries, message.buildId).then(result => {
      sendResponse({ ok: true, ...result });
    }).catch(error => {
      sendResponse({ ok: false, error: error?.message || String(error) });
    });
    return true;
  });
})();
