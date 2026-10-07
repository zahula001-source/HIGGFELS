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
from app.services.microsoft_recovery import (
    MailboxAccessDenied,
    click_use_password,
    fetch_roundcube_messages,
    read_code_in_smail_tab,
    parse_microsoft_account,
)
from app.services.higgsfield_login import (
    video_login_state,
    wait_video_login_state,
    read_free_gens,
    read_quality,
)

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
    if req:
        req.enable_ext = True
    if req and req.auto_random_fp:
        do_random = True
    elif getattr(profile, 'auto_random_fp', False):
        do_random = True
        
    if do_random:
        profile = manager.randomize_fingerprint(profile_id)

    # Urban VPN dang tra 429 o API dang ky, lam popup bao "Registration error".
    # Dung 1ClickVPN (API dang ky hoat dong) lam VPN mac dinh cho CloakBrowser.
    old_ext_paths = (
        "D:/CODE/higgsfield-VIDEOAI/data/extensions/urbanvpn",
        "D:/CODE/higgsfield-VIDEOAI/data/extensions/1clickvpn",
    )
    ext_path = "https://chromewebstore.google.com/detail/1clickvpn-proxy-for-chrom/pphgdbgldlmicfdkhondlafkiomnelnk"

    if profile.extensions:
        for old_ext_path in old_ext_paths:
            profile.extensions = profile.extensions.replace(old_ext_path, "")

    if not profile.extensions or ext_path not in profile.extensions:
        profile.extensions = (profile.extensions + ";" + ext_path).strip(";")
        profile.extensions = profile.extensions.replace(";;", ";")

    result = launch_profile_with_fallback(profile, req)
    
    if result["status"] in ["launched", "already_running"]:
        try:
            # Auto login immediately when opening chrome
            # Nếu được gọi từ "Tạo acc + login", UI sẽ truyền keep_open_after_check=False
            keep_open_after = getattr(req, "keep_open_after_check", True) if req else True
            auto_signup_endpoint(profile_id, keep_open=keep_open_after, generate_ip=req.generate_ip, engine=req.engine)
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

