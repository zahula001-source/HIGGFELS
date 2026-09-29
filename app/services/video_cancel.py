import threading
import uuid
from pydantic import BaseModel
from fastapi import APIRouter
from pathlib import Path

from app.core.state import video_tasks
from app.manager import manager
from app.browser_settings import browser_launch_options

def run_cancel_gen_automation(profile_id: str, is_headless: bool, task_id: str):
    import time
    from playwright.sync_api import sync_playwright
    import os

    try:
        profile = manager.get_profile(profile_id)
        if not profile:
            raise Exception("Không tìm thấy profile")

        video_tasks[task_id] = {"status": "running", "message": "Đang mở Chrome để Cancel..."}

        engine = os.environ.get("HIGGSFIELD_BROWSER_ENGINE", "chrome").lower()
        if engine == "cloakbrowser":
            # Nếu dùng cloakbrowser, kết nối qua CDP hoặc launch
            port_file = Path(profile.user_data_dir) / "cdp_port.txt"
            connected = False
            if port_file.exists():
                latest_port = int(port_file.read_text().strip())
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.connect_over_cdp(f"http://localhost:{latest_port}")
                        context = browser.contexts[0]
                        _do_cancel(context, task_id)
                        connected = True
                except Exception as cdp_err:
                    print(f"Lỗi connect CDP (Cancel gen): {cdp_err}")
            
            if not connected:
                from cloakbrowser import launch_persistent_context
                cloak_kwargs = {
                    "user_data_dir": profile.user_data_dir,
                    "headless": is_headless,
                    "args": [],
                    "accept_downloads": True,
                    "downloads_path": str(Path.home() / "Downloads")
                }
                with launch_persistent_context(**cloak_kwargs) as context:
                    _do_cancel(context, task_id)
        else:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    profile.user_data_dir,
                    headless=is_headless,
                    **browser_launch_options()
                )
                _do_cancel(context, task_id)
                
    except Exception as e:
        video_tasks[task_id] = {"status": "error", "message": str(e)}

def _do_cancel(context, task_id):
    page = None
    # Tìm page có higgsfield
    for p in context.pages:
        if "higgsfield.ai" in p.url:
            page = p
            break
            
    if not page:
        page = context.new_page()
        page.goto("https://higgsfield.ai/ai/video?model=genjutsu")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
    else:
        page.bring_to_front()

    video_tasks[task_id] = {"status": "running", "message": "Đang thao tác Cancel & Gen lại..."}
    
    # 1. Ấn vào text chứa — MAN, the replacement MAN để reload
    page.evaluate("""() => {
        const textElements = Array.from(document.querySelectorAll('span, p, div'));
        const target = textElements.find(el => el.innerText && el.innerText.includes('— MAN, the replacement MAN'));
        if (target) {
            target.click();
        }
    }""")
    page.wait_for_timeout(2000)
    
    # 2. Tìm thẻ Processing và hover, click Cancel
    page.evaluate("""() => {
        // Tìm thẻ đang processing
        const processingSpans = Array.from(document.querySelectorAll('span'));
        const proc = processingSpans.find(el => el.innerText && el.innerText.trim() === 'Processing');
        if (proc) {
            const card = proc.closest('section');
            if (card) {
                // Hover vào card
                card.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                
                // Đợi 1 tí để hiện Cancel
                setTimeout(() => {
                    const btns = Array.from(card.querySelectorAll('button'));
                    const cancelBtn = btns.find(b => b.innerText && b.innerText.includes('Cancel') || b.getAttribute('aria-label') === 'Cancel');
                    if(cancelBtn) cancelBtn.click();
                }, 500);
            }
        }
    }""")
    page.wait_for_timeout(2000)
    
    # 3. Click Confirm
    page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const confirm = btns.find(b => b.innerText && b.innerText.includes('Confirm'));
        if (confirm) confirm.click();
    }""")
    page.wait_for_timeout(4000)
    
    # 4. Check Use free gens
    page.evaluate("""() => {
        const labels = Array.from(document.querySelectorAll('label'));
        const freeLabel = labels.find(l => l.innerText && l.innerText.includes('Use free gens'));
        if (freeLabel) {
            const toggle = freeLabel.parentElement.querySelector('button[role="switch"]');
            if (toggle && toggle.getAttribute('aria-checked') !== 'true') {
                toggle.click();
            }
        }
    }""")
    page.wait_for_timeout(1000)
    
    # 5. Click Generate
    page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const genBtn = btns.find(b => b.innerText && (b.innerText.trim() === 'Generate' || b.innerText.trim() === 'Tạo video'));
        if (genBtn && !genBtn.disabled) {
            genBtn.click();
        }
    }""")
    
    video_tasks[task_id] = {"status": "success", "message": "✅ Đã Cancel và Generate lại!"}
