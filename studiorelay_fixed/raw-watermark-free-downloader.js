(function () {
  'use strict';

  // Prevent duplicate listeners if this content script is injected again.
  if (window.__brandAiRawDownloaderInstalled) return;
  window.__brandAiRawDownloaderInstalled = true;

  const seenMedia = new Set();

  window.addEventListener('DOLA_VIDEO_EXTRACTED', event => {
    const video = event && event.detail;

    // Preview/player URLs are intentionally rejected. Only the original stream
    // discovered by the fallback API is eligible for automatic download.
    if (!video || video.source !== 'fallback_api' || !video.url) return;

    const url = String(video.url).trim();
    if (!/^https?:\/\//i.test(url)) return;

    const key = String(video.vid || url);
    if (seenMedia.has(key) || seenMedia.has(url)) return;


    seenMedia.add(key);
    seenMedia.add(url);

    try {
        let div = document.createElement('div');
        div.className = 'studio-relay-extracted-video';
        div.setAttribute('data-url', url);
        div.style.display = 'none';
        document.body.appendChild(div);
    } catch(e) {}


    chrome.runtime.sendMessage({
      type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
      video: {
        ...video,
        url,
        pageUrl: location.href,
        prompt: video.prompt || video.topicTitle || video.title || ''
      }
    }).catch(error => {
      // A failed request must remain retryable.
      seenMedia.delete(key);
      seenMedia.delete(url);
      console.warn('[BrandAI Raw Downloader] Download request failed:', error);
    });
  });
})();
