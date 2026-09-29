# StudioRelay Bulk Image Upload Plan

## Goal

Add an Images section beside Prompts and Accounts. Users can bulk-select local images, review them as an ordered queue, and upload either one selected image to the active supported tab or distribute queued images serially across all open supported tabs.

## Existing Architecture Findings

- `popup.html` contains the navigation and Prompts/Accounts views.
- `popup.css` owns the compact dark theme and reusable tab, filter, card, and button styles.
- Core `popup.js` and `content.js` are obfuscated, so the feature must not modify their private state or logic.
- Readable add-on modules already extend the protected core safely (`popup-paragraph-prompts.js`, `popup-bulk-accounts.js`, and `ui-polish.js`).
- The manifest injects isolated-world content scripts on Dola and SeaArt pages and already grants `tabs`, `storage`, and required host access.

## Implementation

1. Add a fifth `Images` navigation button and `view-images` panel.
2. Add a hidden `multiple` image file input, bulk-select/drop zone, All/Queued/Done filters, clear action, and compact thumbnail queue cards.
3. Add `popup-image-uploads.js` as an isolated readable module.
4. Persist image `Blob` records and queue status in extension IndexedDB rather than `chrome.storage.local`, avoiding its small serialized-data quota.
5. Each image card gets an Upload action that opens a themed modal with:
   - `Upload to active tab`: upload only the selected image to the active supported tab.
   - `Upload serially to all tabs`: map queued images to supported tabs in deterministic window/tab order, one image per tab, and process them sequentially.
6. Add `image-upload-content.js` as a separate content script. It will:
   - validate incoming image payloads;
   - locate an image-capable file input;
   - if needed, activate likely image/upload controls and wait briefly for a file input;
   - reconstruct a `File`, assign it using `DataTransfer`, and dispatch native `input`/`change` events;
   - return explicit success/error details to the popup.
7. Add status feedback, busy-state protection, per-image Done state, and safe retry behavior.

## Safety and Compatibility

- Only `http(s)` tabs on `dola.com` or `seaart.ai` are eligible.
- Images are processed in selection/queue order and tabs in window/index order.
- Serial mode uploads at most `min(queued images, eligible tabs)` items; unmatched images remain queued.
- Existing prompt, account, download, social-link, and obfuscated core behavior stays untouched.
- Object URLs are revoked after rendering to avoid memory leaks.
- Message responses and `chrome.runtime.lastError` are handled without marking failed images Done.

## Validation Checklist

- Manifest and HTML parse successfully.
- New JavaScript files pass syntax checks where a JS runtime is available; otherwise use structural/static checks.
- Navigation switches correctly between all five views.
- Bulk selection preserves order and survives side-panel reopen through IndexedDB.
- Individual upload targets only the active supported tab.
- Serial upload maps one queued image per eligible tab in order.
- Successful records become Done; failed/unmatched records remain queued.
- Empty state, filters, clear action, modal cancel, and error messages work.
- New UI matches the existing compact StudioRelay theme.
