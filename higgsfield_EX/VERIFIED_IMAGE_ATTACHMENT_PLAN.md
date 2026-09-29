# StudioRelay Verified Image Attachment Plan

## Confirmed False-Positive Chain

- `image-upload-content.js` treated a populated `input.files` value as proof that Dola accepted the image.
- Its drop fallback treated a cancelled drag/drop event as proof of attachment.
- Neither condition verifies that Dola rendered an attachment preview in the composer.
- `image-overlay-background.js` marked the queue record `done` immediately after either weak signal returned success.

## Implementation Plan

1. Tighten file-input selection:
   - accept only inputs linked to the active composer;
   - accept explicitly image-capable inputs;
   - reject unrelated generic/profile/avatar inputs.
2. Capture composer attachment state before every injection attempt.
3. Attempt the composer-linked file input first, then use a no-click composer drop fallback.
4. Treat input assignment/drop dispatch as an attempt, never as success.
5. Poll for real UI evidence for a bounded period:
   - a new/changed image preview;
   - a new attachment/preview/remove control;
   - or the selected filename appearing in the composer surface.
6. Require both `success` and explicit `verified: true` at every popup/background `Done` boundary.
7. On verification failure:
   - return a specific error;
   - keep the image queued;
   - persist the error for both Image Dock and side-panel views.
8. Store verification time/evidence with successful records and automatically re-queue legacy Done records that have no proof.
9. Validate zero programmatic page-button clicks and ensure `Done` is reachable only after verified attachment evidence.

