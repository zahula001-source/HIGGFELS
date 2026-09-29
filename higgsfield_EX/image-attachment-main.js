// ============================================================================
// DOLA TAB SESSION ISOLATION & ANTI-RELOAD LOOP SHIELD
// ============================================================================
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  if (window.__studioRelaySessionShieldActive) return;
  window.__studioRelaySessionShieldActive = true;

  // 1. Cross-Tab Storage Event Blocker
  try {
    const originalAddEventListener = window.addEventListener;
    window.addEventListener = function (type, listener, options) {
      if (type === 'storage') {
        const wrappedListener = function (event) {
          try {
            if (!event || !event.key) return;
            const keyLower = String(event.key).toLowerCase();
            if (
              keyLower.includes('token') ||
              keyLower.includes('auth') ||
              keyLower.includes('session') ||
              keyLower.includes('user') ||
              keyLower.includes('login') ||
              keyLower.includes('logout') ||
              keyLower.includes('passport') ||
              keyLower.includes('account') ||
              keyLower.includes('credential') ||
              keyLower.includes('csrf') ||
              keyLower.includes('jwt')
            ) {
              return;
            }
          } catch (e) {}
          if (typeof listener === 'function') {
            return listener.apply(this, arguments);
          } else if (listener && typeof listener.handleEvent === 'function') {
            return listener.handleEvent(event);
          }
        };
        return originalAddEventListener.call(this, type, wrappedListener, options);
      }
      return originalAddEventListener.apply(this, arguments);
    };
  } catch (e) {}

  // 2. Cross-Tab BroadcastChannel Isolation
  try {
    if (typeof window.BroadcastChannel !== 'undefined') {
      const OriginalBroadcastChannel = window.BroadcastChannel;
      window.BroadcastChannel = function (channelName) {
        const channel = new OriginalBroadcastChannel(channelName);
        const nameLower = String(channelName || '').toLowerCase();
        const isAuthChannel = (
          nameLower.includes('auth') ||
          nameLower.includes('session') ||
          nameLower.includes('login') ||
          nameLower.includes('logout') ||
          nameLower.includes('user') ||
          nameLower.includes('token') ||
          nameLower.includes('passport') ||
          nameLower.includes('account')
        );

        const originalPostMessage = channel.postMessage.bind(channel);
        channel.postMessage = function (message) {
          try {
            if (isAuthChannel) return;
            if (message && typeof message === 'object') {
              const msgStr = JSON.stringify(message).toLowerCase();
              if (
                msgStr.includes('logout') ||
                msgStr.includes('unauthorized') ||
                msgStr.includes('token_expired') ||
                msgStr.includes('session_invalid') ||
                msgStr.includes('reload')
              ) {
                return;
              }
            }
          } catch (e) {}
          return originalPostMessage(message);
        };

        const originalAddEventListener = channel.addEventListener.bind(channel);
        channel.addEventListener = function (type, listener, options) {
          if (type === 'message') {
            const wrapped = function (event) {
              try {
                if (isAuthChannel) return;
                if (event && event.data && typeof event.data === 'object') {
                  const msgStr = JSON.stringify(event.data).toLowerCase();
                  if (
                    msgStr.includes('logout') ||
                    msgStr.includes('unauthorized') ||
                    msgStr.includes('token_expired') ||
                    msgStr.includes('session_invalid') ||
                    msgStr.includes('reload')
                  ) {
                    return;
                  }
                }
              } catch (e) {}
              if (typeof listener === 'function') {
                return listener.apply(this, arguments);
              }
            };
            return originalAddEventListener(type, wrapped, options);
          }
          return originalAddEventListener(type, listener, options);
        };

        return channel;
      };
      window.BroadcastChannel.prototype = OriginalBroadcastChannel.prototype;
    }
  } catch (e) {}

  // 3. Anti-Reload Loop Circuit Breaker
  try {
    const RELOAD_GUARD_KEY = '__studioRelay_reload_guard';
    const now = Date.now();
    let history = [];
    try {
      const stored = sessionStorage.getItem(RELOAD_GUARD_KEY);
      if (stored) {
        history = JSON.parse(stored);
      }
    } catch (e) {}

    history = (Array.isArray(history) ? history : []).filter(t => typeof t === 'number' && now - t < 15000);
    history.push(now);

    try {
      sessionStorage.setItem(RELOAD_GUARD_KEY, JSON.stringify(history));
    } catch (e) {}

    let userInteracted = false;
    ['click', 'keydown', 'touchstart'].forEach(evt => {
      window.addEventListener(evt, () => { userInteracted = true; }, { capture: true, passive: true });
    });

    if (history.length > 2) {
      const preventLoop = function () {
        if (!userInteracted) {
          showReloadGuardBanner();
          return false;
        }
        return true;
      };

      try {
        const origReload = window.location.reload.bind(window.location);
        window.location.reload = function () {
          if (preventLoop()) origReload();
        };
      } catch (e) {}

      try {
        const origReplace = window.location.replace.bind(window.location);
        window.location.replace = function (url) {
          if (typeof url === 'string' && (url.includes('/login') || url.includes('/chat'))) {
            if (!preventLoop()) return;
          }
          origReplace(url);
        };
      } catch (e) {}

      function showReloadGuardBanner() {
        if (document.getElementById('studio-relay-reload-guard-banner')) return;
        const banner = document.createElement('div');
        banner.id = 'studio-relay-reload-guard-banner';
        banner.style.cssText = 'position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:9999999;background:#1e1b4b;color:#e0e7ff;border:1px solid #6366f1;padding:8px 16px;border-radius:8px;font-family:sans-serif;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,0.5);display:flex;align-items:center;gap:10px;';
        banner.innerHTML = '<span>⚠️ Tab cookies expired or invalid. Auto-reload paused.</span><button id="studio-relay-reload-btn" style="background:#6366f1;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold;">↻ Reload</button>';
        (document.body || document.documentElement).appendChild(banner);
        const btn = document.getElementById('studio-relay-reload-btn');
        if (btn) {
          btn.addEventListener('click', () => {
            try { sessionStorage.removeItem(RELOAD_GUARD_KEY); } catch (e) {}
            window.location.reload();
          });
        }
      }
    }
  } catch (e) {}
})();