@router.put("/api/profiles/{profile_id}/name")
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
def auto_signup_endpoint(profile_id: str, keep_open: bool = False, generate_ip: bool = False, engine: str = "chrome"):
    import threading
    from pathlib import Path

    profile = manager.get_profile(profile_id)
    if not profile: raise HTTPException(404, "Profile not found")
    
    from app.browser import prepare_chrome_136_profile
    runtime_dir = profile.user_data_dir if engine == "cloakbrowser" else prepare_chrome_136_profile(profile.user_data_dir)
    port_file = Path(runtime_dir) / "cdp_port.txt"
    if not port_file.exists():
        raise HTTPException(400, "Profile đang không chạy hoặc không có CDP port. Hãy mở lại Chrome!")
        
    try:
        port = int(port_file.read_text().strip())
    except:
        raise HTTPException(400, "Invalid CDP port.")

    with _signup_lock:
        if profile_id in _running_signups:
            print(f"Bỏ qua: Auto signup cho profile {profile_id} đã đang chạy.")
            return {"ok": True, "message": "Auto Login đã đang chạy."}
        _running_signups.add(profile_id)

    def run_auto_signup():
        nonlocal keep_open
        import random, time
        # --- Tối ưu: Stagger startup (giãn cách thời gian mở) để các luồng không tranh chấp tài nguyên và không spam API cùng 1 miligiây ---
        time.sleep(random.uniform(0.5, 3.5))
        
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
                        port_file_latest = Path(runtime_dir) / "cdp_port.txt"
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

                if generate_ip:
                    try:
                        from app.services.vpn_ip import connect_unique_vpn_ip
                        vpn_info = connect_unique_vpn_ip(context, profile_id)
                        print(f"Sinh IP thanh cong: {vpn_info['ip']} ({vpn_info['country']})")
                    except Exception as vpn_error:
                        print(f"Sinh IP that bai, dung tao acc de tranh trung IP: {vpn_error}")
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
                    
                    if page.url != HIGGSFIELD_URL:
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
                initial_login_state = wait_video_login_state(page)
                ms_btn_visible = False
                try:
                    ms_btn_check = page.locator("button:has-text('Continue with Microsoft')")
                    if ms_btn_check.count() > 0 and ms_btn_check.first.is_visible(timeout=500):
                        ms_btn_visible = True
                except: pass

                if initial_login_state is not True and not ms_btn_visible and "auth/sign-in" not in page.url:
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
                already_logged_in = initial_login_state is True
                try:
                    for _ in range(15):
                        if already_logged_in:
                            break
                        if "quiz" in page.url:
                            print("Đã phát hiện URL login sẵn (quiz), bỏ qua chờ popup!")
                            already_logged_in = True
                            break
                        # Check for logged-in indicators
                        if video_login_state(page) is True:
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

                ms_email = None
                ms_password = None
                recovery_email = None
                recovery_password = None
                is_v2_account = False
                ms_acc_file = Path(profile.user_data_dir) / "ms_account.txt"
                if ms_acc_file.exists():
                    try:
                        raw_acc = ms_acc_file.read_text(encoding="utf-8").strip()
                        ms_account = parse_microsoft_account(raw_acc)
                        if ms_account:
                            ms_email = ms_account.email
                            ms_password = ms_account.password
                            recovery_email = ms_account.recovery_email or None
                            recovery_password = ms_account.recovery_password or None
                            is_v2_account = ms_account.is_v2
                            print(f"Loaded MS account: {ms_email}")
                            if ms_account.is_v2:
                                print("Detected MS account V2 with recovery mailbox")
                    except Exception as e:
                        print(f"Error reading ms_account.txt: {e}")
                
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
                    
                    # Đợi chuyển sang trang login.microsoftonline.com / login.live.com hoặc đợi đến khi avatar xuất hiện
                    try:
                        for _ in range(30):
                            if "login.microsoft" in page.url or "login.live" in page.url:
                                break
                            if "higgsfield.ai/quiz" in page.url:
                                break
                            if page.locator('button[aria-haspopup="menu"]:has(img.rounded-full)').is_visible():
                                break
                            page.wait_for_timeout(500)
                    except: pass
                    print(f"Current URL after waiting for redirect: {page.url}")
                    
                    if ms_email and ms_password:
                        page.wait_for_timeout(500)
                        print(f"MS login page URL: {page.url}")
                        
                        # Điền email vào ô input
                        try:
                            import time
                            if "account.live.com" in page.url or "fido" in page.url: 
                                raise ValueError("Stuck on protection page")
                            if page.url.startswith("https://higgsfield.ai") and not page.locator('button:has-text("Continue with Microsoft")').is_visible():
                                raise ValueError("Already logged in or stuck on protection page, skipping email")
                            
                            # Đợi input xuất hiện hoặc nút Sử dụng mật khẩu xuất hiện
                            email_found = False
                            for _ in range(20):
                                try:
                                    # Kiểm tra xem có nút "Sử dụng mật khẩu của bạn" không
                                    use_pwd_btn = page.locator('span[role="button"]:has-text("Use your password"), span[role="button"]:has-text("Sử dụng mật khẩu của bạn"), a:has-text("Use your password"), a:has-text("Sử dụng mật khẩu của bạn"), #iUsePasswordLink, #idA_PWD_SwitchToPassword')
                                    if use_pwd_btn.count() > 0:
                                        print("Bỏ qua chờ nhập email vì đã thấy nút Sử dụng mật khẩu")
                                        raise ValueError("Thấy nút sử dụng mật khẩu")
                                        
                                    if page.locator('#i0116:not([type="hidden"])').is_visible():
                                        email_found = True
                                        break
                                except Exception as e:
                                    if "Thấy nút sử dụng mật khẩu" in str(e):
                                        raise e
                                page.wait_for_timeout(500)
                                
                            if not email_found:
                                raise ValueError("Không thấy ô nhập email")
                            
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
                            if not is_v2_account:
                                page.wait_for_timeout(3000)
                            
                        except Exception as e:
                            print(f"Error filling email: {e}")
                        
                        # Kiểm tra xem có bị chuyển hướng sang trang "Xác minh email của bạn" (chọn phương thức xác thực) không
                        # Nếu có, bấm "Sử dụng mật khẩu của bạn" để quay lại form mật khẩu
                        try:
                            page.wait_for_timeout(100 if is_v2_account else 500)
                            if page.url.startswith("https://higgsfield.ai") or "account.live.com" in page.url or "fido" in page.url: 
                                raise ValueError("Already logged in or stuck on protection page, skipping use password")
                            
                            # Sử dụng JS để tìm và click chính xác
                            clicked_pwd = page.evaluate("""() => {
                                const elements = document.querySelectorAll('span, a, div, button, [role="button"]');
                                for (let el of elements) {
                                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                                    if (text === 'use your password' || text === 'sử dụng mật khẩu của bạn' || text.includes('sử dụng mật khẩu') || text.includes('use your password') || el.id === 'iUsePasswordLink' || el.id === 'idA_PWD_SwitchToPassword') {
                                        if (el.getAttribute('role') === 'button' || el.tagName === 'A' || el.tabIndex === 0 || el.offsetParent !== null) {
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
                                use_pwd_btn = page.locator('span[role="button"]:has-text("Use your password"), span[role="button"]:has-text("Sử dụng mật khẩu của bạn"), a:has-text("Use your password"), a:has-text("Sử dụng mật khẩu của bạn"), #iUsePasswordLink, #idA_PWD_SwitchToPassword')
                                if use_pwd_btn.count() > 0:
                                    use_pwd_btn.first.click(force=True)
                                    print("Clicked 'Sử dụng mật khẩu của bạn' (Use your password) via Locator")
                                    page.wait_for_timeout(2000)
                        except Exception as e:
                            print(f"Error checking 'Sử dụng mật khẩu': {e}")
                            pass
                            
                        # Điền mật khẩu
                        try:
                            if "account.live.com" in page.url or "fido" in page.url: 
                                raise ValueError("Stuck on protection page")
                            if page.url.startswith("https://higgsfield.ai") and not page.locator('button:has-text("Continue with Microsoft")').is_visible():
                                raise ValueError("Already logged in or stuck on protection page, skipping password")
                            
                            # Đợi ô password xuất hiện
                            if is_v2_account:
                                # Poll both states every 100ms: the modern Microsoft
                                # page can render a button after the first DOM check.
                                password_deadline = time.monotonic() + 10
                                while time.monotonic() < password_deadline:
                                    password_ready = page.locator('input[type="password"]:visible')
                                    if password_ready.count() > 0:
                                        break
                                    try:
                                        if click_use_password(page):
                                            print("V2: clicked 'Use your password' immediately")
                                    except Exception:
                                        pass  # Navigation can temporarily destroy the DOM.
                                    page.wait_for_timeout(100)
                                else:
                                    raise ValueError("V2: password form did not appear within 10s")
                            else:
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
                            if not filled_pwd:
                                raise ValueError("Password was not filled; continue with watchdog")
                            
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
                            for _ in range(3):
                                try:
                                    req = urllib.request.Request("https://tinyhost.shop/api/random-domains/?limit=10")
                                    with urllib.request.urlopen(req, timeout=10) as resp:
                                        data = json_mod.loads(resp.read().decode())
                                        domains = data.get("domains", [])
                                        if domains:
                                            return random_mod.choice(domains)
                                except Exception as e:
                                    import time
                                    time.sleep(1.5)
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
                                pass
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
                captcha_active = False
                keep_open_before_captcha = keep_open
                callback_reloads = 0
                watchdog_state = ""
                watchdog_state_since = time.monotonic()
                recovery_known_uids = set()
                recovery_baseline_ready = False
                recovery_code_requested = False
                recovery_last_poll = 0.0
                recovery_api_denied = False
                recovery_last_web_code = ""
                use_password_last_click = 0.0
                original_profile_note = getattr(profile, "notes", "") or ""

                def set_watchdog_note(note):
                    try:
                        live_profile = manager.get_profile(profile_id)
                        if live_profile and live_profile.notes != note:
                            live_profile.notes = note
                            manager._save()
                    except Exception:
                        pass

                def restore_watchdog_note():
                    try:
                        live_profile = manager.get_profile(profile_id)
                        if live_profile and (live_profile.notes or "").startswith("⚠️ Xác minh"):
                            live_profile.notes = original_profile_note
                            manager._save()
                    except Exception:
                        pass

                def handle_microsoft_credentials():
                    """Handle V1 login and V2 recovery-email verification forms."""
                    nonlocal recovery_known_uids, recovery_baseline_ready
                    nonlocal recovery_code_requested, recovery_last_poll
                    nonlocal recovery_api_denied, recovery_last_web_code, keep_open
                    nonlocal use_password_last_click
                    if not ms_email or not ms_password:
                        return False
                    try:
                        current_url = page.url.lower()
                        from urllib.parse import urlsplit
                        microsoft_host = urlsplit(current_url).hostname
                        allowed_hosts = {"login.live.com", "login.microsoftonline.com", "login.microsoft.com"}
                        if is_v2_account:
                            allowed_hosts.add("account.live.com")
                        if microsoft_host not in allowed_hosts:
                            return False

                        def first_visible(selector):
                            candidates = page.locator(selector)
                            for candidate_index in range(candidates.count()):
                                candidate = candidates.nth(candidate_index)
                                try:
                                    if candidate.is_visible(timeout=200):
                                        return candidate
                                except Exception:
                                    pass
                            return None

                        # Microsoft may show a method picker while a generic email
                        # input is also present. Always choose password first.
                        if (
                            time.monotonic() - use_password_last_click >= 3
                            and click_use_password(page)
                        ):
                            use_password_last_click = time.monotonic()
                            print("Watchdog: clicked 'Use your password'")
                            return True
                        use_password = first_visible(
                            'a#iUsePasswordLink, a#idA_PWD_SwitchToPassword, '
                            'span[role="button"]:has-text("Use your password"), '
                            'span[role="button"]:has-text("Sử dụng mật khẩu của bạn"), '
                            '[role="button"]:has-text("Use your password"), '
                            'a:has-text("Use your password"), '
                            '[role="button"]:has-text("Sử dụng mật khẩu")'
                        )
                        if use_password is not None:
                            use_password.click(timeout=3000, force=True)
                            print("Watchdog: clicked 'Use your password'")
                            return True

                        # V2: after password Microsoft asks which recovery address
                        # should receive the code. Click the row matching its domain
                        # (the local part is normally masked in the UI).
                        if (
                            is_v2_account and recovery_email and recovery_password
                            and page.locator('input[type="password"]:visible').count() == 0
                        ):
                            recovery_domain = recovery_email.rsplit("@", 1)[-1].lower()
                            recovery_prefix = recovery_email.split("@", 1)[0][:2].lower()
                            body_lower = page.locator("body").inner_text(timeout=1000).lower()
                            exact_recovery_input = first_visible(
                                '#iProofEmail, input[name="ProofConfirmation"]'
                            )
                            exact_otp_input = first_visible(
                                '#iOttText, input[name="otc"], input[autocomplete="one-time-code"]'
                            )
                            proof_radios = page.locator('input[type="radio"][name="proof"]')
                            if exact_recovery_input is None and exact_otp_input is None:
                                for proof_index in range(proof_radios.count()):
                                    proof_radio = proof_radios.nth(proof_index)
                                    proof_value = (proof_radio.get_attribute("value") or "").lower()
                                    if (
                                        "||email||" in proof_value
                                        and "@" + recovery_domain in proof_value
                                        and proof_radio.is_visible()
                                    ):
                                        proof_radio.check(timeout=3000)
                                        recovery_code_requested = False
                                        recovery_baseline_ready = False
                                        print("Watchdog: selected recovery email radio")
                                        return True
                            recovery_choice = page.evaluate_handle(r"""([domain, prefix]) => {
                                const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                                const nodes = [...document.querySelectorAll('button, a, [role="button"], [role="option"], div')];
                                const matches = nodes.filter(el => {
                                    if (!visible(el)) return false;
                                    const text = (el.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase();
                                    return text.length < 180 && text.includes(domain) &&
                                        (text.includes('email') || text.includes(prefix));
                                });
                                return matches.sort((a, b) => a.childElementCount - b.childElementCount)[0] || null;
                            }""", [recovery_domain, recovery_prefix])
                            choice_element = recovery_choice.as_element()
                            if (
                                choice_element is not None
                                and exact_recovery_input is None
                                and exact_otp_input is None
                                and "send code" not in body_lower
                            ):
                                try:
                                    if recovery_api_denied:
                                        raise MailboxAccessDenied("API disabled after access denial")
                                    recovery_known_uids, _ = fetch_roundcube_messages(
                                        recovery_email, recovery_password
                                    )
                                    recovery_baseline_ready = True
                                except MailboxAccessDenied:
                                    recovery_api_denied = True
                                    recovery_baseline_ready = False
                                except Exception as baseline_error:
                                    recovery_baseline_ready = False
                                    print(f"Recovery mailbox baseline error: {baseline_error}")
                                choice_element.click(timeout=3000, force=True)
                                recovery_code_requested = False
                                print("Watchdog: selected V2 recovery email method")
                                return True

                            recovery_input = first_visible(
                                '#iProofEmail, input[name="ProofConfirmation"], '
                                'input[autocomplete="email"], input[type="email"]'
                            )
                            is_recovery_confirmation = (
                                recovery_input is not None
                                and (
                                    exact_recovery_input is not None
                                    or
                                    "send code" in body_lower
                                    or "verify your email" in body_lower
                                    or "enter the email address" in body_lower
                                    or "xác minh email" in body_lower
                                )
                            )
                            if is_recovery_confirmation:
                                # Legacy account.live.com already appends the domain.
                                domain_label = first_visible('#iConfirmProofEmailDomain')
                                proof_text = recovery_email
                                if domain_label is not None:
                                    displayed_domain = domain_label.inner_text().strip().lower()
                                    if displayed_domain == "@" + recovery_domain:
                                        proof_text = recovery_email.rsplit("@", 1)[0]
                                recovery_input.fill(proof_text, timeout=3000)
                                if not recovery_baseline_ready and not recovery_api_denied:
                                    try:
                                        recovery_known_uids, _ = fetch_roundcube_messages(
                                            recovery_email, recovery_password, timeout=5
                                        )
                                        recovery_baseline_ready = True
                                    except MailboxAccessDenied:
                                        recovery_api_denied = True
                                        print("smail1s denied API access; stopped API retries")
                                    except Exception:
                                        print("Recovery mailbox unavailable; continuing Send code")
                                send_button = first_visible(
                                    '#iSelectProofAction, #idSubmit_SAOTCS_SendCode, #idSIButton9, '
                                    'button[data-testid="primaryButton"], '
                                    'button:has-text("Send code"), input[type="submit"]'
                                )
                                if send_button is not None and send_button.is_enabled():
                                    send_button.click(timeout=3000)
                                else:
                                    recovery_input.press("Enter")
                                recovery_code_requested = True
                                recovery_last_poll = 0.0
                                recovery_last_web_code = ""
                                print("Watchdog: entered recovery email and requested code")
                                return True

                            otp_input = (
                                exact_otp_input
                                if exact_otp_input is not None
                                else first_visible('input[inputmode="numeric"]')
                            )
                            if otp_input is not None:
                                try:
                                    verify_error = first_visible(
                                        '#iVerifyCodeError, .alert-error, [role="alert"]'
                                    )
                                    if verify_error is not None:
                                        error_text = verify_error.inner_text(timeout=500).lower()
                                        if "didn't work" in error_text or "did not work" in error_text:
                                            recovery_code_requested = True
                                            print("Watchdog: Microsoft rejected OTP; refreshing smail1s inbox")
                                except Exception:
                                    pass
                            if otp_input is not None and recovery_code_requested:
                                if recovery_api_denied:
                                    keep_open = True
                                    set_watchdog_note("⚠️ Xác minh OTP: smail1s chặn API")
                                    try:
                                        web_code = read_code_in_smail_tab(
                                            context,
                                            recovery_email,
                                            recovery_password,
                                            refresh=True,
                                            exclude_codes={recovery_last_web_code},
                                        )
                                    except Exception as web_mail_error:
                                        print(f"Tab smail1s: {web_mail_error}")
                                        return False
                                    if web_code:
                                        otp_input.fill(web_code, timeout=3000)
                                        manual_next = first_visible(
                                            '#iVerifyCodeAction, #idSubmit_SAOTCC_Continue, '
                                            '#idSIButton9, button[data-testid="primaryButton"]'
                                        )
                                        if manual_next is not None and manual_next.is_enabled():
                                            manual_next.click(timeout=3000)
                                            recovery_last_web_code = web_code
                                            recovery_code_requested = False
                                            print("Watchdog: submitted OTP from smail1s tab")
                                            return True
                                    return False
                                now = time.monotonic()
                                if now - recovery_last_poll < 4:
                                    return False
                                recovery_last_poll = now
                                try:
                                    current_uids, otp_code = fetch_roundcube_messages(
                                        recovery_email, recovery_password
                                    )
                                    has_new_message = bool(current_uids - recovery_known_uids)
                                    recovery_known_uids.update(current_uids)
                                    if otp_code and (has_new_message or not recovery_baseline_ready):
                                        otp_input.fill(otp_code, timeout=3000)
                                        next_button = first_visible(
                                            '#iVerifyCodeAction, #idSubmit_SAOTCC_Continue, #idSIButton9, '
                                            'button[data-testid="primaryButton"], '
                                            'button:has-text("Next"), input[type="submit"]'
                                        )
                                        if next_button is not None and next_button.is_enabled():
                                            next_button.click(timeout=3000)
                                        else:
                                            otp_input.press("Enter")
                                        recovery_code_requested = False
                                        print("Watchdog: filled V2 recovery code and clicked Next")
                                        return True
                                    print("Watchdog: waiting for a new recovery code")
                                except MailboxAccessDenied:
                                    recovery_api_denied = True
                                    print("smail1s denied API access; enter OTP in Microsoft to continue")
                                    page.bring_to_front()
                                except Exception as otp_error:
                                    print(f"Recovery mailbox poll error: {otp_error}")
                                return False

                        email_input = first_visible(
                            '#i0116:not([type="hidden"]), input[name="loginfmt"], '
                            'input[type="email"], input[autocomplete="username"]'
                        )
                        if email_input is not None:
                            if email_input.input_value() != ms_email:
                                email_input.fill(ms_email, timeout=3000)
                            page.wait_for_timeout(250)
                            next_button = first_visible(
                                '#idSIButton9, button[data-testid="primaryButton"], '
                                'button[type="submit"], input[type="submit"]'
                            )
                            if next_button is not None and next_button.is_enabled():
                                next_button.click(timeout=3000)
                            else:
                                email_input.press("Enter")
                            print("Watchdog: đã điền lại email Microsoft")
                            return True

                        password_input = first_visible(
                            '#i0118, input[name="passwd"], #passwordEntry, '
                            'input[type="password"]'
                        )
                        if password_input is not None:
                            if not password_input.input_value():
                                password_input.fill(ms_password, timeout=3000)
                            page.wait_for_timeout(250)
                            submit_button = first_visible(
                                '#idSIButton9, button[data-testid="primaryButton"], '
                                'button[type="submit"], input[type="submit"]'
                            )
                            if submit_button is not None and submit_button.is_enabled():
                                submit_button.click(timeout=3000)
                            else:
                                password_input.press("Enter")
                            print("Watchdog: đã điền lại mật khẩu Microsoft")
                            return True
                    except Exception as credential_error:
                        print(f"Watchdog Microsoft form: {credential_error}")
                    return False

                login_restarts = 0
                for _ in range(720):
                    # Poll quickly so three concurrent browsers do not sit on a stale step.
                    try:
                        _is_quiz = "higgsfield.ai/quiz" in page.url
                    except Exception:
                        _is_quiz = False
                    page.wait_for_timeout(500 if _is_quiz else 800)
                    
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

                    # Cloudflare Turnstile cannot be safely completed by DOM clicking.
                    # Detect it immediately, surface the affected window, then resume as
                    # soon as the user has completed the verification.
                    try:
                        body_text = page.locator("body").inner_text(timeout=1000)
                    except Exception:
                        body_text = ""
                    try:
                        has_turnstile_frame = page.locator(
                            'iframe[src*="challenges.cloudflare.com"], '
                            'iframe[src*="turnstile"], iframe[title*="Cloudflare"]'
                        ).count() > 0
                    except Exception:
                        has_turnstile_frame = False
                    captcha_detected = (
                        "Verify you are human" in body_text
                        or "Xác minh bạn là con người" in body_text
                        or has_turnstile_frame
                    )
                    if captcha_detected:
                        if not captcha_active:
                            captcha_active = True
                            keep_open = True
                            set_watchdog_note("⚠️ Xác minh người")
                            try:
                                page.bring_to_front()
                            except Exception:
                                pass
                            print("Watchdog: phát hiện Verify you are human; chờ người dùng xác minh...")
                        continue
                    elif captcha_active:
                        captcha_active = False
                        keep_open = keep_open_before_captcha
                        restore_watchdog_note()
                        watchdog_state = ""
                        watchdog_state_since = time.monotonic()
                        print("Watchdog: Cloudflare đã xác minh xong, tiếp tục tự động.")

                    if handle_microsoft_credentials():
                        watchdog_state = ""
                        watchdog_state_since = time.monotonic()
                        page.wait_for_timeout(700)
                        continue

                    # Recover a Higgsfield SSO callback that remains on "Wait just a moment".
                    # Tự động click Cloudflare Turnstile nếu gặp
                    try:
                        cf_clicked = False
                        
                        # 1. Clerk Captcha (Bọc trong shadow DOM khép kín)
                        clerk_wrapper = page.locator('#clerk-captcha')
                        if clerk_wrapper.count() > 0 and clerk_wrapper.first.is_visible(timeout=500):
                            print("Watchdog: Phát hiện hộp kiểm Cloudflare (Clerk), đang click chuột vật lý (lệch trái)...")
                            box = clerk_wrapper.first.bounding_box()
                            if box:
                                # Hộp kiểm Cloudflare thường nằm ở góc trái của khung (khoảng x + 35px)
                                page.mouse.move(box["x"] + 45, box["y"] + box["height"] / 2)
                                page.wait_for_timeout(300)
                                page.mouse.down()
                                page.wait_for_timeout(150)
                                page.mouse.up()
                            else:
                                clerk_wrapper.first.click(position={"x": 45, "y": 30}, force=True)
                            page.wait_for_timeout(3000)
                            watchdog_state_since = time.monotonic()
                            cf_clicked = True
                            
                        # 2. Cloudflare Turnstile độc lập
                        if not cf_clicked:
                            for frame in page.frames:
                                if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                                    print(f"Watchdog: Phát hiện Cloudflare Frame, click giả lập...")
                                    try:
                                        # Click vào giữa thẻ body của frame
                                        frame.locator("body").click(force=True, position={"x": 35, "y": 35})
                                        page.wait_for_timeout(3000)
                                        watchdog_state_since = time.monotonic()
                                        cf_clicked = True
                                        break
                                    except: pass
                                    
                        # 3. Label dự phòng
                        if not cf_clicked:
                            cf_label_page = page.locator('label:has(input[type="checkbox"])').filter(has_text="Verify")
                            if cf_label_page.count() > 0 and cf_label_page.first.is_visible(timeout=500):
                                print("Watchdog: Phát hiện Cloudflare (Label), đang tự động click...")
                                cf_label_page.first.click(timeout=1000, force=True)
                                page.wait_for_timeout(3000)
                                watchdog_state_since = time.monotonic()
                    except Exception:
                        pass
                        
                    callback_waiting = (
                        "/auth/sso-callback" in cur_url
                        or "Wait just a moment" in body_text
                        or "Vui lòng chờ trong giây lát" in body_text
                    )
                    current_state = (
                        f"{cur_url}|callback={callback_waiting}|"
                        f"email={'i0116' in body_text}|password={'Enter your password' in body_text}"
                    )
                    if current_state != watchdog_state:
                        watchdog_state = current_state
                        watchdog_state_since = time.monotonic()
                    elif callback_waiting and time.monotonic() - watchdog_state_since >= 15:
                        callback_reloads += 1
                        print(f"Watchdog: SSO callback treo, tự khôi phục lần {callback_reloads}/3")
                        try:
                            if callback_reloads <= 2:
                                page.reload(wait_until="domcontentloaded", timeout=30000)
                            else:
                                page.goto(HIGGSFIELD_URL, wait_until="domcontentloaded", timeout=30000)
                        except Exception as callback_error:
                            print(f"Watchdog callback reload: {callback_error}")
                        watchdog_state = ""
                        watchdog_state_since = time.monotonic()
                        continue
                    
                    if any(s in cur_url for s in ["/ai/video", "/supercomputer", "/canvas", "/cinema", "/marketing", "/shorts", "/mcp"]) and "quiz" not in cur_url:
                        # Nếu đang ở /ai/video thì KHÔNG GOTO nữa để tránh kẹt reload!
                        if page.url == "https://higgsfield.ai/":
                            page.goto(HIGGSFIELD_URL, wait_until="domcontentloaded", timeout=30000)
                        login_state = wait_video_login_state(page)
                        if login_state is True:
                            try:
                                page.wait_for_url(lambda u: "quiz" in u, timeout=3000)
                                print("Đã đăng nhập nhưng bị đẩy sang trang Quiz, tiếp tục xử lý...")
                                continue
                            except:
                                print("Đã đăng nhập thành công vào Higgsfield!")
                                break
                        if login_state is None:
                            page.reload(wait_until="domcontentloaded", timeout=30000)
                            continue
                        login_restarts += 1
                        if login_restarts > 5:
                            print("Login chưa thành công sau 5 lần khởi động lại luồng.")
                            break
                        print(f"Còn nút Login/Sign up; tự đăng nhập lại lần {login_restarts}/5")
                        auth_button = page.locator('button.hfnav-auth-login:visible, button.hfnav-auth-signup:visible').first
                        if auth_button.count() > 0:
                            auth_button.click(timeout=3000, force=True)
                        else:
                            page.goto("https://higgsfield.ai/auth/sign-in", wait_until="domcontentloaded", timeout=30000)
                        # Wait for the actual Microsoft button; never announce a
                        # successful click when the modal has not rendered yet.
                        microsoft_button = page.locator('button:has-text("Continue with Microsoft"):visible').first
                        try:
                            microsoft_button.wait_for(state="visible", timeout=10000)
                            microsoft_button.click(timeout=3000, force=True)
                            recovery_code_requested = False
                            recovery_baseline_ready = False
                        except Exception as restart_error:
                            print(f"Chưa mở được Microsoft: {restart_error}; tải lại trang video")
                            page.goto(HIGGSFIELD_URL, wait_until="domcontentloaded", timeout=30000)
                        # Continue the same watchdog: email, password, V2 OTP and
                        # post-login steps remain active throughout the retry.
                        continue
                        
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
                                page.evaluate("""() => {
                                    const labels = document.querySelectorAll('label');
                                    for(let l of labels) {
                                        if(l.innerText.includes('Terms of Use') || l.innerText.includes('Privacy Policy')) {
                                            const cb = l.querySelector('input[type="checkbox"]');
                                            if (cb && !cb.checked) {
                                                l.click();
                                            }
                                        }
                                    }
                                }""")
                                print("Quiz: Tích chọn 'I agree to the Terms of Use' (JS)")
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
                        # ⚡ Quét TẤT CẢ đáp án đang hiển thị bằng 1 lần JS duy nhất (nhanh hơn rất nhiều so với
                        # lặp từng locator). Chọn ngẫu nhiên 1 đáp án chưa click, scroll vào giữa và trả về tọa độ.
                        try:
                            picked = page.evaluate("""([options, clicked]) => {
                                const optSet = new Set(options);
                                const clickedSet = new Set(clicked);
                                const found = new Map();
                                const els = document.querySelectorAll('button, [role="button"], [role="radio"], [role="checkbox"], label, div, span, p, h3, h4, li');
                                for (const el of els) {
                                    const txt = (el.innerText || '').trim();
                                    if (!txt || txt.length > 80 || !optSet.has(txt) || clickedSet.has(txt) || found.has(txt)) continue;
                                    if (el.closest('a, nav, header')) continue;
                                    const target = el.closest('button, [role="button"], [role="radio"], [role="checkbox"], label') || el;
                                    const r = target.getBoundingClientRect();
                                    if (r.width < 2 || r.height < 2) continue;
                                    const st = getComputedStyle(target);
                                    if (st.visibility === 'hidden' || st.display === 'none' || target.disabled) continue;
                                    found.set(txt, target);
                                }
                                const keys = Array.from(found.keys());
                                if (keys.length === 0) return null;
                                const key = keys[Math.floor(Math.random() * keys.length)];
                                const t = found.get(key);
                                t.scrollIntoView({block: 'center', inline: 'center'});
                                const r = t.getBoundingClientRect();
                                return {text: key, x: r.left + r.width / 2, y: r.top + r.height / 2};
                            }""", [quiz_options, list(global_quiz_clicked_options)])
                        except Exception:
                            picked = None

                        if picked:
                            try:
                                page.mouse.click(picked["x"], picked["y"])
                                print(f"Quiz: Mouse clicked option '{picked['text']}'")
                                global_quiz_clicked_options.add(picked["text"])
                            except Exception: pass

                        # 3. Bấm Continue ngay khi nút được bật (poll tối đa ~2s thay vì chờ cứng)
                        try:
                            clicked = False
                            for _w in range(10):
                                clicked = page.evaluate("""() => {
                                    const btns = Array.from(document.querySelectorAll('button')).filter(b => {
                                        const text = (b.innerText || b.textContent || '').trim().toLowerCase();
                                        return (text === 'continue' || text === 'next' || text === 'submit' || text.includes('choose')) && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
                                    });
                                    if (btns.length > 0) {
                                        btns[btns.length - 1].click();
                                        return true;
                                    }
                                    return false;
                                }""")
                                if clicked or not picked:
                                    break
                                page.wait_for_timeout(200)
                            if clicked:
                                print("Quiz: JS clicked 'Continue/Next'")
                                page.wait_for_timeout(500)
                        except Exception: pass

                        continue

                        # (Code cũ bên dưới không còn chạy — giữ lại để tham khảo)
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
                            
                            # Cập nhật email khôi phục vào ms_account.txt và notes
                            try:
                                live_profile = manager.get_profile(profile_id)
                                if live_profile:
                                    ms_acc_file = Path(live_profile.user_data_dir) / "ms_account.txt"
                                    if ms_acc_file.exists():
                                        old_acc = ms_acc_file.read_text(encoding="utf-8").strip()
                                        if old_acc and "|" in old_acc:
                                            # Tránh nối chuỗi nếu đã có email khôi phục này
                                            if temp_email not in old_acc:
                                                new_acc = old_acc + f"|{temp_email}"
                                                ms_acc_file.write_text(new_acc, encoding="utf-8")
                                    
                                    # Thêm vào thẻ notes
                                    old_notes = live_profile.notes or ""
                                    if temp_email not in old_notes:
                                        live_profile.notes = (old_notes + f"\nMail khôi phục: {temp_email}").strip()
                                        manager._save()
                            except Exception as e:
                                print(f"Lỗi khi lưu temp_email: {e}")
                            
                            
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
                                        
                                        # Cập nhật email khôi phục thứ 2 vào ms_account.txt và notes
                                        try:
                                            live_profile = manager.get_profile(profile_id)
                                            if live_profile:
                                                ms_acc_file = Path(live_profile.user_data_dir) / "ms_account.txt"
                                                if ms_acc_file.exists():
                                                    old_acc = ms_acc_file.read_text(encoding="utf-8").strip()
                                                    if old_acc and "|" in old_acc:
                                                        if temp_email2 not in old_acc:
                                                            new_acc = old_acc + f"|{temp_email2}"
                                                            ms_acc_file.write_text(new_acc, encoding="utf-8")
                                                
                                                old_notes = live_profile.notes or ""
                                                if temp_email2 not in old_notes:
                                                    live_profile.notes = (old_notes + f"\nMail khôi phục (2): {temp_email2}").strip()
                                                    manager._save()
                                        except Exception as e:
                                            print(f"Lỗi khi lưu temp_email2: {e}")
                                        
                                        
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

                if captcha_active:
                    keep_open = True
                    set_watchdog_note("⚠️ Xác minh người")
                    try:
                        page.bring_to_front()
                    except Exception:
                        pass
                    print("Watchdog: hết thời gian chờ Cloudflare; giữ Chrome mở để người dùng xác minh.")
                    return

                restore_watchdog_note()

                # Login status comes only from the rendered video navigation.
                try:
                    if page.url != HIGGSFIELD_URL:
                        page.goto(HIGGSFIELD_URL, wait_until="domcontentloaded", timeout=30000)
                    login_state = wait_video_login_state(page)
                    if login_state is not True:
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                        login_state = wait_video_login_state(page)
                    if login_state is True:
                        print("Đã đăng nhập: trang video không còn nút Login/Sign up.")
                        free_info = read_free_gens(page)
                        live_profile = manager.get_profile(profile_id)
                        if free_info and live_profile:
                            free_count = free_info.get("count")
                            has_free = (
                                not free_info.get("disabled")
                                and free_info.get("enabled")
                                and (free_count is None or free_count > 0)
                            )
                            quality = read_quality(page) if has_free else ""
                            if has_free:
                                live_profile.notes = (
                                    f"free gen {free_count} {quality}" if free_count is not None and quality
                                    else f"free gen {free_count}" if free_count is not None
                                    else f"free gen {quality}" if quality
                                    else "free gen"
                                )
                            else:
                                live_profile.notes = "không free"
                            manager._save()
                            print(f"Kiểm tra Free Gens/Quality: {live_profile.notes}")
                            # Login + Free Gens/Quality check is complete; close
                            # Chrome even when the request used keep_open defaults.
                            # keep_open = False
                        elif live_profile:
                            live_profile.notes = "không free"
                            manager._save()
                            print("Không tìm thấy switch Use free gens sau khi đăng nhập")
                            # keep_open = False
                    else:
                        set_watchdog_note("lỗi login" if login_state is False else "chưa xác định đăng nhập")
                        print("Chưa xác nhận đăng nhập sau các lần tự thử lại; đã đưa về trang video.")
                except Exception as login_error:
                    print(f"Lỗi kiểm tra đăng nhập: {login_error}")
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


class ExtensionApplyReq(BaseModel):
    profile_id: Optional[str] = None
    extensions: str

@router.post("/api/extensions/apply")
def apply_extensions(req: ExtensionApplyReq):
    ext_str = req.extensions.replace("\n", ";").strip(";")
    if req.profile_id:
        p = manager.get_profile(req.profile_id)
        if p:
            p.extensions = ext_str
            manager._save()
    else:
        for p in manager.list_profiles():
            p.extensions = ext_str
        manager._save()
    return {"ok": True, "message": "Đã lưu tiện ích thành công!"}

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
