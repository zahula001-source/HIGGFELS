# StudioRelay Duplicate Gallery Drop Repair Plan

## Confirmed Evidence

1. `manifest.json` loads only `verified-image-upload-content.js`; no legacy image uploader is active.
2. The verified content script has one guarded document `drop` listener.
3. The native-drop retry path was already removed, so the extension is not deliberately retrying after Dola accepts a trusted File.
4. Each gallery `dragstart` still places both a constructed image `File` and StudioRelay record-token formats into the same `DataTransfer`.
5. Dola renders an exact pair for every single gallery drag, which is consistent with the page consuming more than one representation from that dual payload.

## Repair Contract

1. Give each StudioRelay gallery drag exactly one owner: the token bridge.
2. Clear any browser-populated drag items before writing StudioRelay token formats.
3. Do not place a constructed image `File` in the side-panel `DataTransfer`.
4. Keep the original image Blob in extension IndexedDB; the background returns it only after the trusted token drop reaches Dola.
5. Consume the token drop in the capture phase before Dola can interpret its text/URI forms.
6. Reconstruct the image and perform exactly one attachment mutation: use one linked file input when available, otherwise one composer file-drop event; never chain input, paste, and drop retries for the same job.
7. Add a short per-record drop claim so duplicate browser `drop` events from one physical gesture cannot enqueue a second attachment.
8. Preserve ordinary external/native image drops without programmatically retrying them.
9. Mark Done only after Dola attachment evidence and keep the zero-page-click rule.

## Validation

- Gallery `dragstart` contains no `new File`, `DataTransfer.items.add(File)`, or image Blob URL payload.
- Token drop is stopped before Dola handlers and claimed at most once per gesture.
- Only the token handler calls the attachment pipeline for StudioRelay gallery drags, and a file input receives one change event rather than duplicate input plus change ingestion notifications.
- Native external File drops remain observation-only.
- JavaScript structure, manifest JSON, handler wiring, and no-page-click checks pass.

## Implemented Result

- Gallery drag data is token-only; the side panel no longer constructs or transfers an image File.
- Any pre-existing browser drag File is removed, and the drag is cancelled if a File cannot be cleared safely.
- Repeated token drops for the same record are ignored inside the gesture dedupe window.
- Each image job chooses one attachment method and never falls through to a second method.
- File-input attachment dispatches one change event, eliminating duplicate input-plus-change ingestion.
- Static validation passed for call counts, loaded script wiring, manifest JSON, balanced delimiters, and zero Dola page clicks.

## Runtime Correction

- Dola rejected the token-only reconstructed composer drop, confirmed by the surfaced no-confirmation error and zero rendered attachment.
- The final transport therefore uses one trusted native File, which Dola accepts, plus one opaque extension-only record ID.
- Standard text/plain and text/uri-list representations are not emitted, so Dola receives only one upload-capable representation.
- The native File event is never stopped or retried by StudioRelay; the extension only verifies the resulting Dola preview.
- Previous token-only implementation notes above are historical and are superseded by this runtime correction.
