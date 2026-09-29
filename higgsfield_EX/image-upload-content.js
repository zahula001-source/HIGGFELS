(() => {
    'use strict';

    const INSTALL_FLAG = '__studioRelayImageUploaderInstalled';
    const UPLOAD_ACTION = 'studioRelayUploadImage';
    const MAX_PAYLOAD_BYTES = 35 * 1024 * 1024;
    const SUPPORTED_MIME_TYPES = new Set([
        'image/avif',
        'image/gif',
        'image/jpeg',
        'image/png',
        'image/webp'
    ]);

    if (globalThis[INSTALL_FLAG]) return;
    globalThis[INSTALL_FLAG] = true;

    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
        if (message?.action !== UPLOAD_ACTION) return undefined;

        handleUpload(message.image)
            .then(result => sendResponse({success: true, ...result}))
            .catch(error => sendResponse({
                success: false,
                error: error?.message || String(error)
            }));

        return true;
    });

    async function handleUpload(payload) {
        const file = dataUrlToFile(payload);
        const input = findBestImageInput();

        let method = 'file-input';
        if (input) {
            assignFile(input, file);
            await delay(260);

            if (!input.files?.length) {
                throw new Error('The page blocked assignment to its image upload field.');
            }
        } else {
            const dropTarget = findComposerUploadTarget();
            if (!dropTarget || !dispatchFileDrop(dropTarget, file)) {
                throw new Error('The page did not expose an image input or accept a direct image drop. Open the image composer and retry.');
            }
            method = 'composer-drop';
            await delay(420);
        }

        return {
            fileName: file.name,
            inputAccept: input?.getAttribute('accept') || '',
            inputMultiple: Boolean(input?.multiple),
            method
        };
    }

    function dataUrlToFile(payload) {
        if (!payload || typeof payload.dataUrl !== 'string') {
            throw new Error('The image payload is missing.');
        }

        const commaIndex = payload.dataUrl.indexOf(',');
        if (commaIndex < 0) throw new Error('The image payload is not a valid data URL.');

        const header = payload.dataUrl.slice(0, commaIndex);
        const encoded = payload.dataUrl.slice(commaIndex + 1);
        const headerMatch = /^data:([^;,]+)?(?:;charset=[^;,]+)?(;base64)?$/i.exec(header);
        if (!headerMatch || !headerMatch[2]) throw new Error('The image payload is not base64 encoded.');

        const mimeType = String(payload.type || headerMatch[1] || '') .toLowerCase();
        if (!SUPPORTED_MIME_TYPES.has(mimeType)) throw new Error('This image format is not supported.');

        let binary;
        try {
            binary = atob(encoded);
        } catch {
            throw new Error('The image payload could not be decoded.');
        }

        if (!binary.length || binary.length > MAX_PAYLOAD_BYTES) {
            throw new Error('The image is empty or larger than the supported upload limit.');
        }

        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
        }

        const safeName = sanitizeFileName(payload.name, mimeType);
        return new File([bytes], safeName, {
            type: mimeType,
            lastModified: Number(payload.lastModified) || Date.now()
        });
    }

    function sanitizeFileName(value, mimeType) {
        const fallbackExtensions = {
            'image/avif': 'avif',
            'image/gif': 'gif',
            'image/jpeg': 'jpg',
            'image/png': 'png',
            'image/webp': 'webp'
        };
        const extension = fallbackExtensions[mimeType] || 'png';
        const leafName = String(value || '')
            .split(/[\\/]/)
            .pop()
            .replace(/[\u0000-\u001f<>:"|?*]/g, '_')
            .trim();

        if (!leafName) return `studio-relay-image.${extension}`;
        if (/\.[a-z0-9]{2,5}$/i.test(leafName)) return leafName.slice(0, 180);
        return `${leafName.slice(0, 170)}.${extension}`;
    }

    function findBestImageInput() {
        const inputs = queryAllDeep('input[type="file"]')
            .filter(input => !input.disabled)
            .map((input, index) => ({input, index, score: scoreFileInput(input)}))
            .filter(candidate => candidate.score > 0)
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));

        return inputs[0]?.input || null;
    }

    function scoreFileInput(input) {
        const accept = String(input.getAttribute('accept') || '') .toLowerCase();
        const identity = `${input.id || ''} ${input.name || ''} ${input.className || ''} ${input.getAttribute('aria-label') || ''} ${input.getAttribute('title') || ''} ${input.getAttribute('data-testid') || ''}` .toLowerCase();
        const hasImageIdentity = /image|photo|picture|reference|upload/.test(identity);
        const hasProfileIdentity = /avatar|profile|logo|cover/.test(identity);
        const nearComposer = isNearComposer(input);

        if (/video\//.test(accept) && !/image\//.test(accept)) return -100;
        if (/audio\//.test(accept) && !/image\//.test(accept)) return -100;

        let score = 1;
        if (/image\//.test(accept)) score += 100;
        if (/\.(?:avif|gif|jpe?g|png|webp)/.test(accept)) score += 85;
        if (!accept || accept.includes('*/*')) score += 18;
        if (hasImageIdentity) score += 28;
        if (nearComposer) score += 45;
        if (hasProfileIdentity && !nearComposer) score -= 80;
        if (isVisible(input)) score += 4;
        return score;
    }

    function findComposerUploadTarget() {
        const candidates = queryAllDeep('textarea, [contenteditable]:not([contenteditable="false"]), [role="textbox"], input[type="text"]')
            .filter(element => !element.closest?.('#studio-relay-page-overlays'))
            .filter(isVisible)
            .map((element, index) => ({
                element,
                index,
                score: scoreComposerTarget(element)
            }))
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));

        return candidates[0]?.element || null;
    }

    function scoreComposerTarget(element) {
        const rect = element.getBoundingClientRect();
        const identity = `${element.getAttribute('placeholder') || ''} ${element.getAttribute('aria-label') || ''} ${element.getAttribute('data-placeholder') || ''} ${element.getAttribute('data-testid') || ''}` .toLowerCase();
        let score = 1;
        if (/describe|prompt|image|video|action|create/.test(identity)) score += 100;
        if (element.matches('[contenteditable]:not([contenteditable="false"]), [role="textbox"]')) score += 18;
        if (rect.bottom >= window.innerHeight * 0.45) score += 28;
        if (rect.width >= Math.min(320, window.innerWidth * 0.3)) score += 12;
        return score;
    }

    function dispatchFileDrop(target, file) {
        const transfer = new DataTransfer();
        transfer.items.add(file);

        const dragEnterHandled = !target.dispatchEvent(createFileDragEvent('dragenter', transfer));
        const dragOverHandled = !target.dispatchEvent(createFileDragEvent('dragover', transfer));
        const dropHandled = !target.dispatchEvent(createFileDragEvent('drop', transfer));
        return dragEnterHandled || dragOverHandled || dropHandled;
    }

    function createFileDragEvent(type, transfer) {
        try {
            return new DragEvent(type, {
                bubbles: true,
                cancelable: true,
                composed: true,
                dataTransfer: transfer
            });
        } catch {
            const event = new Event(type, {bubbles: true, cancelable: true, composed: true});
            Object.defineProperty(event, 'dataTransfer', {value: transfer});
            return event;
        }
    }

    function isNearComposer(element) {
        let current = element;
        for (let depth = 0; current && depth < 7; depth += 1) {
            if (current.querySelector?.('textarea, [contenteditable]:not([contenteditable="false"]), [role="textbox"], input[type="text"]')) return true;
            current = current.parentElement || current.getRootNode?.().host || null;
        }
        return false;
    }

    function isVisible(element) {
        const style = getComputedStyle(element);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function queryAllDeep(selector) {
        const results = [];
        const roots = [document];

        while (roots.length) {
            const root = roots.shift();
            let elements = [];
            try {
                elements = Array.from(root.querySelectorAll(selector));
            } catch {
                elements = [];
            }
            results.push(...elements);

            let descendants = [];
            try {
                descendants = root.querySelectorAll('*');
            } catch {
                descendants = [];
            }
            descendants.forEach(element => {
                if (element.shadowRoot) roots.push(element.shadowRoot);
            });
        }

        return Array.from(new Set(results));
    }

    function assignFile(input, file) {
        const transfer = new DataTransfer();
        transfer.items.add(file);

        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files');
        if (descriptor?.set) descriptor.set.call(input, transfer.files);
        else input.files = transfer.files;

        input.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
        input.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
    }

    function delay(milliseconds) {
        return new Promise(resolve => window.setTimeout(resolve, milliseconds));
    }
})();
