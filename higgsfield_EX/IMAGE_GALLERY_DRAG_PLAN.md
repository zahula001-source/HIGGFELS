# StudioRelay Image Gallery Drag Plan

## Goal

Show saved images as a compact phone-gallery grid and let the user drag any thumbnail from the StudioRelay side panel onto a compatible Dola image composer/drop area.

## Interaction Contract

1. Preserve images in IndexedDB as their original `Blob` values.
2. Render square, cover-fit gallery thumbnails in selection order.
3. Keep filename/status accessible through labels and compact visual badges.
4. Clicking a tile retains the existing verified upload dialog.
5. Dragging a tile creates a real `File` from its stored `Blob` and adds it to the user-initiated `DataTransfer`.
6. Use copy semantics and a thumbnail drag image; never serialize image bytes into text payloads.
7. Do not mark a record Done merely because a drag ended. A trusted Dola drop observer waits for native preview evidence, then uses a composer-linked input fallback without page clicks; only verified UI evidence may mark Done.
8. Keep filters, deletion, bulk upload, queue ordering, and object-URL cleanup working.

## Validation

- Gallery is responsive and scrollable inside the side panel.
- Every populated tile has `draggable="true"` and an accessible drag instruction.
- Drag data contains an image `File` with the original name, MIME type, size, and last-modified value.
- Drag failure produces a visible error without changing queue state.
- Existing click upload and serial upload paths still require `verified: true`.
