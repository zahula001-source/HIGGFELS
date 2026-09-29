# StudioRelay Image and Page Overlay Correction Plan

## Requested Outcomes

1. Uploading an image must never programmatically click `Create Images`, `Create Video`, `Generate`, the composer plus button, or any other page control.
2. The Dola page must show an Images overlay aligned with the existing Prompts overlay pattern.
3. The Dola page must show a Hit Video overlay. Clicking it must arm the existing interactive click-sync mode; it must not automatically click a Create/Generate button.

## Analysis Findings

- The unintended click originates in `image-upload-content.js`: when no file input is found, `revealImageInput()` searches page controls and calls `control.click()`.
- Direct image injection already works through `DataTransfer`, the native `HTMLInputElement.files` setter, and bubbling `input`/`change` events.
- Existing click-sync activation is implemented in `site-polish.js` as `handleArmClickSync()` and relayed across Dola tabs through `broadcast_mirrored_click` in `background.js`.
- The existing Prompts overlay is created by the protected runtime. New readable overlay code should detect its visible pill and position the new controls beneath it without modifying the protected runtime.
- Image blobs belong in IndexedDB. Only small queue summary data should be mirrored to `chrome.storage.local` for content-script overlay display.

## Implementation Plan

### 1. Strict no-click image injection

- Remove the entire page-control discovery/click fallback from `image-upload-content.js`.
- Locate an already-existing image-capable `input[type=file]` only.
- Assign the image through `DataTransfer` and dispatch native `input` and `change` events.
- If no eligible input exists, return a clear error asking the user to expose the image input manually; do not click anything.
- Add a static validation ensuring `image-upload-content.js` contains no `.click()` call.

### 2. Images page overlay

- Add `page-control-overlays.js` as a readable isolated-world content script.
- Create a compact dark Images pill matching the visible Prompts pill, anchored just below the detected Prompts overlay.
- Clicking the pill expands/collapses a small queue-status panel.
- Publish `{total, queued, done, lastUploadedName}` from `popup-image-uploads.js` to a small `chrome.storage.local` summary record.
- Read the summary on page load and react to `chrome.storage.onChanged` so counts update live.
- Keep all image blobs in IndexedDB; never copy full image data into `chrome.storage.local`.

### 3. Hit Video activation overlay

- Add a compact Hit Video pill below the Images pill.
- Add an internal custom-event bridge in `site-polish.js` that calls the existing `handleArmClickSync()`.
- Clicking the Hit overlay dispatches only this arm event.
- Reflect Ready/Active state on the overlay and exclude extension overlays from the next-click capture target.
- Do not invoke `hit_create_video` or `clickCreateVideoButton()` from the new overlay.

### 4. Styling and placement

- Add scoped styles to `dock-polish.css` using `studio-relay-` IDs/classes.
- Detect the smallest visible fixed element whose text matches the Prompts progress pill and place the overlay stack beneath it.
- Fall back to a safe upper-left position when the legacy Prompts pill is absent.
- Recalculate on resize and DOM changes without shifting or restyling page-owned controls.

## Validation Checklist

- `image-upload-content.js` has zero page `.click()` calls.
- Image upload still uses `DataTransfer`, native files setter, `input`, and `change`.
- Images pill renders, expands, collapses, and updates All/Queued/Done counts.
- Hit Video pill arms existing click-sync and visually shows Active.
- Clicking either extension overlay is never captured as the mirrored target.
- New overlay click never invokes Create Images/Create Video/Generate.
- Manifest, HTML, CSS, and JavaScript structural checks pass.
- Existing Prompts, Accounts, downloads, and social buttons remain untouched.
