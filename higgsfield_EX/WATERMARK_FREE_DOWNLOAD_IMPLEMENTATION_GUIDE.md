# Watermark-Free Video Download — Reusable Implementation Guide

## 1. Feature ka actual working principle

Yeh feature video ka watermark edit ya remove nahi karta. Dola page ek hi generated video ke liye alag media URLs expose kar sakta hai:

- Player/preview URL — ismein watermark ho sakta hai.
- `fallback_api` se milne wala original/raw master MP4 URL — reference extension isi URL ko watermark-free source maanta hai.

Implementation ka main rule hai:

```text
Sirf video.source === "fallback_api" accept karo.
Preview, player, DOM video aur baaki media URLs ko download mat karo.
```

## 2. Final data flow

```text
Dola API response
    ↓
extractor.js (MAIN world)
    ↓ DOLA_VIDEO_EXTRACTED CustomEvent
raw-watermark-free-downloader.js (isolated content-script world)
    ↓ BRANDAI_RAW_VIDEO_DOWNLOAD runtime message
background.js service worker
    ↓ source validation + deduplication
chrome.downloads.download(...)
    ↓
Exactly one *_no_watermark.mp4 file
```

## 3. Is project mein exactly kya change hua

### Change A — Original extractor ko MAIN world mein load kiya

`manifest.json` ke pehle content-script group mein existing `inject.js` se pehle reference extractor add hua:

```json
{
  "matches": [
    "*://*.dola.com/*",
    "*://*.seaart.ai/*",
    "https://dola.com/*",
    "https://www.dola.com/*"
  ],
  "js": [
    "without watermark/extractor.js",
    "inject.js"
  ],
  "run_at": "document_start",
  "world": "MAIN"
}
```

`MAIN` world zaroori hai, kyunki extractor page ke native network objects/API responses ko observe karta hai. Is project mein extractor yahan reuse hua hai:

```text
without watermark/extractor.js
```

Dusre project mein is file ko project ke andar copy karke path update karna hoga, jaise:

```json
"js": ["extractor.js", "inject.js"]
```

### Change B — Isolated-world download bridge add kiya

Nayi file:

```text
raw-watermark-free-downloader.js
```

Isse normal content-script group mein `content.js` ke baad load kiya:

```json
{
  "js": [
    "content.js",
    "raw-watermark-free-downloader.js"
  ],
  "run_at": "document_start"
}
```

Bridge ka complete reusable code:

```js
(function () {
  'use strict';

  // Same script dobara inject ho to duplicate listener na bane.
  if (window.__brandAiRawDownloaderInstalled) return;
  window.__brandAiRawDownloaderInstalled = true;

  const seenMedia = new Set();

  window.addEventListener('DOLA_VIDEO_EXTRACTED', event => {
    const video = event && event.detail;

    // Preview/player URLs reject. Sirf original fallback_api stream accept.
    if (!video || video.source !== 'fallback_api' || !video.url) return;

    const url = String(video.url).trim();
    if (!/^https?:\/\//i.test(url)) return;

    // Ek video ko page level par sirf ek baar forward karo.
    const key = String(video.vid || url);
    if (seenMedia.has(key) || seenMedia.has(url)) return;
    seenMedia.add(key);
    seenMedia.add(url);

    chrome.runtime.sendMessage({
      type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
      video: {
        ...video,
        url,
        pageUrl: location.href,
        prompt: video.prompt || video.topicTitle || video.title || ''
      }
    }).catch(error => {
      // Request fail ho to retry allow karo.
      seenMedia.delete(key);
      seenMedia.delete(url);
      console.warn('[BrandAI Raw Downloader] Download request failed:', error);
    });
  });
})();
```

### Change C — Background mein strict raw-download handler add kiya

`background.js` ke end mein yeh handler add hua:

