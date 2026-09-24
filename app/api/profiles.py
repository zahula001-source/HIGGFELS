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

@router.get("/api/profiles/{profile_id}/logs")
def get_logs(profile_id: str):
    log_file = BASE_DIR / "data" / "logs" / f"launch_{profile_id}.log"
    if not log_file.exists():
        return {"log": "Chưa có log"}
    return {"log": log_file.read_text(encoding="utf-8", errors="ignore")[-5000:]}

@router.post("/api/profiles/{profile_id}/auto-signup")
def auto_signup_endpoint(profile_id: str):
    import threading
    from pathlib import Path
    
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
                        if not pg.is_closed() and "higgsfield.ai" in pg.url:
                            page = pg
                            break
                    if not page:
                        page = context.new_page()
                        page.goto(HIGGSFIELD_URL, timeout=30000)
                        page.wait_for_load_state("domcontentloaded")
                    
                    page.bring_to_front()
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"Lỗi khi lấy/tạo tab Higgsfield: {e}")
                    try: p.stop()
                    except: pass
                    return
                
                # B1: Click nút Login hoặc Sign up (nếu đang ở trang chủ https://higgsfield.ai)
                if "auth/sign-in" not in page.url:
                    clicked_auth_btn = False
                    try:
                        login_btn = page.locator("a:has-text('Login'), button:has-text('Login')")
                        if login_btn.count() > 0:
                            login_btn.first.click(timeout=2000)
                            clicked_auth_btn = True
                            print("Clicked Login button")
                    except: pass
                    
                    if not clicked_auth_btn:
                        try:
                            signup_btn = page.locator("a:has-text('Sign up'), button:has-text('Sign up')")
                            if signup_btn.count() > 0:
                                signup_btn.first.click(timeout=2000)
                                clicked_auth_btn = True
                                print("Clicked Sign up button")
                        except: pass
                    
                    if not clicked_auth_btn:
                        # Fallback: tìm bằng JS
                        try:
                            page.evaluate("""() => {
                                const els = document.querySelectorAll('a, button');
                                for (let el of els) {
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
                try:
                    for _ in range(15):
                        if "quiz" in page.url or "/ai/video" in page.url:
                            print("Đã phát hiện URL login sẵn, bỏ qua chờ popup!")
                            break
                        wel_loc = page.locator("text=Welcome to Higgsfield")
                        if wel_loc.count() > 0 and wel_loc.first.is_visible():
                            print("Welcome to Higgsfield popup appeared!")
                            break
                        page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"Lỗi chờ popup: {e}")
                
                page.wait_for_timeout(1000)
                
                # B3: Click "Continue with Microsoft"
                try:
                    ms_btn = page.locator("button:has-text('Continue with Microsoft')")
                    if ms_btn.count() > 0:
                        ms_btn.first.click(timeout=3000)
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
                        if page.url.startswith("https://higgsfield.ai"): raise ValueError("Already logged in, skipping email")
                        email_input = page.locator('input[type="email"], input[name="loginfmt"], input[id="i0116"]')
                        email_input.wait_for(state="visible", timeout=10000)
                        email_input.click()
                        time.sleep(0.3)
                        email_input.fill(ms_email)
                        page.wait_for_timeout(500)
                        print(f"Filled email: {ms_email}")
                        
                        # Click nút Tiếp theo / Next
                        next_btn = page.locator('input[type="submit"][value="Tiếp theo"], input[type="submit"][value="Next"], input#idSIButton9, button:has-text("Tiếp theo"), button:has-text("Next")')
                        if next_btn.count() > 0:
                            next_btn.first.click()
                        else:
                            page.keyboard.press("Enter")
                        print("Clicked Next after email")
                        page.wait_for_timeout(3000)
                        
                    except Exception as e:
                        print(f"Error filling email: {e}")
                    
                    # Kiểm tra xem có bị chuyển hướng sang trang "Xác minh email của bạn" (chọn phương thức xác thực) không
                    # Nếu có, bấm "Sử dụng mật khẩu của bạn" để quay lại form mật khẩu
                    try:
                        page.wait_for_timeout(2000)
                        if page.url.startswith("https://higgsfield.ai"): raise ValueError("Already logged in, skipping use password")
                        use_pwd_btn = page.locator('a#iUsePasswordLink, a#idA_PWD_SwitchToPassword, span[role="button"]:has-text("Sử dụng mật khẩu của bạn"), span[role="button"]:has-text("Use your password"), span:has-text("Sử dụng mật khẩu"), text="Sử dụng mật khẩu", text="Use your password"')
                        if use_pwd_btn.count() > 0 and use_pwd_btn.first.is_visible():
                            use_pwd_btn.first.click(force=True)
                            print("Clicked 'Sử dụng mật khẩu của bạn' (Use your password)")
                            page.wait_for_timeout(2000)
                    except:
                        pass
                        
                    # Điền mật khẩu
                    try:
                        if page.url.startswith("https://higgsfield.ai"): raise ValueError("Already logged in, skipping password")
                        pwd_input = page.locator('input[type="password"], input[name="passwd"], input[id="i0118"], input#passwordEntry')
                        pwd_input.wait_for(state="visible", timeout=10000)
                        pwd_input.click()
                        import time
                        time.sleep(0.3)
                        pwd_input.fill(ms_password)
                        page.wait_for_timeout(500)
                        print(f"Filled password")
                        
                        # Click nút Tiếp theo / Sign in
                        signin_btn = page.locator('input[type="submit"][value="Tiếp theo"], input[type="submit"][value="Sign in"], input#idSIButton9, button:has-text("Tiếp theo"), button:has-text("Sign in")')
                        if signin_btn.count() > 0:
                            signin_btn.first.click()
                        else:
                            page.keyboard.press("Enter")
                        print("Clicked Sign in after password")
                        page.wait_for_timeout(4000)
                    except Exception as e:
                        print(f"Error filling password: {e}")
                    
                    # Xử lý trang "Giúp bảo vệ tài khoản của bạn" → Click "Thêm email"
                    try:
                        if page.url.startswith("https://higgsfield.ai"): raise ValueError("Already logged in, skipping protection")
                        # Đợi trang bảo vệ hoặc redirect
                        for _ in range(15):
                            cur_url = page.url
                            if "account.live.com/interrupt" in cur_url or "credentialaction" in cur_url:
                                break
                            page.wait_for_timeout(1000)
                        
                        if "account.live.com/interrupt" in page.url or "credentialaction" in page.url:
                            print("Trang bao ve tai khoan detected!")
                            # Click nút "Thêm email"
                            them_email_btn = page.locator('button:has-text("Thêm email"), input[value="Thêm email"], a:has-text("Thêm email")')
                            if them_email_btn.count() > 0:
                                them_email_btn.first.click()
                                print("Clicked 'Thêm email'!")
                            else:
                                page.evaluate("""() => {
                                    const all = document.querySelectorAll('button, input[type=submit], a');
                                    for (let el of all) {
                                        const t = (el.innerText || el.value || '').trim();
                                        if (t === 'Thêm email' || t.includes('Them email') || t.toLowerCase().includes('add email')) {
                                            el.click();
                                            return;
                                        }
                                    }
                                }""")
                                print("Clicked 'Thêm email' via JS fallback")
                            page.wait_for_timeout(2000)
                            
                            # === TinyHost API: Lấy email temp để xác minh ===
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
                                # Tìm "Mã bảo mật: XXXXXX" hoặc 6 chữ số đứng riêng
                                m = re_mod.search(r'[Mm]ã bảo mật[:\s]+(\d{6})', text)
                                if m: return m.group(1)
                                m = re_mod.search(r'security code[:\s]+(\d{6})', text, re_mod.IGNORECASE)
                                if m: return m.group(1)
                                # Tìm mọi chuỗi 6 chữ số
                                codes = re_mod.findall(r'\b(\d{6})\b', text)
                                if codes: return codes[0]
                                return None
                            
                            # Tạo email temp ngẫu nhiên
                            temp_domain = tinyhost_get_random_domain()
                            temp_user = ''.join(random_mod.choices(string.ascii_lowercase, k=6)) + ''.join(random_mod.choices(string.digits, k=4))
                            temp_email = f"{temp_user}@{temp_domain}"
                            print(f"Temp email for verification: {temp_email}")
                            
                            # Trang "Thêm địa chỉ email" - điền email temp vào
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
                            except Exception as e:
                                print(f"Error filling temp email: {e}")
                            
                            # === Poll TinyHost API để lấy mã OTP ===
                            otp_code = None
                            print(f"Polling TinyHost inbox for OTP... ({temp_email})")
                            for attempt in range(20):  # thử 20 lần, mỗi lần cách 5 giây = 100s tổng
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
                                    print(f"Waiting for OTP email... attempt {attempt+1}/20")
                            
                            if otp_code:
                                # Điền mã OTP vào trang "Nhập mã của bạn"
                                # Microsoft dùng 6 ô input riêng biệt hoặc 1 ô nhập 6 số
                                try:
                                    # Thử 6 ô riêng biệt trước
                                    otp_inputs = page.locator('input[id^="codeEntry-"], input[id^="idTxtBx_SAOTCC_OTC_"], input[maxlength="1"]')
                                    if otp_inputs.count() >= 6:
                                        for i, digit in enumerate(otp_code):
                                            if i < otp_inputs.count():
                                                otp_inputs.nth(i).fill(digit)
                                                page.wait_for_timeout(100)
                                        print(f"Filled OTP in 6 separate inputs: {otp_code}")
                                    else:
                                        # 1 ô nhập dạng text/number
                                        single_input = page.locator('input[type="text"], input[type="tel"], input[type="number"]').first
                                        single_input.fill(otp_code)
                                        print(f"Filled OTP in single input: {otp_code}")
                                    
                                    page.wait_for_timeout(500)
                                    
                                    # Click Tiếp theo để xác nhận
                                    confirm_btn = page.locator('input[type="submit"], button[type="submit"], button:has-text("Tiếp theo"), button:has-text("Verify"), button:has-text("Next")')
                                    if confirm_btn.count() > 0:
                                        confirm_btn.first.click()
                                    else:
                                        page.keyboard.press("Enter")
                                    print("Submitted OTP code!")
                                    page.wait_for_timeout(3000)
                                    
                                    # Xử lý chuỗi trang sau khi nhập mã OTP
                                    # (Đã chuyển vòng lặp pop-up ra ngoài)
                                except Exception as e:
                                    print(f"Error filling OTP: {e}")
                            else:
                                print("OTP not received within timeout. Manual intervention needed.")
                    except Exception as e:
                        print(f"Error on protection page: {e}")
                    
                    # === Vòng lặp toàn cầu xử lý các trang sau khi đăng nhập (Quiz, Yes/Accept, FIDO, Turnstile) ===
                    print("Handling post-login popups...")
                    for _ in range(30):
                        page.wait_for_timeout(2000)
                        cur_url = page.url
                        
                        if "higgsfield.ai/ai/video" in cur_url and "quiz" not in cur_url:
                            # Đợi thêm 3s để chắc chắn React không redirect ngược về Quiz
                            page.wait_for_timeout(3000)
                            if "quiz" not in page.url:
                                print("Đã đăng nhập thành công vào Higgsfield!")
                                break
                            
                        # 0.5 Kiểm tra popup Congratulations (Upgrade promotion)
                        try:
                            congrats = page.locator('text=Congratulations')
                            if congrats.count() > 0 and congrats.first.is_visible():
                                print("Đã gặp popup Congratulations! Đăng ký hoàn tất.")
                                break
                        except: pass
                            
                        # Xử lý trang Quiz (Khảo sát người dùng mới)
                        if "higgsfield.ai/quiz" in cur_url:
                            # Khởi tạo bộ nhớ tạm để không click lại đáp án cũ (tránh kẹt ở slide 1)
                            if not hasattr(page, 'quiz_clicked_options'):
                                page.quiz_clicked_options = set()

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
                                    terms_label = page.locator('label:has-text("I agree to the Terms of Use")').locator("visible=true")
                                    if terms_label.count() > 0:
                                        # Click checkbox
                                        terms_box = terms_label.first.bounding_box()
                                        if terms_box:
                                            page.mouse.click(terms_box["x"] + 10, terms_box["y"] + terms_box["height"] / 2)
                                            print("Quiz: Tích chọn 'I agree to the Terms of Use'")
                                            page.wait_for_timeout(500)
                            except Exception as e:
                                pass

                            # 2. Click các đáp án bằng Tọa độ chuột vật lý (vượt qua mọi giới hạn của React)
                            quiz_options = [
                                "For personal use", "Viral content", "Beginner", "Canvas", 
                                "Video", "Visual editing", "Supercomputer", 
                                "Instagram", "TikTok", "YouTube", 
                                "I'm new to this", "Prompting is hard",
                                "Realistic AI avatars", "Video generations"
                            ]
                            for q_text in quiz_options:
                                if q_text in page.quiz_clicked_options:
                                    continue
                                try:
                                    locs = page.get_by_text(q_text)
                                    if locs.count() > 0 and locs.last.is_visible():
                                        locs.last.scroll_into_view_if_needed()
                                        page.wait_for_timeout(200)
                                        box = locs.last.bounding_box()
                                        if box:
                                            # Di chuyển và click chuột thật vào chính giữa phần tử
                                            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                            print(f"Quiz: Mouse clicked option '{q_text}'")
                                            page.quiz_clicked_options.add(q_text)
                                            page.wait_for_timeout(800)
                                            
                                            # Kiểm tra xem nút Continue đã sáng lên chưa (nếu sáng rồi thì nghỉ click các đáp án khác)
                                            cont_btn = page.locator('button:has-text("Continue")').locator("visible=true")
                                            if cont_btn.count() > 0 and not cont_btn.first.is_disabled():
                                                break
                                except Exception as e:
                                    pass
                                    
                            # 3. Bấm Continue sau khi đã chọn xong (Kể cả popup Start with Higgsfield Academy)
                            try:
                                cont_btn = page.locator('button:has-text("Continue")').locator("visible=true")
                                if cont_btn.count() > 0 and not cont_btn.first.is_disabled():
                                    cont_btn.first.scroll_into_view_if_needed()
                                    page.wait_for_timeout(200)
                                    box = cont_btn.first.bounding_box()
                                    if box:
                                        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                        print("Quiz: Mouse clicked 'Continue'")
                                        page.wait_for_timeout(1500)
                            except Exception:
                                pass
                                
                            continue
                            
                        # 0.5. Popup "Chúng tôi đang cập nhật các điều khoản của mình" (account.live.com/tou/accrue)
                        # Phải click nút "Tiếp theo" (data-testid=primaryButton) để tiếp tục
                        try:
                            tiep_theo_btn = page.locator('button[data-testid="primaryButton"]')
                            if tiep_theo_btn.count() > 0 and tiep_theo_btn.first.is_visible():
                                btn_text = tiep_theo_btn.first.inner_text().strip().lower()
                                has_tos = (
                                    "account.live.com/tou" in cur_url or
                                    "tou/accrue" in cur_url or
                                    "tiếp theo" in btn_text or
                                    "next" in btn_text
                                )
                                if has_tos:
                                    tiep_theo_btn.first.click()
                                    print("Clicked 'Tiếp theo' on Microsoft ToS update page (data-testid=primaryButton)!")
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
                            
                        # 2. Trang chủ Higgsfield bắt đăng nhập lại
                        if "higgsfield.ai/auth/sign-in" in cur_url or ("higgsfield.ai" in cur_url and "login.microsoftonline" not in cur_url):
                            ms_btn = page.locator('button:has-text("Continue with Microsoft"), div:has-text("Continue with Microsoft")')
                            if ms_btn.count() > 0 and ms_btn.first.is_visible():
                                ms_btn.first.click()
                                print("Clicked 'Continue with Microsoft' again after redirect")
                                continue
                                
                        # 3. Form nhập email lại (nếu có)
                        email_input = page.locator('input[type="email"], input[name="loginfmt"]')
                        if email_input.count() > 0 and email_input.first.is_visible():
                            email_input.first.fill(ms_email)
                            page.keyboard.press("Enter")
                            print("Filled email again")
                            continue
                            
                        # 4. Form nhập password lại (nếu có)
                        pwd_input = page.locator('input[type="password"], input[name="passwd"]')
                        if pwd_input.count() > 0 and pwd_input.first.is_visible():
                            pwd_input.first.fill(ms_password)
                            page.keyboard.press("Enter")
                            print("Filled password again")
                            continue
                            
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
                else:
                    print("Không có thông tin tài khoản MS. Vui lòng bấm nút 'Dán mail' để thêm tài khoản trước!")
                
                # ====== BƯỚC CUỐI CÙNG: KIỂM TRA FREE GENS ======
                if "auth/sign-in" not in page.url:
                    print("Đang kiểm tra trạng thái đăng nhập và Free Gens...")
                    try:
                        page.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=30000)
                        
                        def check_login_status():
                            page.wait_for_timeout(4000)
                            status_free = False
                            status_logged = False
                            
                            # Tang 1: Kiem tra "Use free gens"
                            if page.locator('text="Use free gens"').count() > 0:
                                status_free = True
                                status_logged = True
                                print("Xac nhan login: thay 'Use free gens'!")
                                return status_logged, status_free
                                
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
                                    
                            return status_logged, status_free
                            
                        is_logged, is_free = check_login_status()
                        if not is_logged:
                            print("Chua thay dau hieu login, reload trang...")
                            page.reload(timeout=30000)
                            is_logged, is_free = check_login_status()
                            if not is_logged:
                                print("Van chua thay, reload lan cuoi...")
                                page.reload(timeout=30000)
                                is_logged, is_free = check_login_status()
                                
                        p_obj = manager.get_profile(profile.id)
                        if p_obj:
                            if is_free:
                                p_obj.notes = "free gen"
                                print("=> Cap nhat the thanh 'free gen' (Xanh la)")
                            elif is_logged:
                                p_obj.notes = "không free"
                                print("=> Cap nhat the thanh 'khong free' (Vang)")
                            else:
                                p_obj.notes = "lỗi login"
                                print("=> Cap nhat the thanh 'loi login'")
                            manager._save()
                    except Exception as e:
                        print(f"Lỗi khi kiểm tra đăng nhập/Free Gens: {e}")
                
        except Exception as e:
            print(f"Auto signup FATAL err: {e}")
        finally:
            try:
                p.stop()
            except: pass
            try:
                close_profile(profile.id)
                print(f"Đã đóng Chrome cho profile {profile.name} sau khi hoàn tất kiểm tra.")
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

