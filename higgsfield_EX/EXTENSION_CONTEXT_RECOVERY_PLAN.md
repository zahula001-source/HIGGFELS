# StudioRelay Extension Context Recovery Plan

## Confirmed Root Cause

- The visible `Extension context invalidated.` message originates at the Image Dock's `chrome.runtime.sendMessage()` boundary, before the background upload handler can run.
- Chromium emits this exact error after an extension execution context has been invalidated/disposed.
- Reloading or updating an unpacked extension invalidates content scripts already running in open host tabs. Their injected DOM can remain visible, but their `chrome.runtime` connection is no longer usable until the host tab is reloaded.
- Manifest V3 service workers becoming `inactive` after an idle period is expected Chrome lifecycle behavior and is not the upload failure.

## Implementation Plan

1. Add a centralized extension-context health check to `image-dock.js`.
2. Wrap every Image Dock Chrome API boundary so synchronous context-invalidated errors are handled deliberately.
3. Add a terminal stale-context UI state:
   - stop the busy state;
   - disable Upload/Re-upload and Upload All Tabs;
   - show a precise reload-required message;
   - change Refresh into a one-click Reload Page recovery action.
4. Keep page reload user-initiated so an active Dola task or unsaved prompt is not destroyed automatically.
5. Preserve the existing direct-file/no-page-click upload behavior after a fresh context is available.
6. Validate that:
   - stale context cannot start an upload or mark an image done;
   - no unhandled `Extension context invalidated.` error leaks into generic upload status;
   - normal queue refresh/upload still uses the background bridge;
   - image upload still contains zero programmatic page-button clicks.

