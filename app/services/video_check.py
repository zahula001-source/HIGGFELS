import asyncio
import threading
import time
import os
import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Body, Request, Form
from fastapi.responses import FileResponse, JSONResponse

from app.core.state import pw_lock, video_tasks, video_tasks_chat, check_video_task_ids, MAX_RETRIES
from app.core.config import BASE_DIR, STATIC_DIR, DATA_DIR, PROFILES_FILE
from app.models import ProfileCreate, LaunchRequest
from app.manager import manager
from app.browser import launch_profile_with_fallback, close_profile, is_running, list_running
from app.browser_settings import browser_launch_options

def run_check_video_automation(task_id: str, profile_id: str, is_headless: bool = False, _already_tried_login: bool = False, cancel_first: bool = False, engine: str = "chrome"):
    from playwright.sync_api import sync_playwright
    import time, os
    from pathlib import Path
    
    video_tasks[task_id] = {"status": "running", "message": "Đang mở trình duyệt để kiểm tra..."}
    profile = manager.get_profile(profile_id)
    if not profile:
        video_tasks[task_id] = {"status": "error", "message": "Profile not found"}
        return
        
    try:
        with pw_lock:
            p = sync_playwright().start()
        if True:
            # Nếu chrome đang mở, ưu tiên dùng chrome đó
            from app.browser import prepare_chrome_136_profile
            runtime_dir = profile.user_data_dir if engine == "cloakbrowser" else prepare_chrome_136_profile(profile.user_data_dir)
            port_file = Path(runtime_dir) / "cdp_port.txt"
            context = None
            connected_via_cdp = False
            if port_file.exists():
                try:
                    port = int(port_file.read_text().strip())
                    browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
                    print(f"Đã kết nối vào Chrome đang mở của profile {profile.name} qua CDP port {port}")
                    context = browser.contexts[0]
                    connected_via_cdp = True
                except Exception as e:
                    pass
            
            if not context:
                args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--restore-last-session",
                    "--lang=vi-VN",
                    "--accept-lang=vi-VN,vi",
                ]
                if engine == "cloakbrowser":
                    args.append("--fingerprint=" + str(profile.fingerprint.get("random_id", 123456)))
                
                ignore_args = ["--disable-extensions"]
                extension_dirs = []
                
                # Tao extension doi ten tab
                try:
                    import json
                    from pathlib import Path
                    name_ext_dir = Path(runtime_dir) / "automation_extensions" / "name_tab"
                    name_ext_dir.mkdir(parents=True, exist_ok=True)
                    (name_ext_dir / "manifest.json").write_text(json.dumps({
                        "manifest_version": 3,
                        "name": "Profile Name Tab",
                        "version": "1.0",
                        "content_scripts": [{
                            "matches": ["<all_urls>"],
                            "js": ["content.js"],
                            "run_at": "document_idle"
                        }]
                    }), encoding="utf-8")
                    
                    js_code = "setInterval(() => { if (!document.title.startsWith('[' + " + repr(profile.name) + " + ']')) { document.title = '[' + " + repr(profile.name) + " + '] ' + document.title.replace(/^\\\\[.*?\\\\]\\\\s*/, ''); } }, 1000);"
                    (name_ext_dir / "content.js").write_text(js_code, encoding="utf-8")
                    
                    extension_dirs.append(str(name_ext_dir))
                except Exception as e:
                    print(f"Err creating name tab ext: {e}")

                try:
                    from app.extensions import resolve_extension_paths
                    extension_dirs.extend(resolve_extension_paths(profile.extensions, Path(runtime_dir)))
                except Exception as e:
                    print(f"Err loading profile extensions: {e}")
                extension_dirs = list(dict.fromkeys(extension_dirs))
                if extension_dirs:
                    joined_extensions = ",".join(extension_dirs)
                    args.append(f"--disable-extensions-except={joined_extensions}")
                    args.append(f"--load-extension={joined_extensions}")
                
                
                if is_headless:
                    args.append("--window-position=-32000,-32000")
                    args.append("--window-size=1366,768")
                    
                from app.browser_settings import get_algo_proxy
                raw_proxy = get_algo_proxy(profile.name)
                if raw_proxy:
                    from app.proxy_forwarder import start_forwarder
                    local_server = start_forwarder(raw_proxy)
                    algo_proxy = {"server": local_server}
                else:
                    algo_proxy = None

                try:
                    from app.browser_settings import browser_launch_options, get_global_args
                    args.extend(get_global_args(raw_proxy, engine=engine))
                    if engine == "cloakbrowser":
                        from app.browser_settings import BINARY
                        b_opts = {"executable_path": str(BINARY)}
                    else:
                        b_opts = browser_launch_options()
                except:
                    b_opts = {}

                args.append("--remote-debugging-port=0")
                
                # Xoá file port cũ để tránh đọc nhầm
                try:
                    active_port_file = Path(runtime_dir) / "DevToolsActivePort"
                    if active_port_file.exists(): active_port_file.unlink()
                    cdp_file = Path(runtime_dir) / "cdp_port.txt"
                    if cdp_file.exists(): cdp_file.unlink()
                except: pass
                
                context = p.chromium.launch_persistent_context(
                    runtime_dir,
                    headless=False,
                    proxy=algo_proxy,
                    channel="chrome" if not b_opts else None,
                    ignore_default_args=ignore_args,
                    args=args,
                    accept_downloads=True,
                    downloads_path=str(Path.home() / "Downloads"),
                    **b_opts
                )
                
                try:
                    import json
                    cfg = json.loads((Path(__file__).parent.parent.parent / 'data' / 'config.json').read_text())
                    if cfg.get('block_media'):
                        def block_media_route(route, request):
                            if request.resource_type in ['image', 'media', 'font'] and request.method == 'GET':
                                route.abort()
                            else:
                                route.continue_()
                        context.route('**/*', block_media_route)
                except: pass
                
                try:
                    import time
                    for _ in range(20):
                        active_port_file = Path(runtime_dir) / "DevToolsActivePort"
                        if active_port_file.exists():
                            lines_port = active_port_file.read_text().splitlines()
                            if lines_port:
                                Path(runtime_dir, "cdp_port.txt").write_text(lines_port[0])
                                break
                        time.sleep(0.5)
                except: pass
            
            # Tìm tab higgsfield.ai đã mở sẵn, nếu không có thì lấy tab đầu tiên
            page = None
            for pg in context.pages:
                if "higgsfield.ai" in pg.url:
                    page = pg
                    break
                    
            if not page:
                if context.pages:
                    page = context.pages[0]
                else:
                    page = context.new_page()
                    
            # Đóng tất cả các tab khác (bao gồm cả about:blank hoặc tab khôi phục)
            for pg in context.pages:
                if pg != page:
                    try: pg.close()
                    except: pass
            
            try: page.bring_to_front()
            except: pass
            
            # Thêm script tự động đóng popup liên tục
            try:
                page.evaluate("""() => {
                    if (window._popupIntervalId) return;
                    window._popupIntervalId = setInterval(() => {
                        const dialogs = document.querySelectorAll('div[role="dialog"]');
                        for (let dialog of dialogs) {
                            const text = dialog.innerText || "";
                            if (text.includes('Claim Free Generation') || text.includes('Explore styles') || text.includes('RESTYLE') || text.includes('New in Genjutsu') || text.includes('Restyle')) {
                                const closeBtn = dialog.querySelector('button[aria-label="Close"], button[aria-label*="close"], button svg.lucide-x') || dialog.querySelector('button.absolute');
                                if (closeBtn) {
                                    try { closeBtn.click(); } catch(e) {}
                                }
                            }
                        }
                    }, 1000);
                }""")
            except: pass
            page.add_init_script("""
                setInterval(() => {
                    const dialogs = document.querySelectorAll('div[role="dialog"]');
                    for (let dialog of dialogs) {
                        const text = dialog.innerText || "";
                        if (text.includes('Claim Free Generation') || text.includes('Explore styles') || text.includes('RESTYLE') || text.includes('New in Genjutsu') || text.includes('Restyle')) {
                            const closeBtn = dialog.querySelector('button[aria-label="Close"], button[aria-label*="close"], button svg.lucide-x') || dialog.querySelector('button.absolute');
                            if (closeBtn) {
                                try { closeBtn.click(); } catch(e) {}
                            }
                        }
                    }
                }, 1000);
            """)
            
            video_tasks[task_id]["message"] = "Đang vào trang Genjutsu..."
            page.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=60000)
            
            # Wait a bit
            page.wait_for_timeout(5000)
            
            # CHECK CHƯA LOGIN -> GỌI AUTO LOGIN
            is_not_logged_in = False
            if "auth/sign-in" in page.url or "login" in page.url:
                is_not_logged_in = True
            elif page.locator("a:has-text('Login'), button:has-text('Login'), a:has-text('Log In'), button:has-text('Log In')").count() > 0:
                is_not_logged_in = True
            elif page.locator("button:has-text('Continue with Microsoft')").count() > 0:
                is_not_logged_in = True
                
            if is_not_logged_in:
                # Nếu đã thử login 1 lần rồi mà vẫn chưa login → báo lỗi, không retry nữa
                if _already_tried_login:
                    video_tasks[task_id]["status"] = "error"
                    video_tasks[task_id]["message"] = "❌ Đã thử Auto Login nhưng vẫn chưa đăng nhập được!"
                    try: context.close()
                    except: pass
                    with pw_lock: p.stop()
                    return

                video_tasks[task_id]["message"] = "Chưa login, đang tự động đăng nhập..."
                try: context.close()
                except: pass
                with pw_lock: p.stop()
                
                import requests as _req
                try:
                    video_tasks[task_id]["message"] = "🔑 Đang chạy Auto Login, vui lòng chờ..."
                    _req.post(
                        f"http://127.0.0.1:5333/api/profiles/{profile_id}/launch",
                        json={"headless": False, "engine": engine},
                    )
                    time.sleep(8)
                    _req.post(
                        f"http://127.0.0.1:5333/api/profiles/{profile_id}/auto-signup",
                        params={"engine": engine},
                    )
                except Exception as e:
                    video_tasks[task_id]["status"] = "error"
                    video_tasks[task_id]["message"] = f"Lỗi gọi auto login: {e}"
                    return

                # Chờ auto login hoàn tất (tối đa 3 phút)
                video_tasks[task_id]["message"] = "⏳ Đang chờ đăng nhập hoàn tất..."
                waited = 0
                while waited < 180:
                    time.sleep(5)
                    waited += 5
                    # Kiểm tra xem task auto-signup đã báo login xong chưa
                    # (profile sẽ được đóng Chrome sau khi auto-signup xong)
                    p_obj = manager.get_profile(profile_id)
                    if p_obj and getattr(p_obj, 'notes', None) in ("không free", "free gen", "đã ra video"):
                        # Profile đã được cập nhật → login xong
                        break
                    # Cũng thoát nếu bị force stop
                    if video_tasks.get(task_id, {}).get("force_stop"):
                        video_tasks[task_id]["status"] = "error"
                        video_tasks[task_id]["message"] = "🛑 Đã dừng theo yêu cầu!"
                        return

                # Sau khi login xong → tiếp tục check video (đánh dấu đã thử login để tránh loop)
                video_tasks[task_id]["message"] = "✅ Đăng nhập xong! Đang tiếp tục kiểm tra video..."
                time.sleep(3)
                run_check_video_automation(
                    task_id,
                    profile_id,
                    is_headless,
                    _already_tried_login=True,
                    engine=engine,
                )
                return
            
            video_tasks[task_id]["message"] = "Đang chuyển sang tab History..."
            try:
                # History is a span with class q-tabs-tab-label
                # Use a specific JS selector to click it reliably
                page.evaluate("""() => {
                    let tabs = document.querySelectorAll('span.q-tabs-tab-label');
                    for(let t of tabs) {
                        if(t.innerText.includes('History')) {
                            t.click();
                            return;
                        }
                    }
                }""")
                page.wait_for_timeout(3000)
            except Exception as e:
                print("Loi click History:", e)
                
            # XEM RA VIDEO CHUA
            video_tasks[task_id]["message"] = "Đang kiểm tra trạng thái video..."
            
            generating_start_time = None  # Thời điểm bắt đầu Generating
            generating_countdown_done = False  # Đã qua 15 phút chưa
            buffer_countdown_done = False  # Đã qua 5 phút bù chưa
            processing_start_time = None
            
            import random, time
            next_reload_time = time.time() + random.randint(240, 420)
            
            if cancel_first:
                video_tasks[task_id]["cancel_and_gen_requested"] = True
                
            while True:
                try:
                    # Kiểm tra cờ dừng
                    if video_tasks.get(task_id, {}).get("force_stop"):
                        video_tasks[task_id]["status"] = "error"
                        video_tasks[task_id]["message"] = "🛑 Đã dừng theo yêu cầu!"
                        try: context.close()
                        except: pass
                        with pw_lock:
                            p.stop()
                        return
                    if video_tasks.get(task_id, {}).get("cancel_and_gen_requested"):
                        print(f"--- Task {task_id} (Check) nhận lệnh Cancel + Gen. Thực thi thao tác...")
                        video_tasks[task_id]["cancel_and_gen_requested"] = False
                        video_tasks[task_id] = {"status": "running", "message": "Đang thao tác Cancel & Gen lại..."}
                    
                        try:
                            # 1. Click Copy
                            print(f"--- Task {task_id} (Cancel+Gen): Đang tìm thẻ Processing và ép hiện nút Copy/Cancel...")
                            page.evaluate("""() => {
                                const procSpans = Array.from(document.querySelectorAll('span, div'));
                                const proc = procSpans.find(el => el.innerText && el.innerText.trim() === 'Processing');
                                if (proc) {
                                    let card = proc.closest('div.group\\\\/card');
                                    if (!card) card = proc.closest('section');
                                    if (!card) card = proc.closest('.v_list_row');
                                    if (card) {
                                        // Ép hiển thị thanh công cụ
                                        const style = document.createElement('style');
                                        style.innerHTML = 'div[id^="action-panel"], div[class*="opacity-0"] { opacity: 1 !important; pointer-events: auto !important; }';
                                        document.head.appendChild(style);
                                    
                                        const actionPanel = card.querySelector('#action-panel-bottom');
                                        if (actionPanel) {
                                            // Tìm tất cả các nút button bên trong bảng action-panel-bottom
                                            const btns = actionPanel.querySelectorAll('button');
                                            // Theo HTML user: btns[0] là Cancel, btns[1] là Copy, btns[2] là Trash
                                            if (btns.length >= 2) {
                                                const copyBtn = btns[1];
                                                copyBtn.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                                                copyBtn.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
                                                copyBtn.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
                                                copyBtn.click();
                                            }
                                        }
                                    }
                                }
                            }""")
                            print(f"--- Task {task_id} (Cancel+Gen): Đã click Copy prompt, đang đợi 3s để web nhận thông số...")
                            page.wait_for_timeout(3000)
                        
                            # 2. Click Cancel
                            print(f"--- Task {task_id} (Cancel+Gen): Đang click Cancel tiến trình...")
                            page.evaluate("""() => {
                                const procSpans = Array.from(document.querySelectorAll('span, div'));
                                const proc = procSpans.find(el => el.innerText && el.innerText.trim() === 'Processing');
                                if (proc) {
                                    let card = proc.closest('div.group\\\\/card');
                                    if (!card) card = proc.closest('section');
                                    if (!card) card = proc.closest('.v_list_row');
                                    if (card) {
                                        const actionPanel = card.querySelector('#action-panel-bottom');
                                        if (actionPanel) {
                                            const btns = actionPanel.querySelectorAll('button');
                                            if (btns.length >= 1) {
                                                const cancelBtn = btns[0];
                                                cancelBtn.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
                                                cancelBtn.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
                                                cancelBtn.click();
                                            }
                                        }
                                    }
                                }
                            }""")
                            page.wait_for_timeout(2000)
                        
                            # 3. Click Confirm
                            print(f"--- Task {task_id} (Cancel+Gen): Đang click Confirm xác nhận huỷ...")
                            page.evaluate("""() => {
                                const btns = Array.from(document.querySelectorAll('button'));
                                const confirm = btns.find(b => b.innerText && b.innerText.includes('Confirm'));
                                if (confirm) confirm.click();
                            }""")
                            page.wait_for_timeout(4000)
                        
                            # 4. Tải lại trang, Check Free Gens, và Click Generate (Có retry)
                            for retry_gen in range(3):
                                print(f"--- Task {task_id} (Cancel+Gen): Đang reload lại trang (Lần {retry_gen + 1}/3)...")
                                page.reload()
                                page.wait_for_load_state('domcontentloaded')
                                print(f"--- Task {task_id} (Cancel+Gen): Đợi thêm 5s sau khi reload cho web load hẳn...")
                                page.wait_for_timeout(5000)
                            
                                # 5. Check Use free gens
                                print(f"--- Task {task_id} (Cancel+Gen): Kiểm tra công tắc 'Use free gens'...")
                                page.evaluate("""() => {
                                    const switches = Array.from(document.querySelectorAll('button[role="switch"]'));
                                    for (const sw of switches.reverse()) {
                                        let parent = sw.parentElement;
                                        let text = '';
                                        while (parent && parent.tagName !== 'BODY') {
                                            text = parent.innerText || '';
                                            if (text.includes('Use free gens')) {
                                                if (sw.getAttribute('aria-checked') !== 'true') {
                                                    sw.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
                                                    sw.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
                                                    sw.click();
                                                }
                                                return;
                                            }
                                            parent = parent.parentElement;
                                        }
                                    }
                                }""")
                                page.wait_for_timeout(2000)
                            
                                # 6. Click Generate
                                print(f"--- Task {task_id} (Cancel+Gen): Đang bấm nút Generate và chuyển về chế độ chờ...")
                                page.evaluate("""() => {
                                    const btns = Array.from(document.querySelectorAll('button'));
                                    const genBtn = btns.find(b => b.innerText && (b.innerText.includes('Generate') || b.innerText.includes('Tạo video')));
                                    if (genBtn && !genBtn.disabled) {
                                        genBtn.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
                                        genBtn.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
                                        genBtn.click();
                                    }
                                }""")
                                page.wait_for_timeout(4000)
                            
                                # Kiểm tra xem có Processing chưa
                                has_processing = page.evaluate("""() => {
                                    const spans = Array.from(document.querySelectorAll('span, div'));
                                    return spans.some(el => el.innerText && el.innerText.trim() === 'Processing');
                                }""")
                            
                                if has_processing:
                                    print(f"--- Task {task_id} (Cancel+Gen): ✅ Đã thấy thẻ Processing xuất hiện, quá trình tạo bắt đầu thành công!")
                                    break
                                else:
                                    print(f"--- Task {task_id} (Cancel+Gen): ❌ Chưa thấy thẻ Processing, thử lại quá trình tải trang và ấn Generate...")
                                
                            video_tasks[task_id] = {"status": "running", "message": "✅ Đã Cancel và Generate lại! Đang chờ..."}
                        except Exception as ex:
                            print(f"Lỗi khi thực thi Cancel + Gen trong Check: {ex}")
                            video_tasks[task_id] = {"status": "running", "message": f"⚠️ Lỗi Cancel + Gen: {str(ex)}"}
                    
                        continue
                
                    # Lấy trạng thái hiện tại
                    # Kiểm tra thời gian để tải lại trang định kỳ
                    if time.time() > next_reload_time:
                        print(f"--- Task {task_id}: Đã đến giờ reload định kỳ (Random +- 5 phút)...")
                        video_tasks[task_id]["message"] = f"🔄 Đang tải lại trang web để cập nhật tiến trình..."
                        try:
                            page.reload(timeout=30000)
                            page.wait_for_load_state('domcontentloaded')
                            page.wait_for_timeout(5000)
                        except: pass
                        next_reload_time = time.time() + random.randint(240, 420)
                        processing_start_time = time.time()
                        continue
                        
                    status_info = page.evaluate("""() => {
                        // Kiểm tra Processing
                        let spans = document.querySelectorAll('span');
                        for(let s of spans) {
                            if(s.innerText && s.innerText.trim() === 'Processing') return 'processing';
                        }
                        // Kiểm tra Generating
                        for(let s of spans) {
                            if(s.innerText && s.innerText.trim() === 'Generating') return 'generating';
                        }
                        // Kiểm tra video đã xong chưa (trong assets-grid)
                        let grid = document.getElementById('assets-grid');
                        if(grid) {
                            let completed = grid.querySelector('[data-job-status="completed"] video');
                            if(completed && completed.src && completed.src.includes('http')) return 'done';
                        }
                        return 'unknown';
                    }""")
                
                    now = time.time()
                
                    if status_info == 'processing':
                        if processing_start_time is None:
                            processing_start_time = now
                        elapsed_proc = now - processing_start_time
                        generating_start_time = None
                        generating_countdown_done = False
                        buffer_countdown_done = False
                    
                        if video_tasks[task_id].get("message", "").startswith("✅ Đã Cancel"):
                            video_tasks[task_id]["message"] = f"✅ Đã Cancel & Gen! Đang chờ Processing ({int(elapsed_proc)}s)..."
                        else:
                            video_tasks[task_id]["message"] = f"Đang chờ video tạo xong (Processing... {int(elapsed_proc)}s)"
                    
                        p_obj = manager.get_profile(profile_id)
                        if p_obj and p_obj.notes != "free gen":
                            p_obj.notes = "free gen"
                            manager._save()
                        
                        page.wait_for_timeout(3000)
                    
                    elif status_info == 'generating':
                        # Trạng thái Generating → bắt đầu đếm ngược
                        if generating_start_time is None:
                            generating_start_time = now
                            generating_countdown_done = False
                            buffer_countdown_done = False
                    
                        elapsed = now - generating_start_time
                    
                        if not generating_countdown_done:
                            # Đếm ngược 15 phút (900 giây)
                            remaining = max(0, 900 - elapsed)
                            mins = int(remaining // 60)
                            secs = int(remaining % 60)
                            video_tasks[task_id]["message"] = f'<span style="color: #c084fc; font-weight: bold;">⏳ Sắp ra rồi! Còn khoảng {mins} phút {secs} giây nữa... ( sắp ra rồi nhé )</span>'
                            if elapsed >= 900:
                                generating_countdown_done = True
                        else:
                            video_tasks[task_id]["message"] = f'<span style="color: #c084fc; font-weight: bold;">⏳ Đang chờ video... (Đã chờ {int(elapsed // 60)} phút) ( sắp ra rồi nhé )</span>'
                    
                        page.wait_for_timeout(3000)
                    
                    elif status_info == 'done':
                        # Video đã xong!
                        video_tasks[task_id]["message"] = "✅ Video đã sẵn sàng, đang tải xuống..."
                        p_obj = manager.get_profile(profile_id)
                        if p_obj:
                            p_obj.notes = "đã ra video"
                            manager._save()
                        break
                    else:
                        # Không rõ trạng thái → kiểm tra thêm xem có video chưa
                        has_video = page.evaluate("""() => {
                            let grid = document.getElementById('assets-grid');
                            if(grid) {
                                let completed = grid.querySelector('[data-job-status="completed"] video');
                                if(completed && completed.src && completed.src.includes('http')) return true;
                            }
                            return false;
                        }""")
                        if has_video:
                            video_tasks[task_id]["message"] = "✅ Video đã sẵn sàng, đang tải xuống..."
                            p_obj = manager.get_profile(profile_id)
                            if p_obj:
                                p_obj.notes = "đã ra video"
                                manager._save()
                            break
                        else:
                            video_tasks[task_id]["message"] = "Đang chờ video tạo xong..."
                            page.wait_for_timeout(3000)
                        
                except Exception as ex:
                    err_str = str(ex)
                    if "Execution context was destroyed" in err_str:
                        page.wait_for_timeout(3000)
                        continue
                    elif "Target closed" in err_str or "Browser closed" in err_str or "has been closed" in err_str:
                        print(f"--- Task {task_id}: Trình duyệt đã bị đóng, ngưng chờ video.")
                        video_tasks[task_id]["status"] = "error"
                        video_tasks[task_id]["message"] = "🛑 Trình duyệt đã bị đóng, ngưng chờ video!"
                        return
                    else:
                        print(f"--- Task {task_id}: Lỗi khi kiểm tra video: {ex}")
                        page.wait_for_timeout(3000)
                        continue
                        
            page.wait_for_timeout(2000)
            
            # Get Video URLs - CHỈ LẤY VIDEO TRONG assets-grid (video kết quả thật)
            video_urls = page.evaluate("""() => {
                let urls = [];
                // Ưu tiên lấy từ #assets-grid với data-job-status="completed"
                let grid = document.getElementById('assets-grid');
                if(grid) {
                    let cells = grid.querySelectorAll('[data-job-status="completed"]');
                    for(let cell of cells) {
                        let v = cell.querySelector('video');
                        if(v && v.src && v.src.includes('http') && !v.src.includes('blob:')) {
                            urls.push(v.src);
                        } else if(v && v.src && v.src.includes('blob:')) {
                            urls.push(v.src);
                        }
                    }
                }
                // Nếu không tìm được trong grid, fallback lấy video từ history có URL cloudfront/cdn
                if(urls.length === 0) {
                    document.querySelectorAll('video').forEach(v => {
                        if(v.src && v.src.includes('cloudfront.net')) urls.push(v.src);
                        if(v.src && v.src.includes('higgsfield') && v.src.includes('.mp4')) urls.push(v.src);
                    });
                }
                return [...new Set(urls)];
            }""")
            
            if video_urls:
                import urllib.parse
                out_dir = Path.home() / "Downloads"
                all_result_urls = []
                try:
                    for v_idx, v_url in enumerate(video_urls[:1]): # Get latest 1
                        video_url = v_url
                        out_file = out_dir / (f"{task_id}.mp4")
                        if video_url.startswith("blob:"):
                            b64_data = page.evaluate("""async (url) => {
                                const response = await fetch(url);
                                const blob = await response.blob();
                                return new Promise((resolve, reject) => {
                                    const reader = new FileReader();
                                    reader.onloadend = () => resolve(reader.result);
                                    reader.onerror = reject;
                                    reader.readAsDataURL(blob);
                                });
                            }""", video_url)
                            import base64
                            header, encoded = b64_data.split(",", 1)
                            with open(out_file, "wb") as f:
                                f.write(base64.b64decode(encoded))
                        else:
                            ua = page.evaluate("navigator.userAgent")
                            resp = context.request.get(video_url, headers={
                                "User-Agent": ua,
                                "Referer": "https://higgsfield.ai/",
                                "Accept": "*/*"
                            })
                            with open(out_file, "wb") as f:
                                f.write(resp.body())
                                
                        all_urls = [f"/api/video/download/{task_id}?path={urllib.parse.quote(str(out_file))}"]
                        all_result_urls.extend(all_urls)
                        
                    video_tasks[task_id]["result_urls"] = all_result_urls
                    video_tasks[task_id]["status"] = "success"
                    video_tasks[task_id]["message"] = "Đã tải xong!"
                    # Cập nhật tag thành 'đã ra video' sau khi tải thành công
                    p_obj = manager.get_profile(profile_id)
                    if p_obj:
                        p_obj.notes = "đã ra video"
                        manager._save()
                except Exception as e:
                    video_tasks[task_id] = {"status": "error", "message": f"Lỗi khi tải video: {e}"}
            else:
                video_tasks[task_id] = {"status": "error", "message": "Không tìm thấy video nào!"}
                
            page.wait_for_timeout(2000)
            if not connected_via_cdp:
                try: context.close()
                except: pass
            with pw_lock:
                p.stop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        video_tasks[task_id] = {"status": "error", "message": str(e)}
        if "context" in locals() and not connected_via_cdp:
            try: context.close()
            except: pass

