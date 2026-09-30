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
from app.browser_settings import browser_launch_options, VERSION as CLOAK_VERSION

router = APIRouter()

@router.get("/api/profiles")
def get_profiles():
    profiles = manager.list_profiles()
    result = []
    for p in profiles:
        d = p.model_dump()
        d["running"] = is_running(p.id)
        d["browser_engine"] = os.environ.get("HIGGSFIELD_BROWSER_ENGINE", "chrome").lower()
        d["browser_version"] = CLOAK_VERSION if d["browser_engine"] == "cloakbrowser" else None
        # Đếm cookie imported
        cookie_file = Path(p.user_data_dir) / "imported_cookies.json"
        d["cookies_count"] = 0
        if cookie_file.exists():
            try:
                import json
                d["cookies_count"] = len(json.loads(cookie_file.read_text(encoding="utf-8")))
            except:
                pass
        # Tabs
        tabs_file = Path(p.user_data_dir) / "tabs.json"
        d["tabs_count"] = 0
        if tabs_file.exists():
            try:
                import json
                d["tabs_count"] = len(json.loads(tabs_file.read_text(encoding="utf-8")))
            except:
                pass
                
        # MS account
        ms_acc_file = Path(p.user_data_dir) / "ms_account.txt"
        d["ms_account"] = ""
        d["ms_email"] = ""
        if ms_acc_file.exists():
            try:
                acc_text = ms_acc_file.read_text(encoding="utf-8").strip()
                d["ms_account"] = acc_text
                d["ms_email"] = acc_text.split("|")[0].strip() if "|" in acc_text else acc_text
            except:
                pass
                
        result.append(d)
    return result

@router.post("/api/profiles")
def create_profile(data: ProfileCreate):
    name = data.name
    if not name or name.strip() == "":
        profiles = manager.list_profiles()
        max_id = len(profiles)
        import re
        for p in profiles:
            m = re.search(r'tk\s*(\d+)', p.name.lower())
            if m:
                num = int(m.group(1))
                if num > max_id:
                    max_id = num
        name = f"tk {max_id + 1}"
        
    profile = manager.create_profile(
        name=name,
        os=data.os,
        browser=data.browser,
        proxy=data.proxy,
        notes=data.notes,
        fingerprint_preset=data.fingerprint_preset
    )
    return profile.model_dump()

@router.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str):
    if is_running(profile_id):
        close_profile(profile_id)
    ok = manager.delete_profile(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"ok": True}

@router.post("/api/profiles/{profile_id}/duplicate")
def duplicate_profile(profile_id: str):
    new_p = manager.duplicate_profile(profile_id)
    if not new_p:
        raise HTTPException(404, "Profile not found")
    return new_p.model_dump()

@router.post("/api/profiles/{profile_id}/launch")
def launch_profile_endpoint(profile_id: str, req: LaunchRequest = None):
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
        
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            if task.get("params", {}).get("profile_id") == profile_id:
                raise HTTPException(400, f"Profile '{profile.name}' đang chạy ngầm để tạo Video. Vui lòng đợi tạo xong!")
                
    do_random = False
    if req and req.auto_random_fp:
        do_random = True
    elif getattr(profile, 'auto_random_fp', False):
        do_random = True
        
    if do_random:
        profile = manager.randomize_fingerprint(profile_id)

    result = launch_profile_with_fallback(profile, req)
    
    if result["status"] in ["launched", "already_running"]:
        try:
            # Auto login immediately when opening chrome
            # Nếu được gọi từ "Tạo acc + login", UI sẽ truyền keep_open_after_check=False
            keep_open_after = getattr(req, "keep_open_after_check", True) if req else True
            auto_signup_endpoint(profile_id, keep_open=keep_open_after)
        except Exception as e:
            print(f"Failed to trigger auto login: {e}")

    if result["status"] == "launched":
        manager.update_last_used(profile_id)
        return {"ok": True, "pid": result["pid"], "browser": profile.browser}
    elif result["status"] == "already_running":
        return {"ok": True, "message": "Already running", "pid": result["pid"]}
    else:
        raise HTTPException(500, result.get("message", "Launch failed"))

@router.post("/api/profiles/{profile_id}/auto-random-fp")
def toggle_auto_random_fp_endpoint(profile_id: str, payload: dict = Body(...)):
    state = payload.get("state", False)
    if manager.toggle_auto_random_fp(profile_id, state):
        return {"ok": True, "auto_random_fp": state}
    raise HTTPException(404, "Profile not found")

@router.post("/api/profiles/{profile_id}/close")
def close_profile_endpoint(profile_id: str):
    result = close_profile(profile_id)
    return result

def update_profile_name_endpoint(profile_id: str, payload: dict = Body(...)):
    new_name = payload.get("name")
    if not new_name:
        raise HTTPException(400, "Missing name")
    if manager.update_profile_name(profile_id, new_name):
        return {"ok": True}
    raise HTTPException(404, "Profile not found")

@router.post("/api/profiles/{profile_id}/random-fingerprint")
def random_fingerprint(profile_id: str):
    """Nút Random Fingerprint như BitBrowser - đổi ngay lập tức mà vẫn giữ cookie"""
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    
    was_running = is_running(profile_id)
    if was_running:
        close_profile(profile_id)
        import time
        time.sleep(1.5)
    
    new_p = manager.randomize_fingerprint(profile_id)
    
    # Nếu đang chạy thì mở lại luôn với fingerprint mới (giữ nguyên cookies)
    if was_running:
        result = launch_profile_with_fallback(new_p)
        if result["status"] == "launched":
            return {"ok": True, "message": f"Đã random fingerprint mới ({new_p.os}) và mở lại, cookies vẫn giữ!", "profile": new_p.model_dump(), "pid": result["pid"]}
        else:
            return {"ok": True, "message": f"Đã random fingerprint mới ({new_p.os}) nhưng lỗi mở lại: {result.get('message')}", "profile": new_p.model_dump()}
    
    return {"ok": True, "message": f"Đã random fingerprint mới: {new_p.os} - {new_p.fingerprint.get('random_id')}", "profile": new_p.model_dump()}

@router.post("/api/profiles/{profile_id}/import-cookies")
def import_cookies(profile_id: str, payload: dict = Body(...)):
    """Import cookies từ BitBrowser - dán JSON vào"""
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    
    cookies_raw = payload.get("cookies") or payload.get("cookie")
    if not cookies_raw:
        raise HTTPException(400, "Thiếu trường 'cookies' - dán JSON array từ BitBrowser")
    
    result = manager.import_cookies(profile_id, cookies_raw)
    if "error" in result:
        raise HTTPException(400, result["error"])
    
    # Nếu đang chạy thì báo cần restart
    if is_running(profile_id):
        result["need_restart"] = True
        result["message"] = f"Đã import {result['imported']}/{result['total']} cookies! Đóng và mở lại profile để cookie có hiệu lực (tabs vẫn giữ)."
    else:
        result["message"] = f"Đã import {result['imported']}/{result['total']} cookies! Mở profile lên là dùng được."
    
    return result

@router.get("/api/profiles/{profile_id}/export-cookies")
def export_cookies_endpoint(profile_id: str):
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    
    if is_running(profile_id):
        raise HTTPException(400, "Vui lòng ĐÓNG profile trước khi xuất cookie (Playwright đang lock thư mục)!")
    
    try:
        from playwright.sync_api import sync_playwright
        with pw_lock:
            p = sync_playwright().start()
        if True:
            # Mo headless browser de doc cookie
            context = p.chromium.launch_persistent_context(
                profile.user_data_dir, 
                headless=True,
                **browser_launch_options(),
                args=["--disable-blink-features=AutomationControlled"]
            )
            cookies = context.cookies()
            context.close()
            return {"ok": True, "cookies": cookies}
    except Exception as e:
        raise HTTPException(500, f"Lỗi đọc cookies: {e}")

@router.post("/api/export-bundle")
def export_bundle(payload: dict = Body(...)):
    """Xuất bundle JSON gồm nhiều profiles (profile info + ms_account + imported_cookies).
    payload: { profile_ids: [id1, id2, ...] }  - nếu rỗng thì xuất tất cả
    """
    profile_ids = payload.get("profile_ids", [])
    all_p = manager.list_profiles()
    if profile_ids:
        all_p = [p for p in all_p if p.id in profile_ids]
    
    bundle = []
    for p in all_p:
        entry = {
            "name": p.name,
            "os": p.os,
            "proxy": p.proxy,
            "notes": p.notes,
            "fingerprint": p.fingerprint,
            "ms_account": None,
            "imported_cookies": None,
        }
        # Đọc ms_account.txt
        ms_file = Path(p.user_data_dir) / "ms_account.txt"
        if ms_file.exists():
            entry["ms_account"] = ms_file.read_text(encoding="utf-8").strip()
        # Đọc imported_cookies.json
        cookie_file = Path(p.user_data_dir) / "imported_cookies.json"
        if cookie_file.exists():
            try:
                entry["imported_cookies"] = json.loads(cookie_file.read_text(encoding="utf-8"))
            except: pass
        bundle.append(entry)
    
    return {"ok": True, "count": len(bundle), "bundle": bundle}

