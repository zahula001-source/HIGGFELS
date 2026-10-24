"""Select one visible quiz answer and verify it before advancing."""
import time


QUIZ_OPTIONS = (
    "Trending presets & apps", "Video generations", "Voiceover, music & dubbing",
    "Lipsync & Talking avatars", "Upscale", "Realistic AI avatars",
    "Image editing & Inpaint", "Image generations", "For personal use", "Viral content",
    "Beginner", "Intermediate", "Advanced", "Expert", "Instagram", "TikTok", "YouTube",
    "I'm new to this", "Prompting is hard", "Canvas", "MCP & CLI", "Marketing Studio",
    "Shorts studio", "Cinema Studio", "Supercomputer", "Viral content & UGC videos",
    "High-converting marketing", "Just exploring", "Cinematic visuals & AI films",
    "Create avatars & product visuals", "Automate workflows with Supercomputer & MCP/CLI",
    "For my team/organization", "Just me", "2-5", "6-20", "21-100", "100+",
    "Automate our workflow with Supercomputer & MCP/CLI", "Produce content at scale across the team",
    "Custom terms & pricing", "Certifications (SOC 2, GDPR)", "Security & legal compliance",
    "Personal support & AI educator", "No training on your data", "Shared team workspace",
    "Video", "Visual editing",
    "Cinema studio", "AI Influencer", "Higgsfield Genjutsu", "Seedance 2.5", "Ads Studio",
)

_SNAPSHOT = r"""options => {
    const norm = text => (text || '').replace(/\s+/g, ' ').trim();
    const visible = el => {
        if (!el || !el.getClientRects().length) return false;
        for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
            const style = getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        }
        return true;
    };
    const enabled = el => !el.disabled && el.getAttribute('aria-disabled') !== 'true';
    const labels = [...options].sort((a, b) => b.length - a.length);
    const answerLabel = el => {
        // innerText preserves the space between a block title and subtitle.
        // textContent joins them on the newer personal/team cards.
        const rendered = norm(el.innerText);
        const renderedLabel = labels.find(label => rendered === label || rendered.startsWith(label + ' '));
        if (renderedLabel) return renderedLabel;
        const clone = el.cloneNode(true);
        clone.querySelectorAll('svg, .text-q-body-sm-regular').forEach(node => node.remove());
        const text = norm(clone.textContent);
        return labels.find(label => text === label || text.startsWith(label + ' '))
            || labels.find(label => [...el.querySelectorAll('span, p, div')].some(node => norm(node.textContent) === label)) || '';
    };
    const answerSelector = 'button, [role="button"], [role="radio"], label, [tabindex="0"], div.cursor-pointer';
    const isAnswer = el => visible(el) && !el.closest('a, nav, header') && answerLabel(el);
    const headings = [...document.querySelectorAll('h1, h2')].filter(visible);
    const heading = headings.find(el => /(?:how do you plan.*use higgsfield|what do you want.*(?:achieve with|try on) higgsfield)/i.test(norm(el.innerText)))
        || headings[0];
    let root = heading?.closest('[data-quiz-mobile-question="true"]');
    if (!root && heading) {
        root = heading.parentElement;
        while (root.parentElement && ![...root.querySelectorAll(answerSelector)].some(isAnswer)) root = root.parentElement;
    }
    root ||= document.body;
    document.querySelectorAll('[data-hf-quiz-option], [data-hf-quiz-next]').forEach(el => {
        el.removeAttribute('data-hf-quiz-option'); el.removeAttribute('data-hf-quiz-next');
    });
    const found = [];
    for (const el of root.querySelectorAll(answerSelector)) {
        if (!isAnswer(el) || found.some(item => item.element.contains(el))) continue;
        const wrapper = el.closest('.relative.min-w-0') || el.parentElement;
        const checkedSelector = '[role="checkbox"][aria-checked="true"], [role="radio"][aria-checked="true"], input[type="checkbox"]:checked, input[type="radio"]:checked';
        // A row can contain multiple cards; a sibling's radio is not ours.
        const checked = el.querySelector(checkedSelector) || (wrapper?.querySelectorAll(answerSelector).length === 1 && wrapper.querySelector(checkedSelector));
        const selected = el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-checked') === 'true'
            || el.getAttribute('data-state') === 'checked' || el.getAttribute('data-selected') === 'true' || !!checked;
        const marker = 'answer-' + found.length;
        el.setAttribute('data-hf-quiz-option', marker);
        found.push({element:el, marker, text:answerLabel(el), selected, enabled:enabled(el)});
    }
    const nextSelector = 'button, [role="button"], input[type="submit"]';
    // On mobile the fixed Continue bar is a sibling of the question, and on
    // desktop the footer can be outside it too. Always check the visible UI.
    const nextCandidates = [
        ...document.querySelectorAll('[data-quiz-mobile-continue="true"] button, [data-quiz-mobile-continue="true"] [role="button"]'),
        ...root.querySelectorAll(nextSelector),
        ...document.querySelectorAll(nextSelector),
    ];
    const next = nextCandidates.find(el => {
        const text = norm(el.innerText || el.value || el.textContent);
        return visible(el) && enabled(el) && !el.closest('nav, header')
            && /^(continue|next|submit|choose(?: an option)?|finish|get started)$/i.test(text);
    });
    if (next) next.setAttribute('data-hf-quiz-next', 'true');
    const progress = [...document.querySelectorAll('span, p, div')].find(el => visible(el) && /^\d+\s+of\s+\d+$/i.test(norm(el.innerText)));
    return {
        url:location.href,
        step:[location.href, norm(heading?.textContent), norm(progress?.innerText), found.map(item => item.text).sort().join('|')].join('\n'),
        options:found.map(({element, ...item}) => item), next:!!next
    };
}"""