```js
const brandAiRawDownloadKeys = new Set();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'BRANDAI_RAW_VIDEO_DOWNLOAD') return false;

  const video = message.video || {};
  const url = String(video.url || '').trim();

  // Security/quality gate: non-original stream background level par bhi reject.
  if (video.source !== 'fallback_api' || !/^https?:\/\//i.test(url)) {
    sendResponse({
      ok: false,
      downloaded: false,
      reason: 'Rejected non-original stream'
    });
    return false;
  }

  // Service-worker level deduplication.
  const key = String(video.vid || url);
  if (brandAiRawDownloadKeys.has(key) || brandAiRawDownloadKeys.has(url)) {
    sendResponse({
      ok: true,
      downloaded: false,
      reason: 'Already downloaded'
    });
    return false;
  }

  brandAiRawDownloadKeys.add(key);
  brandAiRawDownloadKeys.add(url);

  const safePrompt = String(
    video.prompt || video.topicTitle || video.title || 'video'
  )
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 60);

  const filename =
    `TheBrandAI_Videos/${safePrompt}_${Date.now()}_no_watermark.mp4`;

  chrome.downloads.download(
    {
      url,
      filename,
      saveAs: false,
      conflictAction: 'uniquify'
    },
    downloadId => {
      const error = chrome.runtime.lastError;

      if (error) {
        // Failed download ko permanently locked na rakho.
        brandAiRawDownloadKeys.delete(key);
        brandAiRawDownloadKeys.delete(url);
        sendResponse({
          ok: false,
          downloaded: false,
          error: error.message
        });
        return;
      }

      sendResponse({
        ok: true,
        downloaded: true,
        downloadId,
        filename
      });
    }
  );

  // Asynchronous sendResponse ke liye channel open rakhta hai.
  return true;
});
```

### Change D — Purana preview/with-watermark download path disable kiya

Main extension ke obfuscated `background.js` mein pehle se ek direct-download listener tha. Woh player/preview URL ko bhi download kar sakta tha. Us listener ke bilkul start mein message-type guard add kiya:

```js
if (
  message &&
  message.type !== 'BRANDAI_RAW_VIDEO_DOWNLOAD'
) return;
```

Current obfuscated file mein variables renamed hain, isliye actual inserted form yeh hai:

```js
if (
  _0x5d09b6 &&
  _0x5d09b6.type !== 'BRANDAI_RAW_VIDEO_DOWNLOAD'
) return;
```

Is guard ka purpose purane download message types ko `chrome.downloads.download()` tak pahunchne se rokna hai. Dusre project mein code readable ho to purane listener ko delete/disable karna zyada clean rahega.

## 4. Duplicate download ko kaise roka gaya

Deduplication do jagah hoti hai:

1. Content-script bridge:

```js
const seenMedia = new Set();
const key = String(video.vid || url);
if (seenMedia.has(key) || seenMedia.has(url)) return;
```

2. Background service worker:

```js
const brandAiRawDownloadKeys = new Set();
if (brandAiRawDownloadKeys.has(key) || brandAiRawDownloadKeys.has(url)) {
  return;
}
```

`vid` primary key hai. Agar `vid` available na ho, complete URL fallback key banta hai. URL bhi separately store hota hai, taaki same video alag event objects se aaye tab bhi duplicate na ho.

## 5. Required manifest permissions

Target extension mein minimum yeh permission honi chahiye:

```json
"permissions": [
  "downloads"
]
```

Aur source/CDN domains `host_permissions` mein accessible hone chahiye. Current project already broad host access use karta hai:

```json
"host_permissions": [
  "*://*.dola.com/*",
  "*://*.byteintl.com/*",
  "*://*.ibytedtos.com/*",
  "<all_urls>"
]
```

Security ke liye `<all_urls>` ki jagah exact required domains prefer kiye ja sakte hain.

## 6. Dusre project mein transplant karne ki checklist

