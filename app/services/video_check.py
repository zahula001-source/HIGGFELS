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

def run_check_video_automation(task_id: str, profile_id: str, is_headless: bool = False, _already_tried_login: bool = False):
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
            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--restore-last-session",
                "--lang=vi-VN",
                "--accept-lang=vi-VN,vi",
            ]
            if os.environ.get("HIGGSFIELD_BROWSER_ENGINE") == "cloakbrowser":
                args.append("--fingerprint=" + str(profile.fingerprint.get("random_id", 123456)))
            
            ignore_args = []
            
            if is_headless:
                args.append("--window-position=-32000,-32000")
                args.append("--window-size=1366,768")
                
            try:
                from app.browser_settings import browser_launch_options
                b_opts = browser_launch_options()
            except:
                b_opts = {}

            context = p.chromium.launch_persistent_context(
                profile.user_data_dir,
                headless=False,
                channel="chrome" if not b_opts else None,
                ignore_default_args=ignore_args,
                args=args,
                accept_downloads=True,
                downloads_path=str(Path.home() / "Downloads"),
                **b_opts
            )
            
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
                    _req.post(f"http://127.0.0.1:5333/api/profiles/{profile_id}/launch", json={"headless": False})
                    time.sleep(8)
                    _req.post(f"http://127.0.0.1:5333/api/profiles/{profile_id}/auto-signup")
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
                    if p_obj and getattr(p_obj, 'notes', None) in ("không free", "free gen"):
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
                run_check_video_automation(task_id, profile_id, is_headless, _already_tried_login=True)
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
            
            while True:
                # Kiểm tra cờ dừng
                if video_tasks.get(task_id, {}).get("force_stop"):
                    video_tasks[task_id]["status"] = "error"
                    video_tasks[task_id]["message"] = "🛑 Đã dừng theo yêu cầu!"
                    context.close()
                    with pw_lock:
                        p.stop()
                    return
                # Lấy trạng thái hiện tại
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
                    # Trạng thái Processing → chờ
                    generating_start_time = None  # Reset nếu quay lại processing
                    generating_countdown_done = False
                    buffer_countdown_done = False
                    video_tasks[task_id]["message"] = "Đang chờ video tạo xong (Processing)..."
                    
                    # Cập nhật thẻ thành 'free gen'
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
                        video_tasks[task_id]["message"] = f"⏳ Sắp ra rồi! Còn khoảng {mins} phút {secs} giây nữa..."
                        if elapsed >= 900:
                            generating_countdown_done = True
                    elif not buffer_countdown_done:
                        # Hết 15 phút, đếm thêm 5 phút bù
                        extra_elapsed = elapsed - 900
                        remaining = max(0, 300 - extra_elapsed)
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        video_tasks[task_id]["message"] = f"⏳ Thêm chút nữa thôi! Bù giờ còn {mins} phút {secs} giây..."
                        if extra_elapsed >= 300:
                            buffer_countdown_done = True
                    else:
                        # Đã qua 20 phút vẫn chưa ra → vẫn chờ
                        video_tasks[task_id]["message"] = "⏳ Đang chờ video... (có thể mất thêm chút thời gian)"
                    
                    page.wait_for_timeout(3000)
                    
                elif status_info == 'done':
                    # Video đã xong!
                    video_tasks[task_id]["message"] = "✅ Video đã sẵn sàng, đang tải xuống..."
                    p_obj = manager.get_profile(profile_id)
                    if p_obj:
                        p_obj.notes = "không free"
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
                            p_obj.notes = "không free"
                            manager._save()
                        break
                    else:
                        video_tasks[task_id]["message"] = "Đang chờ video tạo xong..."
                        page.wait_for_timeout(3000)
                    
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
                except Exception as e:
                    video_tasks[task_id] = {"status": "error", "message": f"Lỗi khi tải video: {e}"}
            else:
                video_tasks[task_id] = {"status": "error", "message": "Không tìm thấy video nào!"}
                
            page.wait_for_timeout(2000)
            context.close()
            with pw_lock:
                p.stop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        video_tasks[task_id] = {"status": "error", "message": str(e)}