def _snapshot(page):
    return page.evaluate(_SNAPSHOT, list(QUIZ_OPTIONS))


def _wait_for_change(page, before, answer=None, timeout_ms=900):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        current = _snapshot(page)
        if current["step"] != before["step"]:
            return "advanced"
        if answer and any(item["text"] == answer and item["selected"] for item in current["options"]):
            return "selected"
        if answer and current["next"] and not before["next"]:
            return "ready"
        page.wait_for_timeout(100)
    return ""


def _click(page, locator, strategy):
    if strategy == "locator":
        locator.click(timeout=900)
    elif strategy == "mouse":
        locator.scroll_into_view_if_needed(timeout=900)
        box = locator.bounding_box(timeout=900)
        if box:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    else:
        locator.evaluate("el => { if (el.isConnected && !el.disabled && el.getAttribute('aria-disabled') !== 'true') el.click(); }")


def handle_quiz_step(page, state=None, log=print):
    """Retry missed clicks; never toggle a selected answer or blacklist a missed one."""
    state = state if state is not None else {}
    try:
        before = _snapshot(page)
        if state.get("step") != before["step"]:
            state.clear()
            state["step"] = before["step"]
            state["step_since"] = time.monotonic()
            log(f"Quiz: đang xử lý {before['step'].splitlines()[1] or 'câu hỏi onboarding'}")
        if not before["options"] and not before["next"] and time.monotonic() - state.get("last_wait_log", state["step_since"]) >= 10:
            log("Quiz: chưa nhận diện được lựa chọn/nút tiếp tục, đang chờ giao diện tải xong.")
            state["last_wait_log"] = time.monotonic()
        selected = any(item["selected"] for item in before["options"])
        candidates = [item for item in before["options"] if item["enabled"]]
        # An enabled Continue is ready to advance even if the site's selected
        # card uses a label or state attribute we do not recognize yet.
        if before["options"] and not selected and not before["next"]:
            if not candidates:
                return False  # Hydration/animation has not enabled the cards yet.
            choice = next((item for label in ("For personal use", "Just exploring")
                           for item in candidates if item["text"] == label), candidates[0])["text"]
            for strategy in ("locator", "mouse", "javascript"):
                current = _snapshot(page)
                if current["step"] != before["step"]:
                    return True
                if any(item["selected"] for item in current["options"]) or current["next"]:
                    selected = True
                    break
                target = next((item for item in current["options"] if item["text"] == choice and item["enabled"]), None)
                if not target:
                    continue
                try:
                    _click(page, page.locator(f'[data-hf-quiz-option="{target["marker"]}"]'), strategy)
                except Exception:
                    pass
                result = _wait_for_change(page, before, choice)
                if result == "advanced":
                    log(f"Quiz: đã chọn '{choice}' và chuyển câu hỏi ({strategy})")
                    return True
                if result in ("selected", "ready"):
                    selected = True
                    log(f"Quiz: đã xác nhận chọn '{choice}' ({strategy})")
                    break
            if not selected and not _snapshot(page)["next"]:
                return False

        # A selected answer may render Continue a little later. Leave it selected.
        current = _snapshot(page)
        if current["step"] != before["step"]:
            return True
        if not current["next"]:
            return selected
        if time.monotonic() - state.get("next_attempt_at", 0) < 1.5:
            return selected
        for strategy in ("locator", "mouse", "javascript"):
            current = _snapshot(page)
            if current["step"] != before["step"]:
                return True
            if not current["next"]:
                return selected
            state["next_attempt_at"] = time.monotonic()
            try:
                _click(page, page.locator('[data-hf-quiz-next="true"]'), strategy)
            except Exception:
                pass
            if _wait_for_change(page, before) == "advanced":
                log(f"Quiz: đã bấm Continue/Next và chuyển sang bước tiếp theo ({strategy})")
                return True
        return selected
    except Exception as error:
        log(f"Quiz: giao diện đang thay đổi, sẽ thử lại: {error}")
        return False