(() => {
    'use strict';

    const INSTALL_FLAG = '__studioRelayImageAttachmentMainV2Installed';
    const REQUEST_EVENT = 'studio-relay:image-attach-request:v2';
    const RESPONSE_EVENT = 'studio-relay:image-attach-response:v2';
    const MAX_IMAGE_BYTES = 25 * 1024 * 1024;
    const MAX_REQUEST_CHARS = 36 * 1024 * 1024;
    const JOB_CACHE_MS = 60 * 1000;
    const ACTIVATION_POLL_MS = 80;
    const ACTIVATION_INPUT_TIMEOUT_MS = 1800;
    const ACTIVATION_CONTROL_SELECTOR = 'button, [role=button], [role=menuitem], [role=option], label, li';
    const COMPOSER_SELECTOR = 'textarea, [contenteditable]:not([contenteditable="false"]), [role="textbox"], input[type="text"]';
    const SUPPORTED_MIME_TYPES = new Set([
        'image/avif',
        'image/gif',
        'image/jpeg',
        'image/png',
        'image/webp'
    ]);
    const SUPPORTED_HOSTS = ['dola.com', 'seaart.ai'];

    if (globalThis[INSTALL_FLAG]) return;
    globalThis[INSTALL_FLAG] = true;

    const jobs = new Map();
    document.addEventListener(REQUEST_EVENT, handleRequest, true);

    function handleRequest(event) {
        let request;
        try {
            request = parseRequest(event.detail);
        } catch (error) {
            const requestId = safeRequestIdFromDetail(event.detail);
            if (requestId) respond(requestId, failure(error));
            return;
        }

        let job = jobs.get(request.requestId);
        if (!job) {
            const promise = Promise.resolve()
                .then(() => commitAttachment(request))
                .catch(error => failure(error));
            job = {createdAt: Date.now(), promise};
            jobs.set(request.requestId, job);
            window.setTimeout(() => {
                if (jobs.get(request.requestId) === job) jobs.delete(request.requestId);
            }, JOB_CACHE_MS);
        }

        job.promise.then(result => respond(request.requestId, result));
    }

    function parseRequest(detail) {
        if (typeof detail !== 'string' || !detail || detail.length > MAX_REQUEST_CHARS) {
            throw new Error('The MAIN-world image request is missing or too large.');
        }

        const request = JSON.parse(detail);
        if (request?.v !== 2 || !isSafeId(request.requestId)) {
            throw new Error('The MAIN-world image request is invalid.');
        }
        if (!isSupportedPage()) throw new Error('This page is not a supported Dola target.');
        if (!request.image || typeof request.image.dataUrl !== 'string') {
            throw new Error('The MAIN-world image payload is missing.');
        }
        return request;
    }

    async function commitAttachment(request) {
        const file = dataUrlToFile(request.image);
        const composerTarget = findComposerTarget();
        const composerSurface = findComposerSurface(composerTarget) || composerTarget;
        const input = findBestImageInput(composerSurface, composerTarget);

        if (input) {
            assignFileOnce(input, file);
            return {
                success: true,
                committed: true,
                method: 'main-existing-file-input',
                fileName: file.name,
                fileSize: file.size
            };
        }

        if (!composerTarget || !composerSurface) {
            throw new Error('Dola did not expose an active composer.');
        }

        const activatedInput = await silentlyActivateAndAssign(file, composerSurface, composerTarget);
        return {
            success: true,
            committed: true,
            method: 'main-silent-plus-file-input',
            fileName: file.name,
            fileSize: file.size,
            inputAccept: activatedInput.getAttribute('accept') || ''
        };
    }

    function assignFileOnce(input, file) {
        const transfer = new DataTransfer();
        transfer.items.add(file);
        if (transfer.files.length !== 1) throw new Error('The page FileList could not be prepared.');

        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files');
        if (descriptor?.set) descriptor.set.call(input, transfer.files);
        else input.files = transfer.files;

        input.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
    }

    async function silentlyActivateAndAssign(file, surface, target) {
        const beforeInputs = new Set(queryAllDeep('input[type="file"]'));
        const beforeControls = new Set(queryAllDeep(ACTIVATION_CONTROL_SELECTOR));
        const guard = installSilentFileChooserGuard();
        const plusControl = findComposerAddControl(surface, target);

        if (!plusControl) {
            guard.restore();
            throw new Error('Dola plus/add attachment control was not found in the active composer.');
        }

        try {
            activateControlOnce(plusControl);

            let input = await waitForActivatedImageInput(
                beforeInputs,
                surface,
                target,
                guard,
                650
            );
            if (!input) {
                const uploadControl = findUploadMenuControl(beforeControls, plusControl, surface);
                if (!uploadControl) {
                    throw new Error('Dola opened the plus workflow but exposed no safe image/file upload control.');
                }
                activateControlOnce(uploadControl);
                input = await waitForActivatedImageInput(
                    beforeInputs,
                    surface,
                    target,
                    guard,
                    ACTIVATION_INPUT_TIMEOUT_MS
                );
            }

            if (!input) {
                throw new Error('Dola did not mount or expose its real file input after silent plus activation.');
            }

            assignFileOnce(input, file);
            await delay(180);
            return input;
        } finally {
            guard.restore();
        }
    }

    function activateControlOnce(element) {
        if (!(element instanceof Element)) {
            throw new Error('Dola upload activation control is invalid.');
        }

        const rect = element.getBoundingClientRect();
        const clientX = Math.round(rect.left + Math.max(1, rect.width / 2));
        const clientY = Math.round(rect.top + Math.max(1, rect.height / 2));
        try { element.focus({preventScroll: true}); } catch {}

        const shared = {
            bubbles: true,
            cancelable: true,
            composed: true,
            view: window,
            clientX,
            clientY,
            button: 0
        };
        if (typeof PointerEvent === 'function') {
            element.dispatchEvent(new PointerEvent('pointerdown', {
                ...shared,
                buttons: 1,
                pointerId: 1,
                pointerType: 'mouse',
                isPrimary: true
            }));
        }
        element.dispatchEvent(new MouseEvent('mousedown', {...shared, buttons: 1}));
        if (typeof PointerEvent === 'function') {
            element.dispatchEvent(new PointerEvent('pointerup', {
                ...shared,
                buttons: 0,
                pointerId: 1,
                pointerType: 'mouse',
                isPrimary: true
            }));
        }
        element.dispatchEvent(new MouseEvent('mouseup', {...shared, buttons: 0}));

        if (typeof element.click === 'function') element.click();
        else element.dispatchEvent(new MouseEvent('click', {...shared, buttons: 0, detail: 1}));
    }
    function installSilentFileChooserGuard() {
        let capturedInput = null;
        const hiddenNodes = new Map();
        const inputPrototype = HTMLInputElement.prototype;
        const originalShowPicker = inputPrototype.showPicker;
        let showPickerPatched = false;

        const rememberAndHide = element => {
            if (!(element instanceof Element) || hiddenNodes.has(element)) return;
            const identity = controlIdentity(element);
            const role = String(element.getAttribute('role') || '').toLowerCase();
            const className = String(element.className || '').toLowerCase();
            const likelyOverlay = /menu|listbox|dialog/.test(role) ||
                /popover|dropdown|floating|portal|menu/.test(className) ||
                /upload|attach|choose.*file|select.*file|photo|gallery/.test(identity);
            if (!likelyOverlay) return;

            hiddenNodes.set(element, {
                opacity: element.style.getPropertyValue('opacity'),
                opacityPriority: element.style.getPropertyPriority('opacity'),
                pointerEvents: element.style.getPropertyValue('pointer-events'),
                pointerPriority: element.style.getPropertyPriority('pointer-events')
            });
            element.style.setProperty('opacity', '0', 'important');
            element.style.setProperty('pointer-events', 'none', 'important');
        };

        const inspectAddedNode = node => {
            if (!(node instanceof Element)) return;
            rememberAndHide(node);
            try {
                node.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"], [class*="popover" i], [class*="dropdown" i], [class*="floating" i], [class*="portal" i]')
                    .forEach(rememberAndHide);
            } catch {}
        };

        const observer = new MutationObserver(records => {
            records.forEach(record => {
                if (record.type === 'attributes') inspectAddedNode(record.target);
                else record.addedNodes.forEach(inspectAddedNode);
            });
        });
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class', 'style', 'aria-hidden', 'data-state', 'open']
        });

        const interceptFileClick = event => {
            const path = typeof event.composedPath === 'function' ? event.composedPath() : [event.target];
            const input = path.find(node => node instanceof HTMLInputElement && node.type === 'file');
            if (!input || event.isTrusted) return;
            capturedInput = input;
            event.preventDefault();
            event.stopImmediatePropagation();
        };
        document.addEventListener('click', interceptFileClick, true);

        if (typeof originalShowPicker === 'function') {
            try {
                inputPrototype.showPicker = function studioRelaySilentShowPicker() {
                    if (this instanceof HTMLInputElement && this.type === 'file') {
                        capturedInput = this;
                        return undefined;
                    }
                    return originalShowPicker.call(this);
                };
                showPickerPatched = true;
            } catch {}
        }

        return {
            getCapturedInput() {
                return capturedInput;
            },
            restore() {
                observer.disconnect();
                document.removeEventListener('click', interceptFileClick, true);
                if (showPickerPatched) {
                    try { inputPrototype.showPicker = originalShowPicker; } catch {}
                }
                hiddenNodes.forEach((previous, element) => {
                    if (!(element instanceof Element)) return;
                    if (previous.opacity) {
                        element.style.setProperty('opacity', previous.opacity, previous.opacityPriority);
                    } else {
                        element.style.removeProperty('opacity');
                    }
                    if (previous.pointerEvents) {
                        element.style.setProperty('pointer-events', previous.pointerEvents, previous.pointerPriority);
                    } else {
                        element.style.removeProperty('pointer-events');
                    }
                });
                hiddenNodes.clear();
            }
        };
    }

    function findComposerAddControl(surface, target) {
        const surfaceRect = surface.getBoundingClientRect();
        const candidates = queryAllDeep('button, [role="button"], label[for]')
            .filter(element => !element.closest?.('#studio-relay-page-overlays'))
            .filter(isVisible)
            .map((element, index) => ({
                element,
                index,
                score: scoreComposerAddControl(element, surface, target, surfaceRect)
            }))
            .filter(candidate => candidate.score >= 190)
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));
        return candidates[0]?.element || null;
    }

    function scoreComposerAddControl(element, surface, target, surfaceRect) {
        const identity = controlIdentity(element);
        const text = String(element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        if (/create\s*(?:images?|videos?)|generate|send|submit|download|model|style|template|ratio|translate|avatar|profile|\bfast\b|\bmore\b|writing|homework/.test(identity)) {
            return -1000;
        }

        const rect = element.getBoundingClientRect();
        const linked = surface.contains(element) || element.contains(target) ||
            rectanglesOverlap(rect, surfaceRect, 32);
        if (!linked) return -1000;

        let score = 0;
        if (text === '+') score += 360;
        if (/\bplus\b|(?:^|\s)add(?:\s|$)|add\s*(?:attachment|file|image|photo)|attach|upload/.test(identity)) score += 300;
        if (surface.contains(element)) score += 150;
        if (rect.width <= 72 && rect.height <= 72) score += 50;
        if (rect.left <= surfaceRect.left + surfaceRect.width * 0.35) score += 90;
        const leftOffset = Math.max(0, rect.left - surfaceRect.left);
        score += Math.max(0, 180 - Math.min(180, leftOffset));
        if (rect.bottom >= surfaceRect.top + surfaceRect.height * 0.45) score += 35;
        return score;
    }

    function findUploadMenuControl(beforeControls, plusControl, surface) {
        const plusRect = plusControl.getBoundingClientRect();
        const candidates = queryAllDeep(ACTIVATION_CONTROL_SELECTOR)
            .filter(element => element !== plusControl)
            .filter(element => !element.closest?.('#studio-relay-page-overlays'))
            .filter(hasLayoutBox)
            .map((element, index) => ({
                element,
                index,
                score: scoreUploadMenuControl(element, beforeControls, plusRect, surface)
            }))
            .filter(candidate => candidate.score >= 180)
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));
        return candidates[0]?.element || null;
    }

    function scoreUploadMenuControl(element, beforeControls, plusRect, surface) {
        const identity = controlIdentity(element);
        if (!/upload|attach|image|photo|picture|file|gallery|computer|device/.test(identity)) return -1000;
        if (/create|generate|camera|video|audio|avatar|profile|logo|cover|send|submit/.test(identity)) return -1000;

        let score = 0;
        if (!beforeControls.has(element)) score += 220;
        if (/upload|attach|choose\s*file|select\s*file/.test(identity)) score += 240;
        if (/image|photo|picture|file|gallery|computer|device/.test(identity)) score += 150;
        if (element.matches('label[for]')) score += 80;
        if (element.querySelector?.('input[type="file"]')) score += 260;
        if (!surface.contains(element)) score += 30;

        const rect = element.getBoundingClientRect();
        const distance = Math.hypot(rect.left - plusRect.left, rect.top - plusRect.top);
        if (distance <= 420) score += 70;
        return score;
    }

    async function waitForActivatedImageInput(beforeInputs, surface, target, guard, timeoutMs) {
        const deadline = Date.now() + Math.max(ACTIVATION_POLL_MS, Number(timeoutMs) || 0);
        while (Date.now() < deadline) {
            const captured = guard.getCapturedInput();
            const input = findActivatedImageInput(beforeInputs, captured, surface, target);
            if (input) return input;
            await delay(ACTIVATION_POLL_MS);
        }
        return null;
    }

    function findActivatedImageInput(beforeInputs, capturedInput, surface, target) {
        const candidates = queryAllDeep('input[type="file"]')
            .filter(input => !input.disabled)
            .map((input, index) => ({
                input,
                index,
                score: scoreActivatedImageInput(input, beforeInputs, capturedInput, surface, target)
            }))
            .filter(candidate => candidate.score >= 140)
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));
        return candidates[0]?.input || null;
    }

    function scoreActivatedImageInput(input, beforeInputs, capturedInput, surface, target) {
        const accept = String(input.getAttribute('accept') || '').toLowerCase();
        const identity = controlIdentity(input);
        const explicitImage = /image\//.test(accept) || /\.(?:avif|gif|jpe?g|png|webp)/.test(accept);
        const imageIdentity = /image|photo|picture|attachment|upload|file/.test(identity);
        const profileIdentity = /avatar|profile|logo|cover/.test(identity);
        const linked = isInputLinked(input, surface, target);

        if (/video\//.test(accept) && !/image\//.test(accept)) return -1000;
        if (/audio\//.test(accept) && !/image\//.test(accept)) return -1000;
        if (profileIdentity) return -1000;

        let score = 0;
        if (input === capturedInput) score += 1000;
        if (!beforeInputs.has(input)) score += 360;
        if (explicitImage) score += 220;
        if (imageIdentity) score += 120;
        if (linked) score += 160;
        if (!accept || accept.includes('*/*')) score += 20;
        return score;
    }

    function controlIdentity(element) {
        return [
            element.id,
            element.getAttribute?.('name'),
            element.getAttribute?.('aria-label'),
            element.getAttribute?.('title'),
            element.getAttribute?.('data-testid'),
            element.getAttribute?.('data-tooltip-content'),
            element.getAttribute?.('data-state'),
            String(element.className || ''),
            String(element.textContent || '')
        ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function rectanglesOverlap(left, right, margin) {
        return left.right >= right.left - margin &&
            left.left <= right.right + margin &&
            left.bottom >= right.top - margin &&
            left.top <= right.bottom + margin;
    }

    function hasLayoutBox(element) {
        if (!(element instanceof Element)) return false;
        const rect = element.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const style = getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden';
    }

    function delay(milliseconds) {
        return new Promise(resolve => window.setTimeout(resolve, milliseconds));
    }
    function findBestImageInput(surface, target) {
        const candidates = queryAllDeep('input[type="file"]')
            .filter(input => !input.disabled)
            .map((input, index) => ({input, index, score: scoreImageInput(input, surface, target)}))
            .filter(candidate => candidate.score >= 120)
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));
        return candidates[0]?.input || null;
    }

    function scoreImageInput(input, surface, target) {
        const accept = String(input.getAttribute('accept') || '').toLowerCase();
        const identity = [
            input.id,
            input.name,
            input.className,
            input.getAttribute('aria-label'),
            input.getAttribute('title'),
            input.getAttribute('data-testid')
        ].filter(Boolean).join(' ').toLowerCase();
        const explicitImage = /image\//.test(accept) || /\.(?:avif|gif|jpe?g|png|webp)/.test(accept);
        const imageIdentity = /image|photo|picture|reference|attachment|upload/.test(identity);
        const profileIdentity = /avatar|profile|logo|cover/.test(identity);
        const linked = isInputLinked(input, surface, target);

        if (/video\//.test(accept) && !/image\//.test(accept)) return -1000;
        if (/audio\//.test(accept) && !/image\//.test(accept)) return -1000;
        if (profileIdentity) return -1000;
        if (!explicitImage && !imageIdentity && !linked) return -1000;

        let score = 0;
        if (explicitImage) score += 180;
        if (imageIdentity) score += 70;
        if (linked) score += 110;
        if (!accept || accept.includes('*/*')) score -= 25;
        if (input.multiple) score += 5;
        return score;
    }

    function isInputLinked(input, surface, target) {
        if (surface?.contains?.(input) || input.form?.contains?.(target)) return true;
        const inputId = String(input.id || '').trim();
        if (inputId && surface) {
            try {
                if (Array.from(surface.querySelectorAll('label[for]')).some(label => label.htmlFor === inputId)) {
                    return true;
                }
            } catch {}
        }

        let current = input.parentElement || input.getRootNode?.().host || null;
        for (let depth = 0; current && depth < 8; depth += 1) {
            if (target && current.contains?.(target)) return true;
            current = current.parentElement || current.getRootNode?.().host || null;
        }
        return false;
    }

    function findComposerTarget() {
        const candidates = queryAllDeep(COMPOSER_SELECTOR)
            .filter(element => !element.closest?.('#studio-relay-page-overlays'))
            .filter(isVisible)
            .map((element, index) => ({element, index, score: scoreComposer(element)}))
            .sort((left, right) => (right.score - left.score) || (right.index - left.index));
        return candidates[0]?.element || null;
    }

    function scoreComposer(element) {
        const rect = element.getBoundingClientRect();
        const identity = [
            element.getAttribute('placeholder'),
            element.getAttribute('aria-label'),
            element.getAttribute('data-placeholder'),
            element.getAttribute('data-slate-placeholder'),
            element.getAttribute('data-testid')
        ].filter(Boolean).join(' ').toLowerCase();
        let score = 1;
        if (/describe|prompt|image|video|message|action|create/.test(identity)) score += 100;
        if (element.matches('[contenteditable]:not([contenteditable="false"]), [role="textbox"]')) score += 18;
        if (rect.bottom >= window.innerHeight * 0.45) score += 28;
        if (rect.width >= Math.min(320, window.innerWidth * 0.3)) score += 12;
        return score;
    }

    function findComposerSurface(target) {
        if (!(target instanceof Element)) return null;
        let current = target;
        let best = target;
        for (let depth = 0; current && depth < 10; depth += 1) {
            const rect = current.getBoundingClientRect();
            const hasEditor = current.matches?.(COMPOSER_SELECTOR) || Boolean(current.querySelector?.(COMPOSER_SELECTOR));
            if (hasEditor && rect.width >= 240 && rect.height >= 24 && rect.height <= 600) best = current;
            if (rect.height > 600) break;
            current = current.parentElement || current.getRootNode?.().host || null;
        }
        return best;
    }

    function queryAllDeep(selector) {
        const results = [];
        const roots = [document];
        while (roots.length) {
            const root = roots.shift();
            let elements = [];
            try { elements = Array.from(root.querySelectorAll(selector)); } catch {}
            results.push(...elements);
            let descendants = [];
            try { descendants = root.querySelectorAll('*'); } catch {}
            descendants.forEach(element => {
                if (element.shadowRoot) roots.push(element.shadowRoot);
            });
        }
        return Array.from(new Set(results));
    }

    function dataUrlToFile(payload) {
        const dataUrl = String(payload.dataUrl || '');
        const commaIndex = dataUrl.indexOf(',');
        if (commaIndex < 0) throw new Error('The image payload is not a valid data URL.');

        const header = dataUrl.slice(0, commaIndex);
        const encoded = dataUrl.slice(commaIndex + 1);
        const match = /^data:([^;,]+)?(?:;charset=[^;,]+)?(;base64)?$/i.exec(header);
        const mimeType = String(payload.type || match?.[1] || '').toLowerCase();
        if (!match?.[2] || !SUPPORTED_MIME_TYPES.has(mimeType)) {
            throw new Error('The image payload type is not supported.');
        }
        if (encoded.length > Math.ceil(MAX_IMAGE_BYTES * 4 / 3) + 8) {
            throw new Error('The image is larger than 25 MB.');
        }

        let binary;
        try { binary = atob(encoded); } catch { throw new Error('The image payload could not be decoded.'); }
        if (!binary.length || binary.length > MAX_IMAGE_BYTES) {
            throw new Error('The image is empty or larger than 25 MB.');
        }

        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
        return new File([bytes], sanitizeFileName(payload.name, mimeType), {
            type: mimeType,
            lastModified: Number(payload.lastModified) || Date.now()
        });
    }

    function sanitizeFileName(value, mimeType) {
        const extensions = {
            'image/avif': 'avif',
            'image/gif': 'gif',
            'image/jpeg': 'jpg',
            'image/png': 'png',
            'image/webp': 'webp'
        };
        const extension = extensions[mimeType] || 'png';
        const leaf = String(value || '')
            .split(/[\\/]/)
            .pop()
            .replace(/[\u0000-\u001f<>:"|?*]/g, '_')
            .trim();
        if (!leaf) return `studio-relay-image.${extension}`;
        if (/\.[a-z0-9]{2,5}$/i.test(leaf)) return leaf.slice(0, 180);
        return `${leaf.slice(0, 170)}.${extension}`;
    }

    function safeRequestIdFromDetail(detail) {
        if (typeof detail !== 'string' || detail.length > MAX_REQUEST_CHARS) return '';
        try {
            const parsed = JSON.parse(detail);
            return isSafeId(parsed?.requestId) ? parsed.requestId : '';
        } catch {
            return '';
        }
    }

    function isSafeId(value) {
        return typeof value === 'string' && /^[a-zA-Z0-9_-]{12,160}$/.test(value);
    }

    function isSupportedPage() {
        if (!['http:', 'https:'].includes(location.protocol)) return false;
        return SUPPORTED_HOSTS.some(host => location.hostname === host || location.hostname.endsWith(`.${host}`));
    }

    function isVisible(element) {
        const style = getComputedStyle(element);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function failure(error) {
        return {success: false, committed: false, error: error?.message || String(error)};
    }

    function respond(requestId, result) {
        const detail = JSON.stringify({v: 2, requestId, ...result});
        document.dispatchEvent(new CustomEvent(RESPONSE_EVENT, {detail}));
    }
})();