@router.post("/api/import-bundle")
def import_bundle(payload: dict = Body(...)):
    """Nhập bundle JSON để tự động tạo profiles.
    payload: { bundle: [ {...}, {...} ] }
    """
    bundle = payload.get("bundle", [])
    if not bundle:
        raise HTTPException(400, "Bundle rỗng hoặc không hợp lệ")
    
    created = []
    errors = []
    for entry in bundle:
        try:
            name = entry.get("name", "Profile")
            from app.models import ProfileCreate
            
            pc = ProfileCreate(
                name=name,
                os=entry.get("os", "windows"),
                browser="chromium",
                proxy=entry.get("proxy"),
                notes=entry.get("notes", ""),
                fingerprint_preset=True
            )
            new_p = manager.create_profile(
                name=pc.name,
                os=pc.os,
                browser=pc.browser,
                proxy=pc.proxy,
                notes=pc.notes,
                fingerprint_preset=pc.fingerprint_preset
            )
            
            # Lưu ms_account.txt
            if entry.get("ms_account"):
                ms_file = Path(new_p.user_data_dir) / "ms_account.txt"
                ms_file.parent.mkdir(parents=True, exist_ok=True)
                ms_file.write_text(entry["ms_account"], encoding="utf-8")
            
            # Lưu imported_cookies.json
            if entry.get("imported_cookies"):
                manager.import_cookies(new_p.id, entry["imported_cookies"])
            
            created.append({"id": new_p.id, "name": new_p.name})
        except Exception as e:
            errors.append({"name": entry.get("name", "?"), "error": str(e)})
    
    return {"ok": True, "created": len(created), "profiles": created, "errors": errors}

@router.get("/api/profiles/{profile_id}/logs")
def get_logs(profile_id: str):
    log_file = BASE_DIR / "data" / "logs" / f"launch_{profile_id}.log"
    if not log_file.exists():
        return {"log": "Chưa có log"}
    return {"log": log_file.read_text(encoding="utf-8", errors="ignore")[-5000:]}

_running_signups = set()
_signup_lock = threading.Lock()

