# StudioRelay Trusted Native Gallery Drop Repair Plan

## Permission Gate

This file is analysis and planning only. No runtime extension file may be changed until the user explicitly approves implementation.

## Exact Root Cause

1. A File Explorer/Downloads drag works because Chrome creates a real user-agent drag operation containing a real File. The resulting Dola drop is browser-dispatched and trusted.
2. StudioRelay's current gallery drag deliberately removes all File items and places only a custom record token in the cross-panel DataTransfer.
3. The Dola content script consumes that token, reads the Blob from extension IndexedDB, and asks image-attachment-main.js to reconstruct a File.
4. The current error explicitly reports main-composer-drop. That proves no eligible Dola image input was found and the fallback path was used.
5. That fallback creates new DragEvent('drop', ...) and calls target.dispatchEvent(event). Per the DOM Standard, dispatchEvent initializes isTrusted to false.
6. Running the code in Chrome's MAIN world fixes JavaScript-realm compatibility, but it cannot turn a script-created event into a browser/OS-trusted drag.
7. Dola renders no attachment for this untrusted synthetic drop, so the verifier correctly leaves the record queued. The verifier is not the failure; the transport is.

## Why the Earlier Double Upload Happened

The earlier working build gave Dola a native File while a second extension-owned representation/fallback could also reach an ingestion path. The correct repair is not to remove the trusted File. It is to make the trusted File the only upload-capable representation and make StudioRelay observation-only after the drop.

## Repair Contract

1. One physical gallery drag must expose exactly one upload-capable item: one image File.
2. The drag must contain no text/plain, text/uri-list, DownloadURL, Blob URL, custom image token, or synthetic fallback payload.
3. The File must be added during the user's real dragstart event, while the browser drag data store is writable.
4. The gallery tile is the sole draggable element; its child img must not start an independent browser image drag.
5. StudioRelay must never prevent, stop, replay, reconstruct, or redispatch this native File drop.
6. Dola alone owns ingestion. StudioRelay only snapshots the composer before the trusted drop and verifies the resulting preview afterward.
7. Queue bookkeeping must travel out-of-band, not inside DataTransfer:
   - register a short-lived pending operation in the extension background at dragstart;
   - identify it by operationId plus the File fingerprint (name, size, type, lastModified);
   - claim it once for the receiving tab;
   - expire it automatically.
8. A queue record becomes Done only after Dola adds attachment evidence.
9. No retry, file-input assignment, synthetic paste, synthetic drop, or Dola button click is allowed for the gallery-drag path.
10. Existing button/bulk-upload behavior is kept separate and must not be invoked by a gallery drag.

## Planned Implementation

1. Update popup-image-uploads.js:
   - create one File from the stored Blob during trusted dragstart;
   - clear every existing drag item;
   - add exactly one File;
   - assert files.length === 1, one file-kind item, and no text types;
   - register the pending drag fingerprint with the background;
   - cancel visibly if Chrome cannot preserve exactly one File.
2. Ensure gallery preview images use draggable=false so Chrome cannot add an automatic URL/image representation.
3. Update image-overlay-background.js with a bounded pending-native-drag registry and one-time fingerprint claim.
4. Update verified-image-upload-content.js:
   - leave trusted native File dragover/drop events untouched;
   - observe one File and capture pre-drop composer state;
   - verify post-drop Dola evidence;
   - report success/failure against the pending fingerprint;
   - remove the gallery token-to-MAIN upload route from active drag handling.
5. Keep image-attachment-main.js unavailable to gallery drags. It may remain for separately initiated bulk/button uploads.
6. Bump the visible extension build so stale contexts are obvious after reload.

## Acceptance Tests

1. During a StudioRelay gallery drag:
   - dragstart is trusted;
   - DataTransfer contains exactly one File;
   - DataTransfer contains no text/custom/URL upload representation.
2. At Dola's native drop observer:
   - event.isTrusted is true;
   - files.length is exactly 1;
   - StudioRelay does not call preventDefault, stopPropagation, or dispatchEvent.
3. One drag adds exactly one Dola attachment preview.
4. Five repeated single-image drags each add one preview, never zero and never two.
5. Dragging two different gallery images one at a time adds two total previews.
6. File Explorer/Downloads dragging remains unchanged.
7. No gallery drag can call requestMainWorldAttachment or any synthetic input/paste/drop helper.
8. Done remains downstream of visible Dola attachment evidence and is claimed once.

## Standards Evidence

- DOM Standard: https://dom.spec.whatwg.org/ — dispatchEvent sets isTrusted to false.
- HTML Drag and Drop Standard: https://html.spec.whatwg.org/multipage/dnd.html — dragstart is the writable phase of the browser drag data store, whose items may be File or text.
- Chrome content-script documentation: https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts — MAIN world shares the page JavaScript environment, but it does not grant user-agent event trust.
## Implemented Result

- StudioRelay build is now 1.8.
- Each trusted gallery drag constructs one File from the stored Blob and adds exactly one file-kind item to the real drag data store.
- The drag block emits no custom token, text/plain, text/uri-list, DownloadURL, or Blob URL representation.
- Gallery preview img elements remain non-draggable, leaving the gallery card as the sole drag source.
- Each physical gesture receives a unique File lastModified timestamp and operationId, preventing identical queued files from colliding in bookkeeping.
- The background registers that fingerprint out-of-band for 45 seconds and consumes it on the first success or failure report.
- File Explorer drops with no pending StudioRelay fingerprint are ignored by queue bookkeeping.
- The Dola capture listener is observation-only for native File drops: it never prevents, stops, reconstructs, retries, or redispatches the event.
- The old gallery token resolver and token-to-MAIN synthetic upload route were removed. MAIN attachment remains available only for separately initiated button/bulk uploads.
- Done is still downstream of a new Dola attachment preview/control/filename.

## Verification Result

- manifest.json parses successfully and reports version 1.8.
- The native gallery drag block has one File constructor, one DataTransfer file add, zero setData calls, and a one-file/zero-text guard.
- The Dola native observer has zero preventDefault, stopPropagation, dispatchEvent, handleUpload, or requestMainWorldAttachment calls.
- Pending drag registration and one-time claim/delete assertions passed.
- Legacy gallery token action/function assertions passed with zero matches.
- Raw brace and parenthesis counts are balanced in every affected runtime file.
- Live Chrome automation could not connect because the host Windows ACL blocked the browser-control runtime; no live Dola success is claimed from this environment.

## Required Reload and Runtime Test

1. Open chrome://extensions and press Reload on StudioRelay.
2. Close and reopen the side panel.
3. Confirm the header says Studio version 1.8.
4. Hard-refresh Dola once with Ctrl+Shift+R.
5. Drag one gallery image once onto the same Dola area where a Downloads/File Explorer image succeeds.
6. Confirm exactly one Dola preview appears and the gallery record changes to Done.
