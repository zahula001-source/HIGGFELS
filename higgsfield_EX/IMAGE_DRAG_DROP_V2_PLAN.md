# StudioRelay Image Drag/Drop V2 Plan

## Confirmed Root Cause

1. The extension loads one verified image receiver; duplicate script injection is not the cause.
2. A constructed `File` in side-panel `DataTransfer` is not reliable across Chrome's extension-page boundary.
3. When Chrome strips that File, the current receiver reconstructs it in the isolated extension world and sends a synthetic textbox drop.
4. Dola does not accept or expose attachment evidence for that isolated-world drop, producing the current `Dola did not confirm the composer drop` error.
5. Previous builds mixed native File, token, sequential input/paste/drop attempts, and duplicate input/change events. Those paths could attach the same record more than once.

## Non-Negotiable Contract

1. One physical gallery drag creates one unique `operationId`.
2. The cross-panel drag carries only an opaque custom operation token—never an image File, Blob URL, `text/plain`, or `text/uri-list` payload.
3. The trusted token drop is consumed before Dola can interpret it.
4. The original Blob is read once from extension IndexedDB through the background worker.
5. File reconstruction and Dola ingestion happen in a dedicated MAIN-world script, using the repo's existing cross-world `CustomEvent` pattern.
6. The MAIN-world script chooses exactly one ingestion method before committing:
   - one high-confidence image file input plus one `change` event; or
   - one composer `drop` event containing one File.
7. Once a method commits, no paste, retry, second event family, or fallback method is allowed.
8. `operationId` is claimed in the isolated receiver and cached in MAIN world, so repeated events return the same result without a second ingestion.
9. A MAIN-world acknowledgment never marks Done by itself. Done requires new attachment evidence in Dola's UI.
10. No Dola page button is clicked programmatically.

## Implementation Steps

1. Convert gallery drag transport to versioned custom metadata `{v, recordId, operationId}` only.
2. Add `image-attachment-main.js` and load it in the existing MAIN-world manifest block.
3. Add bounded request/response events between the isolated receiver and MAIN bridge.
4. Route token uploads and popup upload messages through the MAIN bridge.
5. Add operation-level idempotency lasting through the full verification window.
6. Broaden safe image-input discovery for hidden or portalled Dola inputs while rejecting avatar/profile/video/audio inputs.
7. Dispatch only one ingestion event for the selected method.
8. Verify preview/attachment changes across the active composer and nearby portalled UI.
9. Persist Done only on verified evidence; persist a clear non-retrying error otherwise.
10. Remove or disconnect legacy isolated synthetic ingestion helpers from every active call path.

## Acceptance Checks

- One gallery drag produces zero native File items in the side-panel transfer and one versioned custom token.
- One operation reaches MAIN world at most once.
- MAIN world creates exactly one File and commits exactly one ingestion method.
- File-input mode dispatches one `change`; composer mode dispatches one `drop`.
- No active call path dispatches paste or a dragenter/dragover/drop sequence.
- No active content-script call path clicks a Dola control.
- Done is downstream of visible attachment evidence only.
- Manifest JSON, handler wiring, JavaScript structure, and operation call counts validate cleanly.
## Implemented Result

- StudioRelay build is now 1.7, with the version visible in the side panel.
- Gallery drag transport is token-only and creates one unique operationId per physical drag.
- image-attachment-main.js installs first at document_start in the page MAIN world.
- The isolated receiver claims the operation, reads the original Blob once through the background worker, and sends one bounded MAIN-world request.
- MAIN world reconstructs one File, preselects one method, and performs either one change or one drop.
- A 60-second operation cache exists in both the receiver path and MAIN bridge; duplicate delivery cannot cause a second commit.
- All legacy isolated file-input, multi-event drop, and retry helpers were removed.
- Queue status changes to Done only after new attachment UI evidence appears on Dola.

## Verification Performed

- manifest.json parsed successfully and contains each V2 content script exactly once.
- Token-only transfer, operation claim, one-commit, one-change/one-drop, no-click, no-paste, and no-legacy-helper assertions all passed.
- Raw JavaScript brace and parenthesis structure is balanced in all affected runtime files.
- A local JavaScript runtime is not installed, and the Chrome-control runtime was blocked by the host Windows ACL, so a live automated Dola drag could not be claimed from this environment.

## Required Reload Before Testing

1. Open chrome://extensions.
2. Press Reload on StudioRelay and verify the panel header says Studio version 1.7.
3. Close and reopen the side panel.
4. Hard-refresh the Dola tab once (Ctrl+Shift+R).
5. Drag one gallery card onto the Dola composer and wait for the attachment preview before dragging another.
