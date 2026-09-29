(() => {
    'use strict';

    const TEXTAREA_ID = 'textarea-quick-prompts';
    const ADD_BUTTON_ID = 'btn-add-bulk-prompts';
    const COUNT_ID = 'paragraph-prompt-count';
    const STORAGE_KEY = 'ctb_saved_prompts';

    /**
     * Blank lines separate prompts. Single line breaks stay inside the same
     * prompt so a multi-line paragraph keeps its original structure.
     */
    function parseParagraphs(value) {
        const normalized = String(value ?? '')
            .replace(/\r\n?/g, '\n')
            .trim();

        if (!normalized) return [];

        return normalized
            .split(/\n(?:[^\S\n]*\n)+/)
            .map(paragraph => paragraph.trim())
            .filter(Boolean);
    }

    function createCountUi(textarea) {
        textarea.placeholder = 'Paste prompts here. Leave one blank line between prompts...';

        const meta = document.createElement('div');
        meta.className = 'paragraph-prompt-meta';
        meta.setAttribute('aria-live', 'polite');
        meta.innerHTML = `
            <span class='paragraph-prompt-hint'>One paragraph = one prompt</span>
            <span class='paragraph-prompt-count'>Detected Prompts: <strong id='${COUNT_ID}'>0</strong></span>
        `;
        textarea.insertAdjacentElement('afterend', meta);

        return meta.querySelector(`#${COUNT_ID}`);
    }

    function initializeParagraphPrompts() {
        const textarea = document.getElementById(TEXTAREA_ID);
        const addButton = document.getElementById(ADD_BUTTON_ID);

        if (!textarea || !addButton) return;

        const count = document.getElementById(COUNT_ID) || createCountUi(textarea);

        if (!count) return;

        const updateCount = () => {
            count.textContent = String(parseParagraphs(textarea.value).length);
        };

        const showStorageError = error => {
            addButton.disabled = false;
            window.alert(`Could not add prompts: ${error?.message || String(error)}`);
        };

        const appendParagraphs = paragraphs => {
            addButton.disabled = true;

            chrome.storage.local.get([STORAGE_KEY], result => {
                const readError = chrome.runtime.lastError;
                if (readError) {
                    showStorageError(readError);
                    return;
                }

                const saved = Array.isArray(result?.[STORAGE_KEY])
                    ? result[STORAGE_KEY]
                    : [];
                const additions = paragraphs.map((text, index) => ({
                    title: `Prompt #${saved.length + index + 1}`,
                    text,
                    done: false
                }));
                const updated = [...saved, ...additions];

                chrome.storage.local.set({[STORAGE_KEY]: updated}, () => {
                    const writeError = chrome.runtime.lastError;
                    if (writeError) {
                        showStorageError(writeError);
                        return;
                    }

                    textarea.value = '';
                    addButton.disabled = false;
                    updateCount();

                    // Reload so the protected popup's private prompt array is
                    // rehydrated from the just-saved list before other actions.
                    const reloadEvent = new CustomEvent('ctb:prompts-saved', {
                        cancelable: true,
                        detail: {added: additions.length, total: updated.length}
                    });
                    if (document.dispatchEvent(reloadEvent)) window.location.reload();
                });
            });
        };

        textarea.addEventListener('input', updateCount);

        updateCount();

        // The protected popup initializes asynchronously after DOMContentLoaded.
        // Wait for its property handler, then replace only the quick-add path.
        // File upload keeps its original CSV/TXT replacement behavior.
        let attempts = 0;
        const wrapOriginalHandler = () => {
            const originalAddHandler = addButton.onclick;

            if (typeof originalAddHandler !== 'function') {
                attempts += 1;
                if (attempts < 200) window.setTimeout(wrapOriginalHandler, 25);
                return;
            }

            if (originalAddHandler.paragraphAware) return;

            function paragraphAwareAdd(event) {
                const paragraphs = parseParagraphs(textarea.value);

                if (!paragraphs.length) {
                    return originalAddHandler.call(this, event);
                }

                event?.preventDefault();
                appendParagraphs(paragraphs);
                return undefined;
            }

            Object.defineProperty(paragraphAwareAdd, 'paragraphAware', {value: true});
            addButton.onclick = paragraphAwareAdd;
        };

        wrapOriginalHandler();
    }

    window.CTBParagraphPrompts = Object.freeze({
        parseParagraphs
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeParagraphPrompts, {once: true});
    } else {
        initializeParagraphPrompts();
    }
})();