@router.post("/api/profiles/{profile_id}/auto-signup")
def auto_signup_endpoint(profile_id: str, keep_open: bool = False):
    import threading
    from pathlib import Path
    
    with _signup_lock:
        if profile_id in _running_signups:
            print(f"Bỏ qua: Auto signup cho profile {profile_id} đã đang chạy.")
            return {"ok": True, "message": "Auto Login đã đang chạy."}
        _running_signups.add(profile_id)
    
    profile = manager.get_profile(profile_id)
    if not profile: raise HTTPException(404, "Profile not found")
    
    port_file = Path(profile.user_data_dir) / "cdp_port.txt"
    if not port_file.exists():
        raise HTTPException(400, "Profile đang không chạy hoặc không có CDP port. Hãy mở lại Chrome!")
        
    try:
        port = int(port_file.read_text().strip())
    except:
        raise HTTPException(400, "Invalid CDP port.")

    def run_auto_signup():
        nonlocal keep_open
        try:
            from playwright.sync_api import sync_playwright
            with pw_lock:
                p = sync_playwright().start()
            if True:
                browser = None
                context = None
                # Thử connect nhiều lần để chờ browser khởi động xong (nếu bị gọi đồng thời với /launch)
                for attempt in range(10):
                    try:
                        port_file_latest = Path(profile.user_data_dir) / "cdp_port.txt"
                        if port_file_latest.exists():
                            latest_port = int(port_file_latest.read_text().strip())
                            browser = p.chromium.connect_over_cdp(f"http://localhost:{latest_port}")
                            context = browser.contexts[0]
                            break
                    except Exception as e:
                        print(f"Waiting for CDP port to be ready... ({e})")
                        import time
                        time.sleep(2)
                
                if not browser:
                    print("Auto signup: Không thể kết nối tới Chrome, vui lòng thử lại.")
                    try: p.stop()
                    except: pass
                    return
                    
                # Tìm tab đang ở trang higgsfield, nếu không có thì mở mới
                HIGGSFIELD_URL = "https://higgsfield.ai/ai/video?model=genjutsu"
                page = None
                try:
                    for pg in context.pages:
                        if not pg.is_closed() and ("higgsfield.ai" in pg.url or "login.microsoft" in pg.url or "login.live.com" in pg.url or "account.live.com" in pg.url):
                            page = pg
                            break
                    if not page:
                        # Thử dùng lại tab about:blank nếu có
                        for pg in context.pages:
                            if not pg.is_closed() and pg.url == "about:blank":
                                page = pg
                                break
                    if not page:
                        page = context.new_page()
                    
                    if "higgsfield.ai" not in page.url:
                        page.goto(HIGGSFIELD_URL, timeout=30000)
                        page.wait_for_load_state("domcontentloaded")
                    
                    page.bring_to_front()
                    page.wait_for_timeout(2000)
                    

                    
                    if "higgsfield.ai/auth/sign-in" in page.url:
                        print("Phát hiện đang ở trang auth/sign-in, giữ nguyên để tiếp tục...")
                        # Bỏ qua redirect để bấm nút trực tiếp
                except Exception as e:
                    print(f"Lỗi khi lấy/tạo tab Higgsfield: {e}")
                    try: p.stop()
                    except: pass
                    return
                
                # B1: Click nút Login hoặc Sign up (nếu đang ở trang chủ https://higgsfield.ai)
                ms_btn_visible = False
                try:
                    ms_btn_check = page.locator("button:has-text('Continue with Microsoft')")
                    if ms_btn_check.count() > 0 and ms_btn_check.first.is_visible(timeout=500):
                        ms_btn_visible = True
                except: pass

                if not ms_btn_visible and "auth/sign-in" not in page.url:
                    clicked_auth_btn = False
                    try:
                        login_btn = page.locator("a:has-text('Login'), button:has-text('Login')")
                        if login_btn.count() > 0 and login_btn.first.is_visible():
                            login_btn.first.click(timeout=2000, force=True)
                            clicked_auth_btn = True
                            print("Clicked Login button")
                    except: pass
                    
                    if not clicked_auth_btn:
                        try:
                            signup_btn = page.locator("a:has-text('Sign up'), button:has-text('Sign up')")
                            if signup_btn.count() > 0 and signup_btn.first.is_visible():
                                signup_btn.first.click(timeout=2000, force=True)
                                clicked_auth_btn = True
                                print("Clicked Sign up button")
                        except: pass
                    
                    if not clicked_auth_btn:
                        # Fallback: tìm bằng JS
                        try:
                            page.evaluate("""() => {
                                const els = document.querySelectorAll('a, button');
                                for (let el of els) {
                                    if (el.offsetWidth === 0 && el.offsetHeight === 0) continue;
                                    const t = (el.innerText || '').trim().toLowerCase();
                                    if (t === 'login' || t === 'sign up' || t === 'signup') {
                                        el.click();
                                        return;
                                    }
                                }
                            }""")
                            print("Clicked auth button via JS fallback")
                        except Exception as e:
                            print(f"Fallback click err (tab might be closed/navigating): {e}")
                
                # B2: Đợi popup "Welcome to Higgsfield" xuất hiện hoặc phát hiện đã login
                already_logged_in = False
                try:
                    for _ in range(15):
                        if "quiz" in page.url:
                            print("Đã phát hiện URL login sẵn (quiz), bỏ qua chờ popup!")
                            already_logged_in = True
                            break
                        # Check for logged-in indicators
                        if page.locator('text="Use free gens"').count() > 0 or page.locator('button[aria-haspopup="menu"]:has(img.rounded-full)').count() > 0:
                            print("Đã phát hiện avatar/free gens, đã login sẵn!")
                            already_logged_in = True
                            break
                        wel_loc = page.locator("text=Welcome to Higgsfield")
                        if wel_loc.count() > 0 and wel_loc.first.is_visible():
                            print("Welcome to Higgsfield popup appeared!")
                            break
                        page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"Lỗi chờ popup: {e}")
                
                page.wait_for_timeout(1000)
                
                if not already_logged_in:
                    # B3: Click "Continue with Microsoft"
                    try:
                        # Đóng popup Cookie nếu che mất giao diện
                        try:
                            cookie_btn = page.locator('.cc-allow, text="Chấp nhận tất cả Cookies", text="Accept all Cookies"').first
                            if cookie_btn.is_visible(timeout=500):
                                cookie_btn.click(force=True)
                                print("Closed Cookie popup on initial login")
                        except: pass
                        
                        ms_btn = page.locator("button:has-text('Continue with Microsoft')")
                        if ms_btn.count() > 0:
                            ms_btn.first.click(timeout=3000, force=True)
                            print("Clicked 'Continue with Microsoft'!")
                        else:
                            page.evaluate("""() => {
                                const btns = document.querySelectorAll('button');
                                for (let b of btns) {
                                    if ((b.innerText || '').includes('Continue with Microsoft')) {
                                        b.click();
                                        return;
                                    }
                                }
                            }""")
                            print("Clicked Microsoft via JS fallback")
                    except Exception as e:
                        print(f"Lỗi click Microsoft: {e}")
                    
                    # Đợi chuyển sang trang login.microsoftonline.com
                    page.wait_for_timeout(3000)
                    print(f"Current URL after click: {page.url}")
                    
                    # === Đọc thông tin tài khoản từ ms_account.txt ===
                    ms_acc_file = Path(profile.user_data_dir) / "ms_account.txt"
                    ms_email = None
                    ms_password = None
                    if ms_acc_file.exists():
                        try:
                            raw_acc = ms_acc_file.read_text(encoding="utf-8").strip()
                            parts_acc = raw_acc.split("|")
                            if len(parts_acc) >= 2:
                                ms_email = parts_acc[0].strip()
                                ms_password = parts_acc[1].strip()
                                print(f"Loaded MS account: {ms_email}")
                        except Exception as e:
                            print(f"Error reading ms_account.txt: {e}")
                    
                    if ms_email and ms_password:
                        # Đợi trang MS login hoặc trang higgsfield (nếu đã login)
                        try:
                            for _ in range(15):
                                u = page.url
                                if "login.microsoft" in u or "login.live" in u or "higgsfield.ai/quiz" in u or "higgsfield.ai/ai/video" in u:
                                    break
                                page.wait_for_timeout(1000)
                        except:
                            pass
                        
                        page.wait_for_timeout(2000)
                        print(f"MS login page URL: {page.url}")
                        
                        # Điền email vào ô input
                        try:
                            import time
                            if page.url.startswith("https://higgsfield.ai") or "account.live.com" in page.url or "fido" in page.url: 
                                raise ValueError("Already logged in or stuck on protection page, skipping email")
                            
                            # Đợi input xuất hiện
                            page.wait_for_selector('#i0116:not([type="hidden"])', state='visible', timeout=10000)
                            
                            # Dùng JavaScript để set giá trị và trigger Knockout binding (trang MS dùng Knockout.js)
                            filled = page.evaluate("""(email) => {
                                const el = document.getElementById('i0116');
                                if (!el) return false;
                                el.focus();
                                // Set native input value
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                nativeInputValueSetter.call(el, email);
                                // Trigger all necessary events for Knockout
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                                return el.value === email;
                            }""", ms_email)
                            
                            page.wait_for_timeout(800)
                            print(f"Filled email via JS: {ms_email} | success={filled}")
                            
                            # Click nút Tiếp theo / Next bằng JS - thử cả 2 kiểu button MS cũ và mới
                            clicked = page.evaluate("""() => {
                                // Trang cũ: input#idSIButton9
                                const btn1 = document.getElementById('idSIButton9');
                                if (btn1) { btn1.click(); return 'idSIButton9'; }
                                // Trang mới Fluent UI: button[data-testid=primaryButton]
                                const btn2 = document.querySelector('button[data-testid="primaryButton"]');
                                if (btn2) { btn2.click(); return 'primaryButton'; }
                                // Fallback: bất kỳ nút submit
                                const btn3 = document.querySelector('button[type="submit"], input[type="submit"]');
                                if (btn3) { btn3.click(); return 'submit'; }
                                return null;
                            }""")
                            print(f"Clicked Next after email via: {clicked}")
                            page.wait_for_timeout(3000)
                            
                        except Exception as e:
                            print(f"Error filling email: {e}")
                        
                        # Kiểm tra xem có bị chuyển hướng sang trang "Xác minh email của bạn" (chọn phương thức xác thực) không
                        # Nếu có, bấm "Sử dụng mật khẩu của bạn" để quay lại form mật khẩu
                        try:
                            page.wait_for_timeout(3000)
                            if page.url.startswith("https://higgsfield.ai") or "account.live.com" in page.url or "fido" in page.url: 
                                raise ValueError("Already logged in or stuck on protection page, skipping use password")
                            
                            # Sử dụng JS để tìm và click chính xác
                            clicked_pwd = page.evaluate("""() => {
                                const elements = document.querySelectorAll('span, a, div');
                                for (let el of elements) {
                                    const text = (el.innerText || '').trim();
                                    if (text === 'Sử dụng mật khẩu của bạn' || text === 'Use your password' || text.includes('Sử dụng mật khẩu')) {
                                        if (el.getAttribute('role') === 'button' || el.tagName === 'A' || el.tabIndex === 0) {
                                            el.click();
                                            return true;
                                        }
                                    }
                                }
                                return false;
                            }""")
                            
                            if clicked_pwd:
                                print("Clicked 'Sử dụng mật khẩu của bạn' (Use your password) via JS")
                                page.wait_for_timeout(2000)
                            else:
                                # Fallback bằng locator Playwright
                                use_pwd_btn = page.locator('span[role="button"]:has-text("Sử dụng mật khẩu của bạn"), span[role="button"]:has-text("Use your password"), a#iUsePasswordLink, a#idA_PWD_SwitchToPassword, a:has-text("Sử dụng mật khẩu của bạn")')
                                if use_pwd_btn.count() > 0 and use_pwd_btn.first.is_visible():
                                    use_pwd_btn.first.click(force=True)
                                    print("Clicked 'Sử dụng mật khẩu của bạn' (Use your password) via Locator")
                                    page.wait_for_timeout(2000)
                        except Exception as e:
                            print(f"Error checking 'Sử dụng mật khẩu': {e}")
                            pass
                            
                        # Điền mật khẩu
                        try:
                            if page.url.startswith("https://higgsfield.ai") or "account.live.com" in page.url or "fido" in page.url: 
                                raise ValueError("Already logged in or stuck on protection page, skipping password")
                            
                            # Đợi ô password xuất hiện
                            page.wait_for_selector('input[type="password"]', state='visible', timeout=10000)
                            
                            # Dùng JavaScript để set giá trị và trigger Knockout binding
                            filled_pwd = page.evaluate("""(pwd) => {
                                // Thử từng selector
                                const sel = ['#i0118', 'input[name="passwd"]', 'input[type="password"]:not(.moveOffScreen)', '#passwordEntry'];
                                let el = null;
                                for (const s of sel) {
                                    const found = document.querySelector(s);
                                    if (found && found.offsetParent !== null) { el = found; break; }
                                }
                                if (!el) return false;
                                el.focus();
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                nativeInputValueSetter.call(el, pwd);
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                                return el.value.length > 0;
                            }""", ms_password)
                            
                            page.wait_for_timeout(800)
                            print(f"Filled password via JS | success={filled_pwd}")
                            
                            # Click Sign in bằng JS - thử cả 2 kiểu button MS cũ và mới
                            clicked_signin = page.evaluate("""() => {
                                // Trang cũ: input#idSIButton9
                                const btn1 = document.getElementById('idSIButton9');
                                if (btn1) { btn1.click(); return 'idSIButton9'; }
                                // Trang mới Fluent UI: button[data-testid=primaryButton]
                                const btn2 = document.querySelector('button[data-testid="primaryButton"]');
                                if (btn2) { btn2.click(); return 'primaryButton'; }
                                // Fallback
                                const btn3 = document.querySelector('button[type="submit"], input[type="submit"]');
                                if (btn3) { btn3.click(); return 'submit'; }
                                return null;
                            }""")
                            print(f"Clicked Sign in after password via: {clicked_signin}")
                            page.wait_for_timeout(4000)
                        except Exception as e:
                            print(f"Error filling password: {e}")
                        
                        # === TinyHost API Helpers ===
                        import urllib.request, json as json_mod, re as re_mod, string, random as random_mod
                        
                        def tinyhost_get_random_domain():
                            """Lấy domain ngẫu nhiên từ TinyHost API"""
                            try:
                                req = urllib.request.Request("https://tinyhost.shop/api/random-domains/?limit=10")
                                with urllib.request.urlopen(req, timeout=10) as resp:
                                    data = json_mod.loads(resp.read().decode())
                                    domains = data.get("domains", [])
                                    if domains:
                                        return random_mod.choice(domains)
                            except Exception as e:
                                print(f"Error getting domain: {e}")
                            return "spacezin.space"  # fallback domain
                        
                        def tinyhost_check_inbox(domain, user, keyword="Mã bảo mật"):
                            """Poll inbox tìm email chứa keyword"""
                            try:
                                url = f"https://tinyhost.shop/api/email/{domain}/{user}/?limit=20"
                                req = urllib.request.Request(url)
                                with urllib.request.urlopen(req, timeout=10) as resp:
                                    data = json_mod.loads(resp.read().decode())
                                    emails = data.get("emails", [])
                                    for em in emails:
                                        subj = em.get("subject", "") or ""
                                        body = em.get("body", "") or ""
                                        if keyword.lower() in subj.lower() or keyword.lower() in body.lower() or "microsoft" in subj.lower():
                                            return em
                            except Exception as e:
                                print(f"Inbox check err: {e}")
                            return None
                        
                        def extract_otp_code(text):
                            """Trích xuất mã OTP 6 chữ số từ body email"""
                            m = re_mod.search(r'[Mm]ã bảo mật[:\s]+(\d{6})', text)
                            if m: return m.group(1)
                            m = re_mod.search(r'security code[:\s]+(\d{6})', text, re_mod.IGNORECASE)
                            if m: return m.group(1)
                            codes = re_mod.findall(r'\b(\d{6})\b', text)
                            if codes: return codes[0]
                            return None
                    else:
                        print("Không có thông tin tài khoản MS. Vui lòng bấm nút \'Dán mail\' để thêm tài khoản trước!")
                else:
                    print("Đã đăng nhập sẵn, bỏ qua các bước đăng nhập Microsoft.")
                    
                # === Vòng lặp toàn cầu xử lý các trang sau khi đăng nhập (Quiz, Yes/Accept, FIDO, Turnstile) ===
                print("Handling post-login popups...")
                global_quiz_clicked_options = set()
                quiz_completed = False
                for _ in range(30):
                    page.wait_for_timeout(2000)
                    
                    # Vòng lặp chính xử lý các form bật lên
                    
                    # Luôn kiểm tra và đóng popup Cookie nếu xuất hiện bất cứ lúc nào
                    try:
                        # Thẻ "Chấp nhận tất cả Cookies" là <a role="button" class="cc-allow"> — phải dùng JS click
                        cookie_clicked = page.evaluate("""() => {
                            const el = document.querySelector('a.cc-allow, .cc-allow, a.cc-btn.cc-allow');
                            if (el && el.offsetParent !== null) {
                                el.click();
                                return true;
                            }
                            return false;
                        }""")
                        if cookie_clicked:
                            print("Đã tự động click tắt thông báo Cookie!")
                    except: pass
                    
                    # Đóng popup quảng cáo Higgsfield "Plans with up to..." (nút X góc trên phải)
                    try:
                        promo_closed = page.evaluate("""() => {
                            // Chỉ tìm và click nút X nếu có chữ "Plans with up to" trên màn hình
                            if (!document.body.innerText.includes('Plans with up to')) {
                                return false;
                            }
                            
                            // Tìm nút X đóng popup (chứa SVG với path chéo X)
                            const btns = document.querySelectorAll('button, [role="button"]');
                            for (const btn of btns) {
                                const svg = btn.querySelector('svg');
                                if (!svg) continue;
                                const paths = svg.querySelectorAll('path');
                                for (const p of paths) {
                                    const d = p.getAttribute('d') || '';
                                    // Path của nút X: M7.75 7.75L16.25 16.25M16.25 7.75L7.75 16.25
                                    if (d.includes('7.75') && d.includes('16.25')) {
                                        btn.click();
                                        return true;
                                    }
                                }
                            }
                            // Fallback: tìm theo aria-label hoặc text gần "Plans with up to"
                            const overlay = document.querySelector('[data-testid="modal-close"], button[aria-label*="close"], button[aria-label*="Close"], button[aria-label*="Đóng"]');
                            if (overlay && overlay.offsetParent !== null) {
                                overlay.click();
                                return true;
                            }
                            return false;
                        }""")
                        if promo_closed:
                            print("Đã tắt popup quảng cáo Higgsfield!")
                    except: pass

                    
                    # ⚠️ LUÔN ĐỂ Ý: Nếu gặp thông báo lỗi "Couldn't save your answer" -> reload và làm tiếp
                    try:
                        error_texts = [
                            "Couldn't save your answer",
                            "Please try again",
                            "Something went wrong"
                        ]
                        for err_text in error_texts:
                            err_el = page.locator(f'text="{err_text}"')
                            if err_el.count() > 0 and err_el.first.is_visible(timeout=300):
                                print(f"⚠️ Phát hiện lỗi Quiz: '{err_text}' — Đang reload trang và làm tiếp...")
                                page.reload(wait_until="domcontentloaded", timeout=20000)
                                page.wait_for_timeout(3000)
                                continue
                    except: pass
                    
                    # Fix: Ngăn việc click đúp mở quá nhiều tab bằng cách chuyển sang tab mới nếu nó vừa được tạo ra
                    if len(context.pages) > 1:
                        for pg in context.pages:
                            if not pg.is_closed() and pg != page:
                                if "higgsfield.ai" in pg.url:
                                    print("Phát hiện tab mới được mở, chuyển sang tab mới và đóng tab cũ...")
                                    try: page.close()
                                    except: pass
                                    page = pg
                                    page.bring_to_front()
                                    break
                                    
                    cur_url = page.url
                    
                    if any(s in cur_url for s in ["/ai/video", "/supercomputer", "/canvas", "/cinema", "/marketing", "/shorts", "/mcp"]) and "quiz" not in cur_url:
                        # Đợi thêm 3s để chắc chắn React không redirect ngược về Quiz
                        page.wait_for_timeout(3000)
                        if "quiz" not in page.url:
                            print("Đã đăng nhập thành công vào Higgsfield!")
                            break
                        
                    # 0.5 Kiểm tra popup Congratulations (Upgrade promotion)
                    try:
                        # Dùng JS để chắc chắn tìm đúng — tránh selector không match
                        has_congrats = page.evaluate("""() => {
                            const html = document.body ? document.body.innerText : '';
                            return html.includes('Congratulations!') || html.includes('55% OFF') || html.includes('promocode is applied');
                        }""")
                        if has_congrats:
                            print("Đã gặp popup Congratulations! Đăng ký hoàn tất.")
                            quiz_completed = True
                            # Đóng popup bằng JS: tìm nút X trong dialog (thường là button con của dialog)
                            try:
                                closed = page.evaluate("""() => {
                                    // Tìm tất cả button trong dialog role
                                    const dialogs = document.querySelectorAll('[role="dialog"]');
                                    for (const d of dialogs) {
                                        const btns = d.querySelectorAll('button');
                                        for (const b of btns) {
                                            const txt = (b.innerText || b.textContent || '').trim();
                                            // Nút X: không có text, hoặc text là × hay X
                                            if (txt === '' || txt === '×' || txt === 'X' || txt === '✕') {
                                                b.click();
                                                return true;
                                            }
                                        }
                                        // Nếu không có nút X, tìm button đầu tiên nằm ngoài content
                                        const firstBtn = d.querySelector('button');
                                        if (firstBtn) { firstBtn.click(); return true; }
                                    }
                                    // Fallback: Escape
                                    return false;
                                }""")
                                if closed:
                                    print("Đã đóng popup Congratulations qua JS.")
                                else:
                                    page.keyboard.press("Escape")
                            except:
                                page.keyboard.press("Escape")
                            page.wait_for_timeout(1500)
                            break
                    except: pass
                        
                    # Xử lý trang Quiz (Khảo sát người dùng mới)
                    if "higgsfield.ai/quiz" in cur_url:

                        # 0. Kiểm tra lỗi "Couldn't save your answer"
                        try:
                            error_toast = page.locator('text="Couldn\'t save your answer"')
                            if error_toast.count() > 0 and error_toast.first.is_visible():
                                print("Quiz: Bị lỗi 'Couldn't save your answer', đang tải lại trang...")
                                page.reload()
                                page.wait_for_timeout(3000)
                                continue
                        except: pass

                        # 1. Bấm nút Chấp nhận Cookie nếu có
                        try:
                            page.evaluate("""() => {
                                const btns = document.querySelectorAll('button');
                                for(let b of btns) {
                                    if (b.innerText.includes('Chấp nhận tất cả') || b.innerText.includes('Accept all')) {
                                        b.click();
                                    }
                                }
                            }""")
                        except: pass
                        
                        # 1.5 Kiểm tra trang Claim Username (Bước cuối cùng)
                        try:
                            if page.locator('text="Claim your username"').count() > 0:
                                terms_label = page.locator('label:has-text("I agree to the Terms of Use")').first
                                if terms_label.count() > 0:
                                    # Click checkbox
                                    terms_box = terms_label.first.bounding_box()
                                    if terms_box:
                                        page.mouse.click(terms_box["x"] + 10, terms_box["y"] + terms_box["height"] / 2)
                                        print("Quiz: Tích chọn 'I agree to the Terms of Use'")
                                        page.wait_for_timeout(500)
                        except Exception as e:
                            pass

                        # 2. Click ngẫu nhiên các đáp án bằng Tọa độ chuột vật lý
                        quiz_options = [
                            "Trending presets & apps", "Video generations", 
                            "Voiceover, music & dubbing", "Lipsync & Talking avatars", "Upscale",
                            "Realistic AI avatars", "Image editing & Inpaint", "Image generations",
                            "For personal use", "Viral content", "Beginner", "Intermediate", "Advanced", "Expert",
                            "Instagram", "TikTok", "YouTube", 
                            "I'm new to this", "Prompting is hard",
                            "Canvas", "MCP & CLI", "Marketing Studio", "Shorts studio", "Cinema Studio", "Supercomputer",
                            "Viral content & UGC videos", "High-converting marketing", "Just exploring", 
                            "Cinematic visuals & AI films", "Create avatars & product visuals", 
                            "Automate workflows with Supercomputer & MCP/CLI", "For my team/organization",
                            "Just me", "2-5", "6-20", "21-100", "100+", 
                            "Automate our workflow with Supercomputer & MCP/CLI", "Produce content at scale across the team",
                            "Custom terms & pricing", "Certifications (SOC 2, GDPR)", "Security & legal compliance",
                            "Personal support & AI educator", "No training on your data", "Shared team workspace"
                        ]
                        import random
                        random.shuffle(quiz_options)

                        for q_text in quiz_options:
                            if q_text in global_quiz_clicked_options:
                                continue
                            try:
                                # 1. Ưu tiên Button / Role=Button
                                locs = page.locator(f'button:has-text("{q_text}"), div[role="button"]:has-text("{q_text}")')
                                target = None
                                if locs.count() > 0:
                                    target = locs.last
                                else:
                                    # 2. Fallback: Tìm thẻ div/span/label chứa chính xác đoạn text đó (tránh Header/Nav)
                                    exact_locs = page.locator(f'text="{q_text}"')
                                    for i in range(exact_locs.count()):
                                        el = exact_locs.nth(i)
                                        # Bỏ qua nếu là thẻ <a> (để tránh click nhầm link trên menu)
                                        tag_name = el.evaluate("el => el.tagName").upper()
                                        if tag_name != "A":
                                            target = el
                                            break
                                
                                if target and target.is_visible():
                                    target.scroll_into_view_if_needed()
                                    page.wait_for_timeout(200)
                                    box = target.bounding_box()
                                    if box:
                                        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                        print(f"Quiz: Mouse clicked option '{q_text}'")
                                        global_quiz_clicked_options.add(q_text)
                                        page.wait_for_timeout(800)
                                        
                                        cont_btn = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Choose an option"), button:has-text("Submit")').first
                                        if cont_btn.count() > 0 and not cont_btn.first.is_disabled():
                                            break
                            except: pass
                                
                        # 3. Bấm Continue sau khi đã chọn xong
                        try:
                            clicked = page.evaluate("""() => {
                                const btns = Array.from(document.querySelectorAll('button')).filter(b => {
                                    const text = (b.innerText || b.textContent || '').trim().toLowerCase();
                                    return (text === 'continue' || text === 'next' || text === 'submit' || text.includes('choose')) && !b.disabled;
                                });
                                if (btns.length > 0) {
                                    btns[btns.length - 1].click();
                                    return true;
                                }
                                return false;
                            }""")
                            if clicked:
                                print("Quiz: JS clicked 'Continue/Next'")
                                page.wait_for_timeout(1500)
                        except Exception: pass
                            
                        continue
                        
                    # 0.3 Xử lý form Passkey/FIDO2 (Windows Security popup)
                    if "fido" in cur_url or "passkey" in cur_url:
                        print("Phát hiện trang cài đặt Security Key (FIDO), đang cố gắng hủy...")
                        try:
                            # Thử nhấn Escape để đóng popup của Windows (nếu có)
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                            
                            # Click nút Hủy trên giao diện HTML
                            cancel_btn = page.locator('button:has-text("Cancel"), a:has-text("Cancel"), button:has-text("Hủy"), a:has-text("Hủy"), #iCancel')
                            if cancel_btn.count() > 0:
                                cancel_btn.first.click(force=True)
                                print("Clicked 'Hủy' (Cancel) for Security Key setup via locator")
                            else:
                                # JS fallback
                                page.evaluate("""() => {
                                    const all = document.querySelectorAll('button, a, input[type=button]');
                                    for (let el of all) {
                                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                                        if (t === 'hủy' || t === 'cancel') {
                                            el.click();
                                            return;
                                        }
                                    }
                                }""")
                                print("Clicked 'Hủy' via JS fallback")
                        except Exception as e:
                            print(f"Lỗi khi hủy FIDO: {e}")
                        page.wait_for_timeout(2000)
                        continue
                        continue

                    # 0.3.5 Xử lý trang "Cho rằng chúng tôi bảo vệ quá mức..." (Bỏ qua cập nhật email bảo vệ)
                    if "account.live.com/proofs/Verify" in cur_url or "account.live.com/proofs" in cur_url:
                        try:
                            skip_link = page.locator('#iShowSkip, a:has-text("Bỏ qua"), a:has-text("Skip")')
                            if skip_link.count() > 0 and skip_link.first.is_visible():
                                skip_link.first.click(force=True)
                                print("Đã click 'Bỏ qua bây giờ' (Skip) trên trang bảo vệ tài khoản.")
                                page.wait_for_timeout(2000)
                                continue
                        except Exception as e:
                            pass

                    # 0.4 Xử lý trang "Giúp bảo vệ tài khoản của bạn"
                    if "account.live.com/interrupt" in cur_url or "credentialaction" in cur_url:
                        print("Trang bao ve tai khoan detected!")
                        try:
                            # Click nút "Thêm email"
                            # Mở rộng selector để bắt chính xác hơn
                            them_email_btn = page.locator('button:has-text("Thêm email"), input[value="Thêm email"], a:has-text("Thêm email"), #idSubmit_SAOTCS_SendCode, [data-testid="AddEmailButton"]')
                            if them_email_btn.count() > 0 and them_email_btn.first.is_visible():
                                them_email_btn.first.click(force=True)
                                print("Clicked 'Thêm email' via locator!")
                            else:
                                page.evaluate("""() => {
                                    const all = document.querySelectorAll('button, input[type=submit], a, div[role="button"]');
                                    for (let el of all) {
                                        const t = (el.innerText || el.value || '').trim().toLowerCase();
                                        if (t === 'thêm email' || t.includes('them email') || t.includes('add email')) {
                                            el.click();
                                            return;
                                        }
                                    }
                                }""")
                                print("Clicked 'Thêm email' via JS fallback")
                            page.wait_for_timeout(3000)
                            
                            # Tạo email temp ngẫu nhiên
                            temp_domain = tinyhost_get_random_domain()
                            temp_user = ''.join(random_mod.choices(string.ascii_lowercase, k=6)) + ''.join(random_mod.choices(string.digits, k=4))
                            temp_email = f"{temp_user}@{temp_domain}"
                            print(f"Temp email for verification: {temp_email}")
                            
                            # Trang "Thêm địa chỉ email" - điền email temp vào
                            email_filled = False
                            try:
                                # Đợi trang "Thêm địa chỉ email" load
                                email_selector = 'input[type="email"], input[name="EmailAddress"], input#iProofEmail, input[name="Email"], input#Email, input.fui-Input__input, input[type="text"]'
                                page.wait_for_selector(email_selector, timeout=10000)
                                email_field = page.locator(email_selector).first
                                email_field.wait_for(state="visible", timeout=5000)
                                email_field.fill(temp_email)
                                page.wait_for_timeout(500)
                                print(f"Filled temp email: {temp_email}")
                                
                                # Click Tiếp theo
                                next_btn = page.locator('input[type="submit"], button[type="submit"], button:has-text("Tiếp theo"), button:has-text("Next")')
                                if next_btn.count() > 0:
                                    next_btn.first.click()
                                else:
                                    page.keyboard.press("Enter")
                                print("Clicked Next after temp email")
                                page.wait_for_timeout(3000)
                                email_filled = True
                            except Exception as e:
                                print(f"Error filling temp email: {e}")
                            
                            # CHỈ poll TinyHost API nếu đã điền email thành công
                            if email_filled:
                                otp_code = None
                                print(f"Polling TinyHost inbox for OTP... ({temp_email})")
                                for attempt in range(5):  # thử 5 lần, mỗi lần cách 5 giây = 25s
                                    page.wait_for_timeout(5000)
                                    em = tinyhost_check_inbox(temp_domain, temp_user)
                                    if em:
                                        body_text = em.get("body", "") or ""
                                        otp_code = extract_otp_code(body_text)
                                        if otp_code:
                                            print(f"OTP found: {otp_code}")
                                            break
                                        else:
                                            print(f"Email found but no OTP in body: {body_text[:100]}")
                                    else:
                                        print(f"Waiting for OTP email... attempt {attempt+1}/5")
                                
                                if not otp_code:
                                    print("OTP not received after 5 attempts. Clicking back to retry with new email...")
                                    try:
                                        # Click nút Quay lại
                                        back_clicked = page.evaluate("""() => {
                                            const b = document.querySelector('button#back-button, button[data-testid="leftArrowIcon"], button[aria-label="Quay lại"], button[aria-label="Back"]');
                                            if (b) { b.click(); return true; }
                                            return false;
                                        }""")
                                        if back_clicked:
                                            print("Clicked back button!")
                                        else:
                                            back_btn = page.locator('button#back-button, button[aria-label="Quay lại"], button[aria-label="Back"]')
                                            if back_btn.count() > 0:
                                                back_btn.first.click(force=True)
                                                print("Clicked back button via locator!")
                                        page.wait_for_timeout(3000)
                                        
                                        # Bây giờ ta ở trang "Thêm địa chỉ email" - điền email temp MỚI
                                        email_selector2 = 'input[type="email"], input[name="EmailAddress"], input#iProofEmail, input[name="Email"], input#Email, input.fui-Input__input, input[type="text"]'
                                        page.wait_for_selector(email_selector2, timeout=8000)
                                        email_field2 = page.locator(email_selector2).first
                                        
                                        # Tạo email temp mới
                                        temp_domain2 = tinyhost_get_random_domain()
                                        temp_user2 = ''.join(random_mod.choices(string.ascii_lowercase, k=6)) + ''.join(random_mod.choices(string.digits, k=4))
                                        temp_email2 = f"{temp_user2}@{temp_domain2}"
                                        print(f"Retrying with new temp email: {temp_email2}")
                                        
                                        # Xóa email cũ và điền mới
                                        email_field2.triple_click()
                                        email_field2.fill(temp_email2)
                                        page.wait_for_timeout(500)
                                        
                                        # Click Tiếp theo
                                        next_btn2 = page.locator('input[type="submit"], button[type="submit"], button:has-text("Tiếp theo"), button:has-text("Next")')
                                        if next_btn2.count() > 0:
                                            next_btn2.first.click()
                                        else:
                                            page.keyboard.press("Enter")
                                        print("Clicked Next after new temp email")
                                        page.wait_for_timeout(3000)
                                        
                                        # Poll lại với email mới (10 lần nữa)
                                        print(f"Polling TinyHost for OTP with new email... ({temp_email2})")
                                        for attempt2 in range(10):
                                            page.wait_for_timeout(5000)
                                            em2 = tinyhost_check_inbox(temp_domain2, temp_user2)
                                            if em2:
                                                body_text2 = em2.get("body", "") or ""
                                                otp_code = extract_otp_code(body_text2)
                                                if otp_code:
                                                    print(f"OTP found on retry: {otp_code}")
                                                    break
                                                else:
                                                    print(f"Email found but no OTP: {body_text2[:100]}")
                                            else:
                                                print(f"Waiting for OTP (retry)... attempt {attempt2+1}/10")
                                    except Exception as e_back:
                                        print(f"Error on back/retry: {e_back}")
                                
                                if otp_code:
                                    # Điền mã OTP vào trang "Nhập mã của bạn"
                                    try:
                                        otp_inputs = page.locator('input[id^="codeEntry-"], input[id^="idTxtBx_SAOTCC_OTC_"], input[maxlength="1"]')
                                        if otp_inputs.count() >= 6:
                                            for i, digit in enumerate(otp_code):
                                                if i < otp_inputs.count():
                                                    otp_inputs.nth(i).fill(digit)
                                                    page.wait_for_timeout(100)
                                            print(f"Filled OTP in 6 separate inputs: {otp_code}")
                                        else:
                                            single_input = page.locator('input[type="text"], input[type="tel"], input[type="number"]').first
                                            single_input.fill(otp_code)
                                            print(f"Filled OTP in single input: {otp_code}")
                                        
                                        page.wait_for_timeout(500)
                                        confirm_btn = page.locator('input[type="submit"], button[type="submit"], button:has-text("Tiếp theo"), button:has-text("Verify"), button:has-text("Next")')
                                        if confirm_btn.count() > 0:
                                            confirm_btn.first.click()
                                        else:
                                            page.keyboard.press("Enter")
                                        print("Submitted OTP code!")
                                        page.wait_for_timeout(3000)
                                    except Exception as e:
                                        print(f"Error filling OTP: {e}")
                                else:
                                    print("OTP not received after all retries. Moving on...")
                        except Exception as e:
                            print(f"Error handling protection page: {e}")
                        
                        continue
                        
                    # 0.5. Popup "Chúng tôi đang cập nhật các điều khoản của mình" (account.live.com/tou/accrue)
                    # Phải click nút "Tiếp theo" (data-testid=primaryButton) để tiếp tục
                    try:
                        if "account.live.com/tou" in cur_url or "tou/accrue" in cur_url:
                            tiep_theo_btn = page.locator('button[data-testid="primaryButton"], input[type="submit"][value="Tiếp theo"], input[type="submit"][value="Next"], button:has-text("Tiếp theo"), button:has-text("Next")')
                            if tiep_theo_btn.count() > 0 and tiep_theo_btn.first.is_visible():
                                tiep_theo_btn.first.click()
                                print("Clicked 'Tiếp theo' on Microsoft ToS update page!")
                                page.wait_for_timeout(2000)
                                continue
                            else:
                                clicked = page.evaluate("""() => {
                                    const btns = document.querySelectorAll('button, input[type="submit"]');
                                    for(let b of btns) {
                                        const t = (b.innerText || b.value || '').trim().toLowerCase();
                                        if(t === 'tiếp theo' || t === 'next') {
                                            b.click();
                                            return true;
                                        }
                                    }
                                    return false;
                                }""")
                                if clicked:
                                    print("Clicked 'Tiếp theo' on Microsoft ToS via JS!")
                                    page.wait_for_timeout(2000)
                                    continue
                    except Exception as e:
                        pass

                    # 1. Nút "Trông rất được!" / "Looks good!"
                    looks_good_btn = page.locator('#iLooksGood, input[value*="Trông rất được"], input[value*="Looks good"]')
                    if looks_good_btn.count() > 0 and looks_good_btn.first.is_visible():
                        looks_good_btn.first.click()
                        print("Clicked 'Trông rất được!' (Looks good)")
                        continue
                    # 1.5. Đóng popup Cookie nếu che mất giao diện
                    try:
                        cookie_btn = page.locator('button:has-text("Chấp nhận tất cả Cookies"), button:has-text("Accept all Cookies")').first
                        if cookie_btn.is_visible(timeout=500):
                            cookie_btn.click(force=True)
                    except: pass

                    # 2. Trang chủ Higgsfield bắt đăng nhập lại
                    if "higgsfield.ai/auth/sign-in" in cur_url or ("higgsfield.ai" in cur_url and "login.microsoftonline" not in cur_url):
                        ms_btn = page.locator('button:has-text("Continue with Microsoft")')
                        if ms_btn.count() > 0 and ms_btn.first.is_visible():
                            ms_btn.first.click(force=True)
                            print("Clicked 'Continue with Microsoft' again after redirect")
                            page.wait_for_timeout(3000)
                            continue
                            
                    # 3. Form nhập email lại (nếu có)
                    try:
                        email_el_exists = page.evaluate("""() => {
                            const el = document.getElementById('i0116');
                            return el && el.offsetParent !== null;
                        }""")
                        if email_el_exists:
                            page.evaluate("""(email) => {
                                const el = document.getElementById('i0116');
                                el.focus();
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                setter.call(el, email);
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                const btn = document.getElementById('idSIButton9');
                                if (btn) btn.click();
                            }""", ms_email)
                            print("Filled email again via JS")
                            page.wait_for_timeout(3000)
                            continue
                    except Exception as e:
                        print(f"Error re-filling email: {e}")
                        
                    # 4. Form nhập password lại (nếu có)
                    try:
                        pwd_el_exists = page.evaluate("""() => {
                            const sels = ['#i0118', 'input[name="passwd"]', 'input[type="password"]:not(.moveOffScreen)', '#passwordEntry'];
                            for (const s of sels) {
                                const el = document.querySelector(s);
                                if (el && el.offsetParent !== null) return true;
                            }
                            return false;
                        }""")
                        if pwd_el_exists:
                            page.evaluate("""(pwd) => {
                                const sels = ['#i0118', 'input[name="passwd"]', 'input[type="password"]:not(.moveOffScreen)', '#passwordEntry'];
                                let el = null;
                                for (const s of sels) {
                                    const found = document.querySelector(s);
                                    if (found && found.offsetParent !== null) { el = found; break; }
                                }
                                if (!el) return;
                                el.focus();
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                setter.call(el, pwd);
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                // Click nút submit - thử cả kiểu cũ và mới
                                const btn1 = document.getElementById('idSIButton9');
                                if (btn1) { btn1.click(); return; }
                                const btn2 = document.querySelector('button[data-testid="primaryButton"]');
                                if (btn2) { btn2.click(); return; }
                                const btn3 = document.querySelector('button[type="submit"], input[type="submit"]');
                                if (btn3) btn3.click();
                            }""", ms_password)
                            print("Filled password again via JS")
                            page.wait_for_timeout(4000)
                            continue
                    except Exception as e:
                        print(f"Error re-filling password: {e}")
                        
                    # 5. Trang thiết lập Security Key (bảng đen FIDO2) -> Bấm Hủy (Cancel)
                    if "fido" in cur_url or "fido/create" in cur_url:
                        # Cố gắng tắt dialog native của Windows (Security key)
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                        cancel_btn = page.locator('#iCancel, a#iCancel, button#iCancel, input[value="Hủy"], input[value="Cancel"], a:has-text("Hủy"), button:has-text("Hủy")')
                        if cancel_btn.count() > 0 and cancel_btn.first.is_visible():
                            cancel_btn.first.click()
                            print("Clicked Cancel for Security Key setup")
                            continue
                            
                    # 6. Tích chọn Cloudflare Turnstile "Xác minh bạn là con người" (ƯU TIÊN HÀNG ĐẦU VÌ NÓ BLOCK TRANG)
                    try:
                        # Cách 1: Click qua div #clerk-captcha (bao bọc shadow DOM)
                        captcha_div = page.locator('#clerk-captcha')
                        if captcha_div.count() > 0 and captcha_div.first.is_visible():
                            box = captcha_div.first.bounding_box()
                            if box:
                                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                print("Clicked Turnstile via #clerk-captcha bounding box")
                                continue
                                
                        # Cách 2: Click trực tiếp vào iframe (nếu truy cập được)
                        iframe_el = page.locator('iframe[src*="cloudflare.com"], iframe[src*="turnstile"]')
                        if iframe_el.count() > 0 and iframe_el.first.is_visible():
                            box = iframe_el.first.bounding_box()
                            if box:
                                page.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
                                print("Clicked Turnstile via iframe bounding box")
                                continue
                        
                        # Cách 3: Truyền thống - Nếu nằm ngoài cùng
                        cf_checkbox = page.locator('input[type="checkbox"][aria-label*="con người"], input[type="checkbox"][aria-label*="human"]')
                        if cf_checkbox.count() > 0 and cf_checkbox.first.is_visible():
                            cf_checkbox.first.click(force=True, position={"x": 5, "y": 5})
                            print("Clicked Turnstile checkbox (main frame)")
                            continue
                            
                        # Cách 4: Truyền thống - Nếu nằm trong iframe
                        cf_iframe = page.frame_locator('iframe[src*="cloudflare.com"], iframe[src*="turnstile"]')
                        cf_checkbox_iframe = cf_iframe.locator('input[type="checkbox"], body')
                        if cf_checkbox_iframe.count() > 0:
                            cf_checkbox_iframe.first.click(force=True)
                            print("Clicked Turnstile checkbox (in iframe)")
                            continue
                    except Exception as e:
                        print(f"Error handling Turnstile: {e}")

                    # 7. Nút Có (Yes) / Chấp nhận (Accept) - Duy trì đăng nhập / Cho phép ứng dụng
                    yes_btn = page.locator('button[data-testid="appConsentPrimaryButton"], input#idSIButton9, button#idSIButton9, button#acceptButton, input#acceptButton, button#idBtn_Accept, input#idBtn_Accept, input[value*="Có"], input[value*="Yes"], input[value*="Chấp nhận"], input[value*="Accept"], button:has-text("Có"), button:has-text("Yes"), button:has-text("Chấp nhận")')
                    if yes_btn.count() > 0 and yes_btn.first.is_visible():
                        yes_btn.first.click(force=True)
                        print("Clicked Yes / Accept")
                        continue
                    else:
                        clicked_yes_js = page.evaluate("""() => {
                            const btns = document.querySelectorAll('button, input[type="submit"], input[type="button"], a');
                            for (let b of btns) {
                                if (b.getAttribute('data-testid') === 'appConsentPrimaryButton') {
                                    b.click();
                                    return true;
                                }
                                const t = (b.innerText || b.value || '').trim().toLowerCase();
                                const tn = t.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
                                if (t === 'có' || tn === 'co' || t === 'yes' || tn.includes('chap nhan') || t === 'accept' || b.id === 'idSIButton9' || b.id === 'acceptButton' || b.id === 'idBtn_Accept') {
                                    // Kiểm tra xem nút có đang bị ẩn không
                                    const style = window.getComputedStyle(b);
                                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                                        b.click();
                                        return true;
                                    }
                                }
                            }
                            return false;
                        }""")
                        if clicked_yes_js:
                            print("Clicked Yes / Accept via JS fallback")
                            continue

                # ====== BƯỚC CUỐI CÙNG: KIỂM TRA FREE GENS ======
                if "auth/sign-in" not in page.url:
                    if "quiz" in page.url and not quiz_completed:
                        keep_open = True
                        print("Trình duyệt vẫn kẹt ở Quiz! Không đóng trình duyệt để người dùng xử lý nốt.")
                        return {"ok": True, "message": "Kẹt ở Quiz, trình duyệt vẫn mở để bạn xử lý..."}

                    print("Đang kiểm tra trạng thái đăng nhập và Free Gens...")
                    try:
                        # Vào trang video để check free gens
                        page.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=30000)
                        page.wait_for_timeout(2000)
                        # Đóng cookie banner nếu còn
                        try:
                            page.evaluate("""() => {
                                const el = document.querySelector('a.cc-allow, .cc-allow');
                                if (el && el.offsetParent !== null) { el.click(); }
                            }""")
                        except: pass
                        page.wait_for_timeout(1000)
                        
                        def check_login_status():
                            page.wait_for_timeout(4000)
                            status_free = False
                            status_logged = False
                            quality = ""
                            
                            # Tang 1: Kiem tra "Use free gens"
                            if page.locator('text="Use free gens"').count() > 0:
                                status_free = True
                                status_logged = True
                                print("Xac nhan login: thay 'Use free gens'!")
                                
                                try:
                                    # Trích xuất quality (720p hoặc 480p)
                                    q_val = page.evaluate("""() => {
                                        const spans = document.querySelectorAll('span, div');
                                        for (let s of spans) {
                                            const t = (s.innerText || s.textContent || '').trim();
                                            if (t === 'Quality') {
                                                const p = s.parentElement;
                                                if (p) {
                                                    const pText = (p.innerText || p.textContent || '');
                                                    if (pText.includes('720')) return '720p';
                                                    if (pText.includes('480')) return '480p';
                                                    if (pText.includes('1080')) return '1080p';
                                                }
                                            }
                                        }
                                        // Fallback 1: check inside comboboxes
                                        const btns = document.querySelectorAll('button[aria-label="Quality"], button[role="combobox"]');
                                        for (let b of btns) {
                                            const bText = (b.innerText || b.textContent || '');
                                            if (bText.includes('720')) return '720p';
                                            if (bText.includes('480')) return '480p';
                                        }
                                        // Fallback 2: check HTML
                                        const html = document.body.innerHTML;
                                        if (html.includes('>720p<') || html.includes('720p')) return '720p';
                                        if (html.includes('>480p<') || html.includes('480p')) return '480p';
                                        return '';
                                    }""")
                                    if q_val:
                                        quality = q_val
                                        print(f"Detected quality: {quality}")
                                except Exception as e:
                                    print(f"Lỗi lấy quality: {e}")
                                    
                                return status_logged, status_free, quality
                                
                            # Tang 2: Click Avatar -> Radix Portal append vao DOM -> tim a[href*=logout]
                            try:
                                avatar_btn = page.locator('button.hfnav-avatar-ring, button[aria-label="Account menu"]')
                                if avatar_btn.count() > 0 and avatar_btn.first.is_visible():
                                    avatar_btn.first.click()
                                    page.wait_for_timeout(2000)
                                    has_logout = page.evaluate("""() => {
                                        const links = document.querySelectorAll('a[href*="logout"]');
                                        return links.length > 0;
                                    }""")
                                    if has_logout:
                                        status_logged = True
                                        print("Xac nhan login: tim thay a[href*=logout] trong DOM!")
                                    page.keyboard.press("Escape")
                                    page.wait_for_timeout(500)
                            except Exception as e:
                                print(f"Loi check Sign Out: {e}")
                                
                            # Tang 3: Fallback - Clerk session cookie
                            if not status_logged:
                                try:
                                    has_session = page.evaluate("""() => {
                                        return document.cookie.includes('__session') || 
                                               document.cookie.includes('__clerk');
                                    }""")
                                    if has_session:
                                        status_logged = True
                                        print("Xac nhan login: tim thay Clerk session cookie!")
                                except Exception as e:
                                    print(f"Loi check Clerk session: {e}")
                                    
                            return status_logged, status_free, quality
                            
                        is_logged, is_free, quality = check_login_status()
                        if not is_logged:
                            print("Chua thay dau hieu login, reload trang...")
                            page.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=30000)
                            page.wait_for_timeout(5000)
                            is_logged, is_free, quality = check_login_status()
                            if not is_logged:
                                print("Van chua thay, reload lan cuoi...")
                                page.reload(timeout=30000)
                                is_logged, is_free, quality = check_login_status()
                        p_obj = manager.get_profile(profile.id)
                        if p_obj:
                            if is_free:
                                tag_note = f"free gen {quality}".strip() if quality else "free gen"
                                p_obj.notes = tag_note
                                print(f"=> Cap nhat the thanh '{tag_note}' (Xanh la)")
                            elif is_logged:
                                p_obj.notes = "không free"
                                print("=> Cap nhat the thanh 'khong free' (Vang)")
                            else:
                                if not getattr(threading.current_thread(), 'has_retried_login', False):
                                    threading.current_thread().has_retried_login = True
                                    print("Chưa login thì thực hiện login lại lần nữa...")
                                    try:
                                        page.goto("https://higgsfield.ai/auth/sign-in", timeout=30000)
                                        page.wait_for_timeout(3000)
                                        ms_btn = page.locator("button:has-text('Continue with Microsoft')")
                                        if ms_btn.count() > 0:
                                            ms_btn.first.click(timeout=3000, force=True)
                                            print("Retry: Clicked 'Continue with Microsoft'")
                                            page.wait_for_timeout(3000)
                                            
                                            # Thử điền lại email nếu có form
                                            email_input = page.locator('input[type="email"], input[name="loginfmt"], input[id="i0116"]')
                                            if email_input.count() > 0 and email_input.first.is_visible():
                                                ms_acc_file = Path(profile.user_data_dir) / "ms_account.txt"
                                                if ms_acc_file.exists():
                                                    parts = ms_acc_file.read_text(encoding="utf-8").strip().split("|")
                                                    if len(parts) >= 2:
                                                        email_input.first.fill(parts[0].strip())
                                                        page.keyboard.press("Enter")
                                                        page.wait_for_timeout(2000)
                                                        
                                                        pwd_input = page.locator('input[type="password"], input[name="passwd"], input[id="i0118"]')
                                                        if pwd_input.count() > 0 and pwd_input.first.is_visible():
                                                            pwd_input.first.fill(parts[1].strip())
                                                            page.keyboard.press("Enter")
                                                            page.wait_for_timeout(3000)
                                    except Exception as ex:
                                        print(f"Lỗi khi retry login: {ex}")
                                    
                                    # Sau khi thử click lại, kiểm tra lại trạng thái
                                    is_logged, is_free, quality = check_login_status()
                                    if is_free:
                                        tag_note = f"free gen {quality}".strip() if quality else "free gen"
                                        p_obj.notes = tag_note
                                        print(f"=> Retry thành công: {tag_note}")
                                    elif is_logged:
                                        p_obj.notes = "không free"
                                        print("=> Retry thành công: không free")
                                    else:
                                        p_obj.notes = "lỗi login"
                                        print("=> Retry thất bại: cập nhật thẻ thành 'loi login'")
                                        keep_open = True
                                else:
                                    p_obj.notes = "lỗi login"
                                    print("=> Cap nhat the thanh 'loi login'")
                                    keep_open = True
                            manager._save()
                    except Exception as e:
                        print(f"Lỗi khi kiểm tra đăng nhập/Free Gens: {e}")
                
        except Exception as e:
            print(f"Auto signup FATAL err: {e}")
        finally:
            with _signup_lock:
                if profile_id in _running_signups:
                    _running_signups.remove(profile_id)
            try:
                if not keep_open:
                    p.stop()
            except: pass
            try:
                if not keep_open:
                    close_profile(profile.id)
                    print(f"Đã đóng Chrome cho profile {profile.name} sau khi hoàn tất cập nhật.")
                else:
                    print(f"Giữ Chrome mở cho profile {profile.name} theo yêu cầu.")
            except: pass

    threading.Thread(target=run_auto_signup, daemon=True).start()
    return {"ok": True, "message": "Bắt đầu Auto Login Higgsfield (Microsoft)..."}