- `extractor.js` ko target project mein copy karo.
- Extractor ko `document_start` aur `world: "MAIN"` mein register karo.
- `raw-watermark-free-downloader.js` add karo.
- Bridge ko normal/isolated content-script group mein register karo.
- Manifest mein `downloads` permission confirm karo.
- Dola aur returned CDN domains ko `host_permissions` mein rakho.
- Background service worker mein `BRANDAI_RAW_VIDEO_DOWNLOAD` handler add karo.
- Existing preview/player/DOM-based auto-download handlers disable karo.
- `video.source === 'fallback_api'` validation dono layers par mat hatao.
- `vid` + URL deduplication dono layers par rakho.
- Extension ko Chrome extensions page se reload karo.
- Fresh generation se test karo; purani already-loaded tab ko bhi reload karo.

## 7. Acceptance test

Ek fresh video generate karne ke baad expected behavior:

- Sirf ek MP4 download ho.
- Filename `_no_watermark.mp4` par end ho.
- File `Downloads/TheBrandAI_Videos/` mein save ho.
- With-watermark/preview copy download na ho.
- Same extraction event repeat hone par second download na ho.
- Non-`fallback_api` message manually bhejne par background usse reject kare.

## 8. Important limitations

- Feature Dola ke current API response structure aur `fallback_api` marker par depend karta hai. Site API badalne par extractor update karna pad sakta hai.
- Page-level `Set` duplicate extraction events ko rokta hai. Service-worker restart ke baad background active Chrome downloads ko URL se check karta hai, aur verification jobs `chrome.storage.local` mein persist hoti hain.
- `force` ya manual bypass jaan-bujhkar add nahi kiya gaya, kyunki requirement sirf original watermark-free stream aur single download ki hai.
- Existing downloader ko active chhod diya gaya to duplicate wapas aa sakta hai. Target project mein har `chrome.downloads.download()` call audit karna zaroori hai.

## 9. Large-file completion verification

Sirf `chrome.downloads.download()` ka callback milna complete download ka proof nahi hai.
Callback ka matlab sirf itna hai ki Chrome ne download accept/start kar diya. Kuch CDN
responses beech mein close hokar 20-25 MB partial MP4 ko bhi `complete` dikha sakte hain.

Current project mein reliable flow `reliable-watermark-free-downloader.js` handle karta hai:

- Download request ko immediately start/acknowledge karta hai; start se pehle koi long polling nahi hoti.
- `chrome.downloads.onChanged` ke terminal state ka wait karta hai.
- Chrome ke `complete` bolne ke baad sirf ek short one-byte Range probe (maximum 5 seconds) se remote total bytes verify karta hai.
- Disk par received bytes ko verified remote bytes se compare karta hai; probe unavailable ho to trusted API/browser size fallback use hota hai.
- Confirmed partial file ko remove karke maximum 3 attempts tak automatically retry karta hai.
- Interrupted Chrome download resumable ho to ek baar resume karta hai.
- Service-worker restart ke liye active verification job `chrome.storage.local` mein rakhta hai.
- Restart ke baad same URL ka active Chrome download milne par duplicate start nahi karta.
- Verification/bookkeeping error par redownload loop start nahi karta.
- Purane long-polling implementation ki stale job metadata startup par clean karta hai.
- Content bridge ko terminal failure batata hai, taaki manual/fresh retry permanently lock na ho.

`background.js` mein purana start-only raw handler disabled hai aur reliable module load hota hai:

```js
importScripts('reliable-watermark-free-downloader.js');
```

Large-file acceptance test mein expected 61 MB aur first-attempt 20 MB simulate karo.
Expected result: partial attempt remove ho, automatic retry chale, aur final 61 MB file verify ho.

## 10. Files involved in current project

```text
manifest.json
background.js
raw-watermark-free-downloader.js
reliable-watermark-free-downloader.js
without watermark/extractor.js
```

Port karte waqt poora `without watermark` extension copy karna required nahi hai. Download feature ke liye extractor, bridge, background handler, manifest wiring aur legacy-download disablement hi relevant pieces hain.
