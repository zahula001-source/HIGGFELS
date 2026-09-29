(function () {
    'use strict';

    const SESSION_BADGE_ID = 'channa-tab-session-badge';
    const SESSION_BADGE_TEXT = 'dola 30s minh';
    const MODE_LABEL_TEXT = '30s (minh)';
    const LEGACY_MODE_PATTERN = /^\s*(\d+)\s*s\s*\(\s*bypassed\s*\)\s*$/i;
    const ACTIVE_MODE_PATTERN = /^\s*(\d+)\s*s\s*\(\s*minh\s*\)\s*$/i;
    const INLINE_LEGACY_MODE_PATTERN = /(\d+)\s*s\s*\(\s*bypassed\s*\)/gi;
    const RELEVANT_MODE_TEXT = /bypassed|minh/i;
    const DOWNLOAD_LABEL_TEXT = 'Fetch & Download done';
    const LEGACY_DOWNLOAD_PATTERN = /^\s*(?:.{0,6}\s*)?fetch\s*\d+\s*s\s*hd\s*video\s*$/iu;
    const ACTIVE_DOWNLOAD_PATTERN = /^\s*fetch\s*&\s*download\s*done\s*$/i;
    const COMPLETED_DOWNLOAD_PATTERN = /^\s*(?:✓|✅)?\s*downloaded!?\s*$/iu;
    const RELEVANT_DOWNLOAD_TEXT = /fetch|downloaded/i;

    function polishSessionBadge() {
        const badge = document.getElementById(SESSION_BADGE_ID);
        if (!badge) return;
        badge.classList.add('studio-relay-session-badge');
        badge.setAttribute('aria-label', SESSION_BADGE_TEXT);
        badge.setAttribute('title', SESSION_BADGE_TEXT);
        if (badge.textContent.trim() !== SESSION_BADGE_TEXT) {
            badge.textContent = SESSION_BADGE_TEXT;
        }
    }

    function labelForDuration(duration) {
        return MODE_LABEL_TEXT.replace(/^30/, String(duration));
    }

    function findExactModeHost(start, pattern) {
        let current = start;
        for (let depth = 0; current && depth < 6; depth += 1) {
            const match = (current.textContent || '').match(pattern);
            if (match) return { element: current, duration: match[1] };
            current = current.parentElement;
        }
        return null;
    }

    function applyModeLabel(element, duration) {
        if (!(element instanceof Element)) return;
        const next = labelForDuration(duration);
        if (element.textContent.trim() !== next) element.textContent = next;
        element.classList.add('studio-relay-mode-pill');
        element.setAttribute('aria-label', next);
        element.setAttribute('title', next);
    }

    function polishModeTextNode(textNode) {
        if (!(textNode instanceof Text)) return;
        const parent = textNode.parentElement;
        if (!parent || parent.closest('script, style, textarea, input, [contenteditable="true"]')) return;

        const nearbyText = parent.textContent || '';
        if (!RELEVANT_MODE_TEXT.test(textNode.nodeValue || '') && !RELEVANT_MODE_TEXT.test(nearbyText)) return;

        const legacyHost = findExactModeHost(parent, LEGACY_MODE_PATTERN);
        if (legacyHost) {
            applyModeLabel(legacyHost.element, legacyHost.duration);
            return;
        }

        const activeHost = findExactModeHost(parent, ACTIVE_MODE_PATTERN);
        if (activeHost) {
            applyModeLabel(activeHost.element, activeHost.duration);
            return;
        }

        const source = textNode.nodeValue || '';
        let detectedDuration = null;
        const normalized = source.replace(INLINE_LEGACY_MODE_PATTERN, (_, duration) => {
            detectedDuration = duration;
            return labelForDuration(duration);
        });
        if (!detectedDuration) return;

        if (normalized !== source) textNode.nodeValue = normalized;
        const normalizedHost = findExactModeHost(parent, ACTIVE_MODE_PATTERN);
        applyModeLabel(normalizedHost ? normalizedHost.element : parent, detectedDuration);
    }

    function polishModeLabels(root) {
        if (root instanceof Text) {
            polishModeTextNode(root);
            return;
        }
        if (!(root instanceof Element) && root !== document) return;
        if (root instanceof Element && !RELEVANT_MODE_TEXT.test(root.textContent || '')) return;

        const scope = root === document ? document.documentElement : root;
        if (!scope) return;
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        textNodes.forEach(polishModeTextNode);
    }

    function findExactDownloadHost(start, pattern) {
        let current = start;
        for (let depth = 0; current && depth < 6; depth += 1) {
            if (pattern.test(current.textContent || '')) return current;
            current = current.parentElement;
        }
        return null;
    }

    function applyDownloadLabel(element) {
        if (!(element instanceof Element)) return;
        if (element.textContent.trim() !== DOWNLOAD_LABEL_TEXT) {
            element.textContent = DOWNLOAD_LABEL_TEXT;
        }
        element.classList.add('studio-relay-download-status');
        element.setAttribute('aria-label', DOWNLOAD_LABEL_TEXT);
        element.setAttribute('title', DOWNLOAD_LABEL_TEXT);
    }

    function polishDownloadTextNode(textNode) {
        if (!(textNode instanceof Text)) return;
        const parent = textNode.parentElement;
        if (!parent || parent.closest('script, style, textarea, input, [contenteditable="true"]')) return;

        const nearbyText = parent.textContent || '';
        if (!RELEVANT_DOWNLOAD_TEXT.test(textNode.nodeValue || '') && !RELEVANT_DOWNLOAD_TEXT.test(nearbyText)) return;

        const themedHost = parent.closest('.studio-relay-download-status');
        if (themedHost && COMPLETED_DOWNLOAD_PATTERN.test(themedHost.textContent || '')) {
            applyDownloadLabel(themedHost);
            return;
        }

        const legacyHost = findExactDownloadHost(parent, LEGACY_DOWNLOAD_PATTERN);
        if (legacyHost) {
            applyDownloadLabel(legacyHost);
            return;
        }

        const activeHost = findExactDownloadHost(parent, ACTIVE_DOWNLOAD_PATTERN);
        if (activeHost) applyDownloadLabel(activeHost);
    }

    function polishDownloadLabels(root) {
        if (root instanceof Text) {
            polishDownloadTextNode(root);
            return;
        }
        if (!(root instanceof Element) && root !== document) return;
        if (root instanceof Element && !RELEVANT_DOWNLOAD_TEXT.test(root.textContent || '')) return;

        const scope = root === document ? document.documentElement : root;
        if (!scope) return;
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        textNodes.forEach(polishDownloadTextNode);
    }

    function polishPage(root) {
        polishSessionBadge();
        polishModeLabels(root || document);
        polishDownloadLabels(root || document);
    }

    function start() {
        polishPage(document);
        if (!document.documentElement) return;

        new MutationObserver((mutations) => {
            polishSessionBadge();
            mutations.forEach((mutation) => {
                if (mutation.type === 'characterData') {
                    polishModeTextNode(mutation.target);
                    polishDownloadTextNode(mutation.target);
                    return;
                }
                mutation.addedNodes.forEach((node) => {
                    polishModeLabels(node);
                    polishDownloadLabels(node);
                });
            });
        }).observe(document.documentElement, {
            childList: true,
            characterData: true,
            subtree: true
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