@router.post("/api/profiles/{profile_id}/set-ms-account")
def set_ms_account(profile_id: str, payload: dict = Body(...)):
    """Lưu thông tin tài khoản Microsoft vào profile. Format: email|password|token|guid"""
    profile = manager.get_profile(profile_id)
    if not profile: raise HTTPException(404, "Profile not found")
    
    raw = payload.get("raw", "").strip()
    if not raw:
        raise HTTPException(400, "Thiếu dữ liệu tài khoản")
    
    parts = raw.split("|")
    if len(parts) < 2:
        raise HTTPException(400, "Sai định dạng. Cần: email|password hoặc email|password|token|guid")
    
    email = parts[0].strip()
    password = parts[1].strip()
    
    acc_file = Path(profile.user_data_dir) / "ms_account.txt"
    acc_file.parent.mkdir(parents=True, exist_ok=True)
    acc_file.write_text(raw, encoding="utf-8")
    
    return {"ok": True, "email": email, "message": f"Đã lưu tài khoản {email}"}

@router.post("/api/settings/max_retries")
def set_max_retries(val: int = Form(...)):
    global GLOBAL_MAX_RETRIES
    if val > 0:
        GLOBAL_MAX_RETRIES = val
    return {"ok": True}



@router.put("/api/profiles/{profile_id}/name")
def rename_profile(profile_id: str, payload: dict = Body(...)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Tên không được để trống")
    ok = manager.update_profile_name(profile_id, name)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"ok": True, "name": name}



@router.post('/api/profiles/{profile_id}/reload_tab')
def reload_profile_tab(profile_id: str):
    p = manager.get_profile(profile_id)
    if not p:
        raise HTTPException(404, 'Not found')
    port_file = Path(p.user_data_dir) / 'cdp_port.txt'
    if not port_file.exists():
        return {'ok': False, 'message': 'Chrome chua mo'}
    port = port_file.read_text().strip()
    if not port:
        return {'ok': False, 'message': 'Chrome chua mo'}
    def _do_reload():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(f'http://localhost:{port}')
                ctx = browser.contexts[0]
                target_page = None
                for page in ctx.pages:
                    if 'higgsfield.ai' in page.url:
                        target_page = page
                        break
                if not target_page and ctx.pages:
                    target_page = ctx.pages[0]
                if target_page:
                    target_page.reload(timeout=15000)
            except Exception as e:
                print('Loi reload CDP:', e)
    import threading
    threading.Thread(target=_do_reload, daemon=True).start()
    return {'ok': True}
