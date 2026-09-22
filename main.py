"""
Antidetect Unlimited V4 - Hỗ trợ Cookie BitBrowser + Random Fingerprint + Tabs persistence
"""
import asyncio
import threading
pw_lock = threading.Lock()
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os

from app.models import ProfileCreate, LaunchRequest
from app.browser_settings import browser_launch_options, VERSION as CLOAK_VERSION
from app.manager import manager
from app.browser import launch_profile_with_fallback, close_profile, is_running, list_running

video_tasks: dict = {}  # task_id -> status/result / "static"

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
app = FastAPI(title="Antidetect Unlimited - Camoufox Edition V4", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
@app.get("/api/profiles")
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

@app.post("/api/profiles")
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

@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str):
    if is_running(profile_id):
        close_profile(profile_id)
    ok = manager.delete_profile(profile_id)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"ok": True}

@app.post("/api/profiles/{profile_id}/duplicate")
def duplicate_profile(profile_id: str):
    new_p = manager.duplicate_profile(profile_id)
    if not new_p:
        raise HTTPException(404, "Profile not found")
    return new_p.model_dump()

@app.post("/api/profiles/{profile_id}/launch")
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

@app.post("/api/profiles/{profile_id}/auto-random-fp")
def toggle_auto_random_fp_endpoint(profile_id: str, payload: dict = Body(...)):
    state = payload.get("state", False)
    if manager.toggle_auto_random_fp(profile_id, state):
        return {"ok": True, "auto_random_fp": state}
    raise HTTPException(404, "Profile not found")

@app.post("/api/profiles/{profile_id}/close")
def close_profile_endpoint(profile_id: str):
    result = close_profile(profile_id)
    return result

@app.post("/api/profiles/{profile_id}/random-fingerprint")
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

@app.post("/api/profiles/{profile_id}/import-cookies")
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

@app.get("/api/profiles/{profile_id}/export-cookies")
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

@app.get("/api/profiles/{profile_id}/logs")
def get_logs(profile_id: str):
    log_file = BASE_DIR / "data" / "logs" / f"launch_{profile_id}.log"
    if not log_file.exists():
        return {"log": "Chưa có log"}
    return {"log": log_file.read_text(encoding="utf-8", errors="ignore")[-5000:]}

@app.get("/api/running")
def get_running():
    return list_running()

@app.get("/api/health")
def health():
    return {"status": "ok", "profiles": len(manager.list_profiles()), "running": len(list_running())}

@app.get("/api/profiles/free")
def get_free_profile():
    used_profiles = set()
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            used_profiles.add(task.get("params", {}).get("profile_id"))
    for p in list_running():
        used_profiles.add(p["id"])
    
    all_profiles = manager.list_profiles()
    free_profiles = [p.id for p in all_profiles if p.id not in used_profiles]
    return {"free_profiles": free_profiles}

@app.get("/api/select-folder")
def select_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_path = filedialog.askdirectory(title="Chọn thư mục lưu Video")
        root.destroy()
        return {"path": folder_path or ""}
    except Exception as e:
        return {"path": ""}

@app.post("/api/profiles/{profile_id}/auto-signup")
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
                browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
                context = browser.contexts[0]
                
                # Tìm tab đang ở trang higgsfield, nếu không có thì mở mới
                HIGGSFIELD_URL = "https://higgsfield.ai/ai/video?model=genjutsu"
                page = None
                for pg in context.pages:
                    if "higgsfield.ai" in pg.url:
                        page = pg
                        break
                if not page:
                    page = context.new_page()
                    page.goto(HIGGSFIELD_URL, timeout=30000)
                    page.wait_for_load_state("domcontentloaded")
                
                page.bring_to_front()
                page.wait_for_timeout(2000)
                
                # B1: Click nút Login hoặc Sign up (ấn 1 nút nào được)
                clicked_auth_btn = False
                try:
                    login_btn = page.locator("a:has-text('Login'), button:has-text('Login')")
                    if login_btn.count() > 0:
                        login_btn.first.click()
                        clicked_auth_btn = True
                        print("Clicked Login button")
                except: pass
                
                if not clicked_auth_btn:
                    try:
                        signup_btn = page.locator("a:has-text('Sign up'), button:has-text('Sign up')")
                        if signup_btn.count() > 0:
                            signup_btn.first.click()
                            clicked_auth_btn = True
                            print("Clicked Sign up button")
                    except: pass
                
                if not clicked_auth_btn:
                    # Fallback: tìm bằng JS
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
                
                # B2: Đợi popup "Welcome to Higgsfield" xuất hiện
                try:
                    page.wait_for_selector("text=Welcome to Higgsfield", timeout=15000)
                    print("Welcome to Higgsfield popup appeared!")
                except Exception as e:
                    print(f"Popup chưa xuất hiện: {e}")
                
                page.wait_for_timeout(1000)
                
                # B3: Click "Continue with Microsoft"
                try:
                    ms_btn = page.locator("button:has-text('Continue with Microsoft')")
                    if ms_btn.count() > 0:
                        ms_btn.first.click()
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
                    # Đợi trang Microsoft login load xong
                    try:
                        page.wait_for_url("*login.microsoftonline.com*", timeout=15000)
                    except:
                        try:
                            page.wait_for_url("*login.live.com*", timeout=10000)
                        except:
                            pass
                    
                    page.wait_for_timeout(2000)
                    print(f"MS login page URL: {page.url}")
                    
                    # Điền email vào ô input
                    try:
                        import time
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
                        
                        # Kiểm tra xem có bị chuyển hướng sang trang "Xác minh email của bạn" không
                        # Nếu có, bấm "Sử dụng mật khẩu của bạn" để quay lại form mật khẩu
                        use_pwd_btn = page.locator('a#iUsePasswordLink, a#idA_PWD_SwitchToPassword, a:has-text("Sử dụng mật khẩu"), a:has-text("Use your password")')
                        if use_pwd_btn.count() > 0 and use_pwd_btn.first.is_visible():
                            use_pwd_btn.first.click()
                            print("Clicked 'Sử dụng mật khẩu của bạn' (Use your password)")
                            page.wait_for_timeout(2000)
                            
                    except Exception as e:
                        print(f"Error filling email: {e}")
                    
                    # Điền mật khẩu
                    try:
                        pwd_input = page.locator('input[type="password"], input[name="passwd"], input[id="i0118"]')
                        pwd_input.wait_for(state="visible", timeout=10000)
                        pwd_input.click()
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
                                    print("Handling post-OTP popups...")
                                    for _ in range(25):
                                        page.wait_for_timeout(2000)
                                        cur_url = page.url
                                        
                                        if "higgsfield.ai/ai/video" in cur_url and "quiz" not in cur_url:
                                            print("Đã đăng nhập thành công vào Higgsfield!")
                                            break
                                            
                                        # Xử lý trang Quiz (Khảo sát người dùng mới)
                                        if "higgsfield.ai/quiz" in cur_url:
                                            # Thử click các câu trả lời
                                            for q_text in ["For personal use", "Viral content & UGC videos", "Beginner", "Canvas"]:
                                                ans_btn = page.locator(f'text="{q_text}"')
                                                if ans_btn.count() > 0 and ans_btn.first.is_visible():
                                                    ans_btn.first.click(force=True)
                                                    print(f"Quiz: Clicked '{q_text}'")
                                                    page.wait_for_timeout(800)
                                                    
                                            # Bấm Continue (nếu có ở màn hình cuối)
                                            cont_btn = page.locator('button:has-text("Continue")')
                                            if cont_btn.count() > 0 and cont_btn.first.is_visible():
                                                cont_btn.first.click(force=True)
                                                print("Quiz: Clicked 'Continue'")
                                                page.wait_for_timeout(1500)
                                            continue
                                            
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
                                                
                                        # 6. Nút Có (Yes) / Chấp nhận (Accept) - Duy trì đăng nhập / Cho phép ứng dụng
                                        yes_btn = page.locator('input#idSIButton9, button#idSIButton9, input[value="Có"], input[value="Yes"], input[value="Chấp nhận"], input[value="Accept"], button:has-text("Chấp nhận")')
                                        if yes_btn.count() > 0 and yes_btn.first.is_visible():
                                            yes_btn.first.click()
                                            print("Clicked Yes / Accept")
                                            continue
                                            
                                        # 7. Tích chọn Cloudflare Turnstile "Xác minh bạn là con người"
                                        try:
                                            # Nếu nằm ngoài cùng
                                            cf_checkbox = page.locator('input[type="checkbox"][aria-label*="con người"], input[type="checkbox"][aria-label*="human"]')
                                            if cf_checkbox.count() > 0 and cf_checkbox.first.is_visible():
                                                cf_checkbox.first.click(force=True, position={"x": 5, "y": 5})
                                                print("Clicked Turnstile checkbox (main frame)")
                                                continue
                                                
                                            # Nếu nằm trong iframe
                                            cf_iframe = page.frame_locator('iframe[src*="cloudflare.com"], iframe[src*="turnstile"]')
                                            cf_checkbox_iframe = cf_iframe.locator('input[type="checkbox"]')
                                            if cf_checkbox_iframe.count() > 0:
                                                cf_checkbox_iframe.first.click(force=True)
                                                print("Clicked Turnstile checkbox (in iframe)")
                                                continue
                                        except Exception:
                                            pass
                                except Exception as e:
                                    print(f"Error filling OTP: {e}")
                            else:
                                print("OTP not received within timeout. Manual intervention needed.")
                    except Exception as e:
                        print(f"Error on protection page: {e}")
                else:
                    print("Không có thông tin tài khoản MS. Vui lòng bấm nút 'Dán mail' để thêm tài khoản trước!")
                
                try:
                    p.stop()
                except: pass
        except Exception as e:
            print(f"Auto signup FATAL err: {e}")

    threading.Thread(target=run_auto_signup, daemon=True).start()
    return {"ok": True, "message": "Bắt đầu Auto Login Higgsfield (Microsoft)..."}

@app.post("/api/profiles/{profile_id}/set-ms-account")
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


import threading
import uuid as uuid_module
from fastapi import UploadFile, File, Form
from fastapi.responses import JSONResponse

video_tasks_chat: dict = {}

@app.get("/api/tasks/{task_id}/chat")
def get_task_chat(task_id: str):
    return video_tasks_chat.get(task_id, {"messages": [], "queue": []})

@app.post("/api/tasks/{task_id}/chat")
def send_task_chat(task_id: str, payload: dict = Body(...)):
    if task_id in video_tasks_chat:
        video_tasks_chat[task_id]["queue"].append(payload.get("message", ""))
    return {"ok": True}

GLOBAL_MAX_RETRIES = 20

@app.post("/api/settings/max_retries")
def set_max_retries(val: int = Form(...)):
    global GLOBAL_MAX_RETRIES
    if val > 0:
        GLOBAL_MAX_RETRIES = val
    return {"ok": True}

def _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=False, is_headless=False):
    """Mở trình duyệt với Random FP và kích hoạt extension
    only_navigator=True: chỉ bật nút 1 (Spoof Navigator) - dùng khi cần tải ảnh
    close_old_tabs=True: đóng hết các tab cũ khi mở lên (chỉ dùng cho video creation)
    """
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
    if ext_path:
        args.append(f"--load-extension={ext_path}")
        ignore_args = ["--disable-extensions"]
    else:
        args.append("--disable-extensions")
    if is_headless:
        # Tắt chế độ headless thật để tránh bị website phát hiện/cắt xén DOM
        # Thay vào đó, đẩy cửa sổ ra tít ngoài màn hình để giấu giao diện đi (vẫn tiết kiệm tài nguyên mà an toàn 100%)
        args.append("--window-position=-32000,-32000")
        args.append("--window-size=1366,768")
        
    context = p.chromium.launch_persistent_context(
        profile.user_data_dir,
        headless=False,
        **browser_launch_options(),
        ignore_default_args=ignore_args,
        args=args,
        accept_downloads=True,
        downloads_path=str(Path.home() / "Downloads"),
    )

    # Chrome tự xử lý download 100% native - Không chặn, không xử lý bằng Playwright để tránh crash/lỗi .crdownload


    try:
        import random
        ext_page = context.new_page()
        ext_page.goto("chrome-extension://facgnnelgcipeopfbjcajpaibhhdjgcp/popup.html", wait_until="load", timeout=5000)
        try:
            ext_page.wait_for_function("document.querySelector('#spoofCanvas') && document.querySelector('#spoofCanvas').textContent !== ''", timeout=3000)
        except:
            pass
            
        # Lần 1: OFF, OFF (0)
        # Lần 2: ON, OFF (1)
        # Lần 3: OFF, ON (2)
        # Lần 4: ON, ON (3)
        state = (attempt - 1) % 4
        btn1_on = (state == 1 or state == 3)
        btn2_on = (state == 2 or state == 3)
        
        script = f"""() => {{
            const navBtn = document.querySelector('#spoofNav');
            const canBtn = document.querySelector('#spoofCanvas');
            
            if ({'true' if btn1_on else 'false'}) {{
                if (navBtn && !navBtn.classList.contains('btn-danger')) navBtn.click();
            }} else {{
                if (navBtn && navBtn.classList.contains('btn-danger')) navBtn.click();
            }}
            
            if ({'true' if btn2_on else 'false'}) {{
                if (canBtn && !canBtn.classList.contains('btn-danger')) canBtn.click();
            }} else {{
                if (canBtn && canBtn.classList.contains('btn-danger')) canBtn.click();
            }}
        }}"""
        
        try:
            ext_page.evaluate(script)
        except: pass
                
        ext_page.close()
    except:
        pass
    
    # Đóng tab trống của extension hoặc about:blank
    try:
        for pg in context.pages:
            try:
                if pg.url in ('about:blank', '') or pg.url.startswith('chrome-extension://'):
                    pg.close()
            except:
                pass
    except:
        pass
    return context

def _activate_canvas_spoof(context, ext_path):
    """Kích hoạt Spoof Canvas SAU khi đã upload ảnh thành công"""
    return # Không mở popup extension này nữa theo yêu cầu
    try:
        ext_page = context.new_page()
        ext_page.goto("chrome-extension://facgnnelgcipeopfbjcajpaibhhdjgcp/popup.html", wait_until="load", timeout=5000)
        ext_page.wait_for_timeout(500)
        try:
            ext_page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('*'));
                const canOff = btns.find(e => e.innerText === 'Spoof Canvas');
                if (canOff) canOff.click();
            }""")
        except:
            pass
        ext_page.close()
    except:
        pass


def _handle_auto_login(page, video_tasks, task_id):
    if "auth.bfl.ai" in page.url:
        if video_tasks and task_id:
            video_tasks[task_id]["message"] = "Trang yêu cầu đăng nhập. Đang tự động điền mật khẩu..."
        try:
            page.wait_for_timeout(3000)
            email = page.evaluate("""() => {
                const el = document.querySelector('input[type="email"], input[name="email"], input[name="identifier"]');
                if (el && el.value) return el.value;
                const match = document.body.innerText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                return match ? match[0] : null;
            }""")
            
            if email:
                pwd = email.split('@')[0] + '@H1'
                
                page.wait_for_timeout(500)
                try:
                    import random
                    import time
                    p_loc = page.locator('input[type="password"], input[name="password"]')
                    p_loc.wait_for(state="visible", timeout=5000)
                    p_loc.click()
                    time.sleep(0.5)
                    for char in pwd:
                        p_loc.press_sequentially(char)
                        time.sleep(random.uniform(0.05, 0.25))
                except:
                    # Fallback nếu click/type lỗi
                    page.evaluate(f"""(pwd) => {{
                        const pEl = document.querySelector('input[type="password"], input[name="password"]');
                        if (pEl) {{
                            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            nativeSetter.call(pEl, pwd);
                            pEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            pEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    }}""", pwd)
                
                page.wait_for_timeout(500)
                
                page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (let b of btns) {
                        const t = (b.innerText || "").toLowerCase();
                        if (t.includes('sign in') || t.includes('continue')) {
                            b.click();
                            break;
                        }
                    }
                }""")
                
                try:
                    page.wait_for_url("**/dashboard.bfl.ai/**", timeout=15000)
                except: pass
                
                page.wait_for_timeout(3000)
        except:
            pass

def _fill_form(page, context, ext_path, prompt, img1_path, img2_path, video_tasks, task_id, is_retry=False):
    """Điền prompt + upload ảnh vào bfl.ai. Trả về True nếu OK."""
    _handle_auto_login(page, video_tasks, task_id)
    
    # Đợi textarea
    try:
        page.wait_for_selector("textarea[placeholder*='Describe']", timeout=15000)
    except:
        return False

    # Điền prompt bằng JS (tránh overlay chặn)
    page.evaluate("""(text) => {
        const ta = document.querySelector("textarea[placeholder*='Describe']");
        if (ta) {
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
            nativeSetter.call(ta, text);
            ta.dispatchEvent(new Event('input', { bubbles: true }));
            ta.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }""", prompt)
    page.wait_for_timeout(800)

    if is_retry:
        # Nếu là retry, ảnh đã được lưu ở session bfl.ai nên KHÔNG CẦN TẢI LẠI
        video_tasks[task_id] = {"status": "running", "message": "Form đã sẵn sàng (bỏ qua bước tải ảnh)."}
        return True

    # Bỏ ảnh cũ trước khi tải ảnh mới (kể cả khi không có ảnh mới cũng bỏ)
    try:
        page.evaluate("""() => {
            const removeBtns = document.querySelectorAll("button[aria-label^='Remove']");
            removeBtns.forEach(b => b.click());
        }""")
        page.wait_for_timeout(1000)
    except:
        pass

    # Click nút "All parameters" để hiện phần tải ảnh (giao diện bfl.ai mới cập nhật)
    try:
        page.evaluate("""() => {
            const btns = document.querySelectorAll("button");
            for (let b of btns) {
                if (b.innerText && b.innerText.toUpperCase().includes('ALL PARAMETERS')) {
                    b.click();
                    break;
                }
            }
        }""")
        page.wait_for_timeout(1000)
    except:
        pass

    img1_ok = False
    if img1_path and Path(img1_path).exists():
        # Upload ảnh 1 - Start frame (Spoof Canvas CHƯA được bật ở bước này)
        video_tasks[task_id] = {"status": "running", "message": "Đang tải ảnh 1 (Start frame)..."}
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                page.locator("button[aria-label='Attach start frame']").click()
            fc_info.value.set_files(img1_path)
            page.wait_for_timeout(2000)
            img1_ok = True
        except:
            try:
                page.locator("input[type='file']").first.set_input_files(img1_path)
                page.wait_for_timeout(2000)
                img1_ok = True
            except Exception as e:
                video_tasks[task_id] = {"status": "running", "message": f"Cảnh báo tải ảnh 1: {e}"}

    # ✅ Ảnh 1 đã upload thành công → Giờ mới bật Spoof Canvas an toàn
    if img1_ok:
        video_tasks[task_id] = {"status": "running", "message": "Ảnh 1 OK! Đang kích hoạt Spoof Canvas..."}
        _activate_canvas_spoof(context, ext_path)
        page.wait_for_timeout(500)

    # Upload ảnh 2 - End frame (optional)
    if img2_path and Path(img2_path).exists():
        video_tasks[task_id] = {"status": "running", "message": "Đang tải ảnh 2 (End frame)..."}
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                page.locator("button[aria-label='Attach end frame']").click()
            fc_info.value.set_files(img2_path)
            page.wait_for_timeout(2000)
        except:
            try:
                page.locator("input[type='file']").nth(1).set_input_files(img2_path)
                page.wait_for_timeout(2000)
            except:
                pass
    return True

def _get_generating_status(page, target_prompt=None) -> str:
    """Kiểm tra xem có xuất hiện 'GENERATING' hoặc 'QUEUED' ở giữa màn hình không và lấy text"""
    try:
        snippet = ""
        if target_prompt:
            snippet = " ".join(target_prompt.split())[:30].strip()
            
        result = page.evaluate("""(snippet) => {
            function findStatusText(container) {
                const allElements = Array.from(container.querySelectorAll('*'));
                for (let el of allElements) {
                    if (el.children.length === 0) {
                        const txt = (el.innerText || "").toUpperCase().trim();
                        if (txt.startsWith('QUEUED') || txt.startsWith('GENERATING')) {
                            if (txt.includes('VOLUME')) continue;
                            const parent = el.parentElement;
                            if (parent) {
                                const pText = parent.innerText.replace(/\\n/g, ' ');
                                if (pText.length < 50 && pText.match(/\\d/)) {
                                    return pText;
                                }
                            }
                        }
                    }
                }
            }
            
            if (snippet) {
                const articles = document.querySelectorAll('article');
                for (let a of articles) {
                    if (a.textContent.includes(snippet)) {
                        return findStatusText(a);
                    }
                }
            } else {
                return findStatusText(document);
            }
        }""", snippet)
        return result
    except:
        return None

def _is_rate_limited(page) -> bool:
    """Kiểm tra xem có bị lỗi hệ thống (Rate limited, 503, Over capacity) không"""
    try:
        result = page.evaluate("""() => {
            const allText = (document.body.innerText || "").toUpperCase();
            return allText.includes('RATE LIMITED') || 
                   allText.includes('SYSTEM_ERROR') ||
                   allText.includes('SERVICE ISSUE') ||
                   allText.includes('STATUS 503') ||
                   allText.includes('OVER CAPACITY');
        }""")
        return result
    except:
        return False

def _get_new_video_url(page, target_prompt: str):
    """Lấy URL video MỚI nhất có chứa prompt tương ứng. Đảm bảo 100% không bắt nhầm video cũ."""
    try:
        snippet = " ".join(target_prompt.split())[:30].strip()
        result = page.evaluate("""(snippet) => {
            const articles = document.querySelectorAll('article');
            for (let a of articles) {
                if (a.textContent.includes(snippet)) {
                    const videos = a.querySelectorAll('video');
                        if (v.src && v.src.startsWith('http')) return v.src;
                        if (s && s.src && s.src.startsWith('http')) return s.src;
                    }
                }
            }
        }""", snippet)
        
        if result:
            return result
    except:
        pass
    return None

def _send_video_to_telegram(video_path, token, chat_id):
    if not token or not chat_id: return
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendVideo"
        with open(video_path, 'rb') as f:
            requests.post(url, data={"chat_id": chat_id}, files={"video": f}, timeout=30)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def run_video_automation(task_id, prompt, img1_path, img2_path, profile_id, save_path, is_headless=False, enable_ext=False, enable_ext_btn2=False, tg_enabled=False, tg_token="", tg_chat_id="", video_model="Dreamina Seedance 2.0 Fast", video_duration="10s", video_ratio="9:16"):
    """Background thread: mở higgsfield.ai, đăng nhập Google, upload ảnh, nhập prompt và tạo video."""
    from playwright.sync_api import sync_playwright
    import urllib.parse
    import uuid
    import time
    from pathlib import Path

    if not save_path:
        save_path = str(Path.home() / "Downloads")
    else:
        save_path = str(Path(save_path))

    manager.randomize_fingerprint(profile_id)
    profile = manager.get_profile(profile_id)
    if not profile:
        video_tasks[task_id] = {"status": "error", "message": "Profile not found"}
        return

    if enable_ext:
        ext_path = str((Path(BASE_DIR) / "data" / "extensions" / "fingerprint_spoofer").absolute())
    else:
        ext_path = None
    global GLOBAL_MAX_RETRIES

    video_tasks[task_id] = {"status": "running", "message": "Đang mở trình duyệt..."}
    video_tasks_chat[task_id] = {"messages": [], "queue": []}
    is_retrying = False

    def sync_chat(pg):
        if task_id not in video_tasks_chat: return
        try:
            msgs = pg.evaluate("""() => {
                try {
                    // CÁCH CHẮC CHẮN NHẤT: Bắt thẳng vào trái tim của mọi tin nhắn (khung chứa chữ)
                    let textContainers = Array.from(document.querySelectorAll('.container-enLQFx, .container-fBOrXO, [data-message-id]'));
                    
                    if (textContainers.length === 0) return [{role: "bot", text: "DEBUG: Không tìm thấy bất kỳ thẻ text nào trong DOM!"}];

                    const results = textContainers.map(node => {
                        // Tránh lấy trùng lặp nếu querySelectorAll lấy cả cha lẫn con
                        // Ưu tiên lấy text từ container trong cùng
                        let txt = node.innerText || node.textContent || "";
                        txt = txt.replace('Tải về cho Windows', '').trim();
                        
                        // Xác định User/Bot bằng cách dò ngược lên các thẻ cha xem có đặc điểm của User không
                        const isUser = node.classList.contains('justify-end') || 
                                       (node.closest && node.closest('.justify-end') !== null) ||
                                       (node.parentElement && node.parentElement.classList.contains('justify-end'));
                                       
                        return { role: isUser ? "user" : "bot", text: txt };
                    }).filter(Boolean);
                    
                    if (results.length === 0) return [{role: "bot", text: `DEBUG: Tìm thấy ${textContainers.length} thẻ nhưng bị filter do rỗng!`}];
                    
                    // Lọc bỏ các tin nhắn bị trùng lặp (giữ lại cái dài nhất nếu bị lồng nhau)
                    const uniqueResults = [];
                    for(let r of results) {
                        const existing = uniqueResults.find(x => x.text === r.text || x.text.includes(r.text) || r.text.includes(x.text));
                        if(!existing) {
                            uniqueResults.push(r);
                        } else if (r.text.length > existing.text.length) {
                            // Cập nhật lại nếu tìm thấy chuỗi bao hàm dài hơn
                            existing.text = r.text;
                        }
                    }
                    return uniqueResults;
                } catch(e) {
                    return [{role: "bot", text: "Lỗi bóc tách: " + e.message}];
                }
            }""")
            if msgs is not None:
                video_tasks_chat[task_id]["messages"] = msgs
            
            while len(video_tasks_chat[task_id]["queue"]) > 0:
                msg = video_tasks_chat[task_id]["queue"].pop(0)
                try:
                    input_loc = pg.locator("div[contenteditable='true']").first
                    input_loc.fill(msg)
                    pg.wait_for_timeout(500)
                    input_loc.press("Enter")
                except: pass
        except: pass

    try:
        with pw_lock:
            p = sync_playwright().start()
        if True:
            context = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=enable_ext_btn2, is_headless=is_headless)
            
            # Tái sử dụng tab đầu tiên nếu có để tránh mở nhiều tab
            page = None
            for _ in range(5):
                if context.pages:
                    page = context.pages[0]
                    break
                else:
                    try:
                        page = context.new_page()
                        break
                    except Exception as e:
                        print(f"Lỗi lấy page, thử lại sau 1s: {e}")
                        time.sleep(1)
            
            if not page:
                raise Exception("Không thể khởi tạo tab Chrome. Vui lòng tắt thủ công Chrome của profile này và thử lại!")
                
            # Đóng các tab dư thừa
            for i in range(1, len(context.pages)):
                try: context.pages[i].close()
                except: pass

            # (ĐÃ BỎ CẮT COOKIE HIGGSFIELD ĐỂ GIỮ TRẠNG THÁI LOGIN TỪ PROFILE)
            # video_tasks[task_id] = {"status": "running", "message": "Đang giả lập máy tính hoàn toàn mới (Clear Cookies)..."}
            # ... đoạn code xóa cookie đã bị vô hiệu hóa ...

            # ── BƯỚC 1: Mở higgsfield.ai/chat ──────────────────────────────────
            video_tasks[task_id] = {"status": "running", "message": "Đang mở higgsfield.ai/ai/video..."}
            page.goto("https://higgsfield.ai/ai/video?model=genjutsu", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            
            # Xử lý trang lỗi "This page is temporarily unavailable"
            try:
                if page.locator("text='This page is temporarily unavailable'").is_visible(timeout=3000):
                    video_tasks[task_id] = {"status": "running", "message": "higgsfield bị lỗi tạm thời, đang ấn Refresh..."}
                    page.locator("button:has-text('Refresh')").click(timeout=3000)
                    page.wait_for_timeout(5000)
            except:
                pass

            def check_age_popup(pg):
                try:
                    pg.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                        const confirmBtn = btns.reverse().find(el => el.innerText && (
                            el.innerText.trim() === 'Confirm' || 
                            el.innerText.trim() === 'Xác nhận' ||
                            el.innerText.trim() === 'OK' ||
                            el.innerText.trim() === 'Ok'
                        ));
                        if (confirmBtn) {
                            confirmBtn.click();
                            console.log("Clicked Confirm Age popup!");
                        }
                    }""")
                except:
                    pass

            # ── BƯỚC 2: Kiểm tra đã login chưa (Dựa vào sự tồn tại của nút Log In) ──
            video_tasks[task_id] = {"status": "running", "message": "Kiểm tra trạng thái đăng nhập..."}
            already_logged_in = False
            try:
                # Đợi cho trang load xong và các phần tử ổn định
                try:
                    page.wait_for_load_state("load", timeout=10000) # Dùng load thay vì networkidle cho lẹ
                except:
                    pass
                
                # ── BƯỚC 2: Kiểm tra đã login chưa (Kiểm tra Avatar -> Settings) ──
                is_logged_in = False
                try:
                    import re
                    # Tìm nút Avatar (Mở rộng selector để bao quát cả giao diện higgsfield mới)
                    # Ưu tiên tìm theo aria-label="Account menu" là chuẩn nhất cho bản mới
                    avatar_loc = page.locator('button[aria-label="Account menu"], button[aria-haspopup="menu"], button:has(.rounded-full), div[role="button"]:has(.rounded-full)').filter(has_not_text=re.compile(r"^(Đăng nhập|Log In|Sign In)$", re.IGNORECASE)).last
                    
                    if avatar_loc.is_visible(timeout=2000):
                        avatar_loc.click(timeout=3000)
                        page.wait_for_timeout(1000)
                        
                        # Kiểm tra xem có menu Settings/Cài đặt/Đăng xuất/Công việc xổ ra không
                        has_settings = page.evaluate("""() => {
                            const allBtns = Array.from(document.querySelectorAll('button, p, div, span, a'));
                            return allBtns.some(b => b.innerText && (
                                b.innerText.trim() === 'Settings' || 
                                b.innerText.trim() === 'Cài đặt' || 
                                b.innerText.trim() === 'Đăng xuất' || 
                                b.innerText.trim() === 'Log out' ||
                                b.innerText.trim() === 'Sign Out' ||
                                b.innerText.trim() === 'Tài khoản' ||
                                b.innerText.trim() === 'Account'
                            ));
                        }""")
                        
                        if has_settings:
                            is_logged_in = True
                            page.mouse.click(0, 0) # Click ra ngoài để đóng menu
                            page.wait_for_timeout(500)
                except Exception as inner_e:
                    print(f"Lỗi soi avatar: {inner_e}")
                    pass
                
                already_logged_in = is_logged_in
                print(f"--- [BƯỚC 2] Kết quả quét trạng thái: {'ĐÃ LOGIN TỪ TRƯỚC' if already_logged_in else 'CHƯA LOGIN (Sẽ chạy Bước 3 & 4)'}")
            except Exception as e:
                print(f"--- Lỗi kiểm tra login: {e}")
                already_logged_in = False

            if not already_logged_in:
                # Quét xem có modal "Log In to Unlock More Features" đang mở sẵn không
                is_modal_open = False
                try:
                    is_modal_open = page.locator("text='Log In to Unlock More Features'").is_visible(timeout=2000)
                except:
                    pass
                
                if not is_modal_open:
                    # ── BƯỚC 3: Ấn "Đăng nhập" / "Log In" ───────────────────────
                    video_tasks[task_id] = {"status": "running", "message": "Đang mở bảng Đăng nhập..."}
                    
                    try:
                        # Vòng lặp ấn nút Log In cho đến khi bảng hiện ra (tối đa 5 lần)
                        for _ in range(5):
                            # Tìm nút Log In (thường nằm góc phải trên cùng)
                            login_btn = page.locator("button, a").filter(has_text=re.compile(r"^(Đăng nhập|Log In|Login|Sign In)$", re.IGNORECASE)).first
                            if login_btn.is_visible():
                                box = login_btn.bounding_box()
                                if box:
                                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                    page.wait_for_timeout(300)
                                    page.mouse.down()
                                    page.wait_for_timeout(150)
                                    page.mouse.up()
                                    page.wait_for_timeout(500)
                                    # Fallback click JS nếu mouse click bị xịt
                                    page.evaluate("""(btn) => { if(btn) btn.click(); }""", login_btn.element_handle())
                            else:
                                # Nếu không thấy nút Log In, thử tìm nút bất kỳ ở góc trên bên phải
                                page.evaluate("""() => {
                                    const btns = Array.from(document.querySelectorAll('button'));
                                    const loginBtn = btns.find(b => b.innerText && b.innerText.toLowerCase().includes('log'));
                                    if(loginBtn) loginBtn.click();
                                }""")
                            
                            page.wait_for_timeout(2000) # Đợi 2s để bảng bung ra rồi check lại
                            
                            try:
                                is_modal = page.locator("text='Log In to Unlock More Features'").is_visible(timeout=1000)
                                if is_modal:
                                    print("--- Đã thấy bảng Log In to Unlock More Features!")
                                    break
                            except:
                                pass
                    except Exception as e:
                        print(f"--- Lỗi khi ấn nút Log In: {e}")
                else:
                    print("--- Bảng đăng nhập đã mở sẵn!")

                # ── BƯỚC 4: Ấn "Continue with Google" / "Tiếp tục bằng Google" ──
                try:
                    video_tasks[task_id] = {"status": "running", "message": "Đang dò tọa độ nút Google để click thật..."}
                    
                    # Chờ 3s cho popup có thời gian bung ra hoàn chỉnh
                    page.wait_for_timeout(3000)
                    
                    # Dùng JS lấy tọa độ (x, y, width, height) của nút thay vì click ảo bằng JS (vì JS click ảo bị web bỏ qua)
                    js_get_rect = """
                    () => {
                        let btn = document.evaluate(
                          "//button[.//*[normalize-space()='Continue with Google']]",
                          document,
                          null,
                          XPathResult.FIRST_ORDERED_NODE_TYPE,
                          null
                        ).singleNodeValue;
                        
                        if (!btn) {
                            const btns = Array.from(document.querySelectorAll('button'));
                            btn = btns.find(b => b.innerText && b.innerText.includes('Google'));
                        }
                        
                        if (btn) {
                            const rect = btn.getBoundingClientRect();
                            return {
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height,
                                found: true
                            };
                        }
                        return { found: false };
                    }
                    """
                    
                    success_click = False
                    for i in range(15): # Lặp 15 lần (tối đa 30s)
                        try:
                            rect_info = page.evaluate(js_get_rect)
                            if rect_info and rect_info.get("found"):
                                # Dùng Playwright di chuột VẬT LÝ đến tọa độ tâm nút và nhấp đúp như người thật
                                center_x = rect_info["x"] + rect_info["width"] / 2
                                center_y = rect_info["y"] + rect_info["height"] / 2
                                
                                page.mouse.move(center_x, center_y, steps=10)
                                page.wait_for_timeout(500)
                                
                                # Click lần 1
                                page.mouse.down()
                                page.wait_for_timeout(100)
                                page.mouse.up()
                                page.wait_for_timeout(200)
                                
                                # Click lần 2
                                page.mouse.down()
                                page.wait_for_timeout(150)
                                page.mouse.up()
                                
                                # Kiểm tra xem bảng popup đã biến mất chưa (chứng tỏ click ăn, mở popup Google)
                                page.wait_for_timeout(3000)
                                check_still_there = page.evaluate(js_get_rect)
                                if not check_still_there.get("found"):
                                    print(f"--- [BƯỚC 4] Đã CLICK THẬT thành công nút Google ở lần thử {i+1}!")
                                    success_click = True
                                    break
                                else:
                                    print(f"--- [BƯỚC 4] Lần {i+1}: Đã ấn chuột vật lý nhưng popup chưa tắt, thử lại...")
                            else:
                                print(f"--- [BƯỚC 4] Lần {i+1}: Chưa thấy nút Google. Có thể do click Log In hụt, đang thử click lại Log In...")
                                try:
                                    # Tìm nút bằng nhiều cách để chắc chắn không trượt
                                    login_btn = page.locator('button:has-text("Log In"), button:has-text("Login"), .login-btn-header-CTKsn1').first
                                    if login_btn.is_visible(timeout=500):
                                        box = login_btn.bounding_box()
                                        if box:
                                            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                            page.wait_for_timeout(200)
                                            page.mouse.down()
                                            page.wait_for_timeout(100)
                                            page.mouse.up()
                                except:
                                    pass
                        except Exception as js_err:
                            print(f"--- [BƯỚC 4] Lỗi JS lần {i+1}: {js_err}")
                        
                        page.wait_for_timeout(2000)
                    
                    if not success_click:
                        # CHẶN CHẠY MÙ QUÁNG: Báo lỗi và dừng tiến trình
                        video_tasks[task_id] = {"status": "error", "message": "Lỗi: Quá thời gian chờ nút Continue with Google."}
                        print("====== [LỖI] KHÔNG THỂ ẤN NÚT GOOGLE, DỪNG TIẾN TRÌNH TRÁNH CHẠY MÙ QUÁNG ======")
                        return
                    
                    # Đã click thành công, chờ Google Auth xử lý
                    page.wait_for_timeout(6000)
                except Exception as e:
                    print(f"\n====== LỖI BƯỚC 4 ======\n{str(e)}\n========================\n")
                    video_tasks[task_id] = {"status": "error", "message": f"Lỗi ở bước đăng nhập Google: {str(e)}"}
                    return # Ngăn chạy tiếp xuống các bước tạo video

                # ── BƯỚC 5 & 6: Xử lý Xác nhận tuổi (nếu có) và Chờ đăng nhập thành công ──
                video_tasks[task_id] = {"status": "running", "message": "Đang chờ đăng nhập hoàn tất..."}
                try:
                    page.wait_for_timeout(4000) # Đợi trang load xong sau khi Auth
                    
                    login_success = False
                    for _ in range(15): # Lặp tối đa ~30s
                        # 0. Quét xem có bị báo lỗi Limit từ server higgsfield không
                        try:
                            limit_msg = page.evaluate("""() => {
                                const texts = ['Maximum number of attempts reached', "Couldn't load", 'experiencing high demand'];
                                return texts.find(t => document.body && document.body.innerText.includes(t));
                            }""")
                            if limit_msg:
                                video_tasks[task_id] = {"status": "limit", "message": f"Tài khoản đã bị Limit: {limit_msg}"}
                                print(f"====== [LIMIT] TÀI KHOẢN BỊ GIỚI HẠN: {limit_msg} ======")
                                return
                        except: pass
                        
                        # 1. Quét xem có dialog xác nhận tuổi không, nếu có thì click
                        check_age_popup(page)
                        
                        page.wait_for_timeout(1000)
                        
                        # 2. Bấm vào nút Avatar bằng Playwright (như người thật) thay vì JS
                        try:
                            # Nút button có aria-haspopup="menu" và chứa thẻ img.rounded-full
                            avatar_loc = page.locator('button[aria-haspopup="menu"]:has(img.rounded-full)').first
                            if avatar_loc.count() > 0:
                                avatar_loc.click(timeout=2000)
                        except:
                            pass
                            
                        page.wait_for_timeout(1000)
                        
                        # 3. Kiểm tra xem menu Settings có xổ ra không
                        has_settings = page.evaluate("""() => {
                            const allBtns = Array.from(document.querySelectorAll('button, p, div, span'));
                            return allBtns.some(b => b.innerText && (b.innerText.includes('Settings') || b.innerText.includes('Cài đặt')));
                        }""")
                        
                        if has_settings:
                            login_success = True
                            # Click ra ngoài để đóng menu Settings
                            page.mouse.click(0, 0)
                            page.wait_for_timeout(500)
                            break
                            
                        page.wait_for_timeout(1000)

                    if login_success:
                        video_tasks[task_id] = {"status": "running", "message": "✅ Đăng nhập thành công! Đang chuẩn bị tạo video..."}
                    else:
                        raise Exception("Không tìm thấy menu Settings, đăng nhập có thể đã thất bại.")
                        
                except Exception as e:
                    video_tasks[task_id] = {"status": "error", "message": f"Đăng nhập thất bại: {e}"}
                    try: context.close()
                    except: pass
                    return
            else:
                video_tasks[task_id] = {"status": "running", "message": "✅ Đã đăng nhập sẵn! Đang chuẩn bị tạo video..."}

            page.wait_for_timeout(1500)

            # ĐỀ PHÒNG WEB TỰ VĂNG (LOGOUT)
            if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Google'))"):
                raise Exception("Tài khoản higgsfield bị văng (Logout) giữa chừng. Vui lòng tắt và CHẠY LẠI profile này!")

            # ── BƯỚC 7: Ấn nút "Tạo video" trong thanh công cụ ──────────────
            video_tasks[task_id] = {"status": "running", "message": "Đang ấn nút 'Tạo video'..."}
            try:
                page.locator("button[data-skill-id='skill_bar_button_17']").click(timeout=8000)
                page.wait_for_timeout(1000)
            except:
                try:
                    page.evaluate("""() => {
                        const all = Array.from(document.querySelectorAll('button'));
                        const btn = all.find(el => el.innerText && el.innerText.trim().includes('Tạo video'));
                        if (btn) btn.click();
                    }""")
                    page.wait_for_timeout(1000)
                except:
                    pass

            # ── BƯỚC 7.5: Chọn Model, Duration, Ratio ──────────────
            video_tasks[task_id] = {"status": "running", "message": "Đang chọn cài đặt video..."}
            try:
                # Chọn Model
                if video_model:
                    page.locator('button[data-input-engine-actionbar-control-key="video-model"]').click(timeout=3000)
                    page.wait_for_timeout(500)
                    page.evaluate(f"""(text) => {{
                        const items = Array.from(document.querySelectorAll('div[role="menuitem"], div[role="menuitemradio"], div[role="option"], button'));
                        const item = items.find(el => el.innerText && el.innerText.trim().includes(text));
                        if(item) item.click();
                    }}""", video_model)
                    page.wait_for_timeout(500)
                
                # Chọn Duration
                if video_duration:
                    page.locator('button[data-input-engine-actionbar-control-key="video-duration"]').click(timeout=3000)
                    page.wait_for_timeout(500)
                    page.evaluate(f"""(text) => {{
                        const items = Array.from(document.querySelectorAll('div[role="menuitem"], div[role="menuitemradio"], div[role="option"], button'));
                        const item = items.find(el => el.innerText && el.innerText.trim() === text);
                        if(item) item.click();
                    }}""", video_duration)
                    page.wait_for_timeout(500)
                    
                # Chọn Ratio
                if video_ratio:
                    page.locator('button[data-input-engine-actionbar-control-key="video-ratio"]').click(timeout=3000)
                    page.wait_for_timeout(500)
                    page.evaluate(f"""(text) => {{
                        const items = Array.from(document.querySelectorAll('div[role="menuitem"], div[role="menuitemradio"], div[role="option"], button'));
                        const item = items.find(el => el.innerText && el.innerText.trim() === text);
                        if(item) item.click();
                    }}""", video_ratio)
                    page.wait_for_timeout(500)
            except Exception as e:
                print(f"Lỗi khi chọn thông số video: {e}")
                pass # Bỏ qua nếu lỗi, web có thể dùng mặc định

            # ĐỀ PHÒNG WEB TỰ VĂNG (LOGOUT)
            if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Google'))"):
                raise Exception("higgsfield_logout")

            # ── BƯỚC 8: Upload ảnh (ấn nút "+") ─────────────────────────────
            images_to_upload = []
            if img1_path and Path(img1_path).exists():
                images_to_upload.append(img1_path)
            if img2_path and Path(img2_path).exists():
                images_to_upload.append(img2_path)

            if images_to_upload:
                video_tasks[task_id] = {"status": "running", "message": f"Đang tải {len(images_to_upload)} ảnh lên..."}
                try:
                    # Nút "+" là input[type=file] ẩn, trigger qua file chooser
                    with page.expect_file_chooser(timeout=8000) as fc_info:
                        # Click nút "+" (button đầu tiên trong input boundary)
                        page.locator("div[data-guidance-input-boundary='true'] button").first.click()
                    fc_info.value.set_files(images_to_upload)
                    page.wait_for_timeout(2000)
                    video_tasks[task_id] = {"status": "running", "message": f"✅ Đã tải lên {len(images_to_upload)} ảnh!"}
                except:
                    try:
                        # Fallback: set trực tiếp vào input file
                        file_input = page.locator("input[type='file']").first
                        file_input.set_input_files(images_to_upload)
                        page.wait_for_timeout(2000)
                        video_tasks[task_id] = {"status": "running", "message": f"✅ Đã tải lên {len(images_to_upload)} ảnh (fallback)!"}
                    except Exception as e:
                        video_tasks[task_id] = {"status": "running", "message": f"Cảnh báo: Không tải được ảnh - {e}"}

            # ĐỀ PHÒNG WEB TỰ VĂNG (LOGOUT)
            if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Google'))"):
                raise Exception("Tài khoản higgsfield bị văng (Logout) giữa chừng. Vui lòng tắt và CHẠY LẠI profile này!")
                
            check_age_popup(page)

            # ── BƯỚC 9: Nhập prompt vào ô chat ──────────────────────────────
            video_tasks[task_id] = {"status": "running", "message": "Đang nhập prompt..."}
            try:
                editor = page.locator("div[contenteditable='true']").first
                editor.click(timeout=5000)
                page.wait_for_timeout(300)
                
                # Dùng execCommand để PASTE nguyên cục text có xuống dòng, tránh gõ từng chữ (Enter bị hiểu là "Gửi")
                page.evaluate("""([el, txt]) => {
                    el.focus();
                    // Lệnh insertText hoạt động y hệt như ấn Ctrl+V, sẽ dán nguyên khối văn bản
                    if (!document.execCommand('insertText', false, txt)) {
                        // Fallback nếu trình duyệt chặn
                        el.innerText = txt;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                    }
                }""", [editor.element_handle(), prompt])
                
                page.wait_for_timeout(500)
            except Exception as e:
                print(f"Lỗi nhập prompt: {e}")

            # ── BƯỚC 10: Ấn nút Gửi (send button) ──────────────────────────
            video_tasks[task_id] = {"status": "running", "message": "Đang gửi yêu cầu tạo video..."}
            try:
                # Nút gửi có id "flow-end-msg-send"
                send_btn = page.locator("#flow-end-msg-send")
                # Đợi nút không bị disabled (sau khi nhập prompt)
                for _ in range(10):
                    if video_tasks.get(task_id, {}).get("force_stop"):
                        raise Exception("force_stop")
                    is_disabled = send_btn.is_disabled()
                    if not is_disabled:
                        break
                    page.wait_for_timeout(500)
                    
                if video_tasks.get(task_id, {}).get("force_stop"):
                    raise Exception("force_stop")
                    
                send_btn.click(timeout=8000)
                page.wait_for_timeout(1000)
            except Exception as e:
                if str(e) == "force_stop":
                    # Nhảy thẳng xuống cuối (BƯỚC 12)
                    video_tasks[task_id]["status"] = "done"
                else:
                    try:
                        page.evaluate("""() => {
                            const btn = document.getElementById('flow-end-msg-send');
                            if (btn && !btn.disabled) btn.click();
                        }""")
                        page.wait_for_timeout(1000)
                    except:
                        # Fallback: ấn Enter
                        try:
                            page.locator("div[contenteditable='true']").first.press("Enter")
                            page.wait_for_timeout(1000)
                        except:
                            pass

            video_tasks[task_id] = {"status": "running", "message": "✅ Đã gửi yêu cầu! Đang chờ higgsfield.ai tạo video..."}

            # ── BƯỚC 11: Đợi video xuất hiện (tối đa 10 phút) ───────────────
            video_url = None
            video_urls = []
            for i in range(600):
                page.wait_for_timeout(1000)
                
                # Cập nhật log chat
                sync_chat(page)
                
                # CHÚ Ý: Đề phòng web tự văng acc giữa chừng (như lúc đang chờ video)
                if "from_logout=1" in page.url:
                    raise Exception("higgsfield_logout")
                    
                check_age_popup(page)
                    
                if video_tasks.get(task_id, {}).get("force_stop"):
                    print(f"--- Task {task_id} bị force_stop. Thoát vòng lặp chờ video.")
                    break
                
                try:
                    # Quét xem có popup Log In bất ngờ hiện lên không
                    new_urls = page.evaluate("""() => {
                        const extracted = Array.from(document.querySelectorAll('.studio-relay-extracted-video'));
                        const urls = extracted.map(el => el.getAttribute('data-url')).filter(Boolean);
                        
                        const videos = Array.from(document.querySelectorAll('video'));
                        for (let v of videos) {
                            if (v.src && (v.src.startsWith('http') || v.src.startsWith('blob'))) urls.push(v.src);
                            else {
                                const s = v.querySelector('source');
                                if (s && s.src && (s.src.startsWith('http') || s.src.startsWith('blob'))) urls.push(s.src);
                            }
                        }
                        return [...new Set(urls)];
                    }""")
                    has_login_modal = page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        return btns.some(b => b.innerText && b.innerText.includes('Continue with Google'));
                    }""")
                    if has_login_modal:
                        raise Exception("higgsfield_logout")
                except Exception as eval_e:
                    if "higgsfield_logout" in str(eval_e):
                        raise
                
                try:
                    # Cuộn xuống cuối và Hover để ép higgsfield tải thẻ video (Lazy load)
                    page.evaluate("""() => {
                        // 1. Cuộn màn hình xuống cuối cùng
                        const scrollers = document.querySelectorAll('.v_list_row, .container-enLQFx, .block-video-MzfWVN, [data-message-id]');
                        if (scrollers.length > 0) {
                            scrollers[scrollers.length - 1].scrollIntoView({behavior: 'smooth', block: 'end'});
                        }
                        
                        // 2. Hover vào tất cả các vùng có khả năng chứa video
                        const targets = document.querySelectorAll('.v_list_row, .block-video-MzfWVN, .image-box-grid-EYaIcP, .video-player-wrapper-IZ7Zoq, .xgplayer');
                        targets.forEach(t => {
                            try { t.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})); } catch(e){}
                        });
                        
                        // 3. Click thẳng vào nút Play hoặc ảnh đại diện để ÉP nó tải luồng video (Bắt buộc phải Play mới lấy được link)
                        const playBtns = document.querySelectorAll('.play-icon-gWzeeV, .xg-icon-play, [aria-label="play"], .video-hover-button-group-container-mh06XY, .image-box-grid-EYaIcP img');
                        playBtns.forEach(b => {
                            try { 
                                b.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})); 
                                b.click(); // Phải CLICK thì xgplayer mới bơm link vào thẻ <video>
                            } catch(e){}
                        });
                    }""")
                    page.wait_for_timeout(1000) # Chờ 1 giây để nó nạp link sau khi click
                except:
                    pass

                try:
                    new_url = page.evaluate("""() => {
                        const extracted = Array.from(document.querySelectorAll('.studio-relay-extracted-video'));
                        const urls = extracted.map(el => el.getAttribute('data-url')).filter(Boolean);
                        const videos = Array.from(document.querySelectorAll('video'));
                        for (let v of videos) { if (v.src && (v.src.startsWith('http') || v.src.startsWith('blob'))) urls.push(v.src); else { const s = v.querySelector('source'); if (s && s.src && (s.src.startsWith('http') || s.src.startsWith('blob'))) urls.push(s.src); } }
                        return [...new Set(urls)];
                    }""")
                    if new_url and len(new_url) > 0:
                        video_urls = new_url
                        video_url = new_url[0]
                        break
                except:
                    pass

                mins = i // 60
                secs = i % 60
                video_tasks[task_id]["message"] = f"Đang chờ higgsfield.ai tạo video... {mins:02d}:{secs:02d}"

            if video_urls:
                out_dir = Path(save_path)
                out_dir.mkdir(parents=True, exist_ok=True)
                all_result_urls = []
                try:
                    for v_idx, v_url in enumerate(video_urls):
                        video_url = v_url
                        out_file = out_dir / (f"{task_id}.mp4" if len(video_urls) == 1 else f"{task_id}_{v_idx+1}.mp4")
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
                            # DỰ PHÒNG 3 LỚP ĐỂ TẢI VIDEO THÀNH CÔNG 100%
                            success = False
                            err_msg = ""
                            
                            # Lớp 1: Tải bằng Playwright API (thêm User-Agent và Referer để tránh bị CDN block gây lỗi ETIMEDOUT)
                            try:
                                ua = page.evaluate("navigator.userAgent")
                                resp = context.request.get(video_url, headers={
                                    "User-Agent": ua,
                                    "Referer": "https://higgsfield.ai/",
                                    "Accept": "*/*"
                                }, timeout=60000)
                                if resp.ok:
                                    with open(out_file, "wb") as f:
                                        f.write(resp.body())
                                    success = True
                                else:
                                    err_msg = f"HTTP {resp.status}"
                            except Exception as e:
                                err_msg = str(e)
                                
                            # Lớp 2: Nếu Lớp 1 thất bại (bị block kết nối), tải trực tiếp bằng JS trong lòng Page
                            if not success:
                                try:
                                    b64_data = page.evaluate("""async (url) => {
                                        const response = await fetch(url);
                                        if (!response.ok) throw new Error('Fetch failed');
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
                                    success = True
                                except Exception as e:
                                    err_msg = f"JS Fetch Lỗi: {e}"
                                    
                            # Lớp 3: Phương án cuối cùng, bắn sang tab mới để ép trình duyệt tải
                            if not success:
                                try:
                                    dl_page = context.new_page()
                                    dl_page.goto(video_url, timeout=30000)
                                    dl_page.wait_for_timeout(5000)
                                    # File tải về sẽ rơi vào _on_download event của Playwright, nhưng ta không biết tên file. 
                                    # Cách tốt nhất là báo lỗi để retry nếu 2 lớp trên thất bại.
                                    dl_page.close()
                                    raise Exception(f"Tải video thất bại sau 3 cách. Lỗi gốc: {err_msg}")
                                except Exception as e:
                                    raise e
                                   
                        # Phần này chạy chung cho cả 2 trường hợp tải thành công (blob hoặc http)
                        if tg_enabled:
                            _send_video_to_telegram(str(out_file), tg_token, tg_chat_id)
                        all_urls = [f"/api/video/download/{task_id}?path={urllib.parse.quote(str(out_file))}"]
                        all_result_urls.extend(all_urls)
                    video_tasks[task_id]["result_urls"] = all_result_urls
                    video_tasks[task_id]["message"] = f"🎉 {len(video_urls)} Video tạo xong! Đang hiển thị lên Tool..."
                    page.wait_for_timeout(3000)
                except Exception as e:
                    video_tasks[task_id] = {"status": "error", "message": f"Tạo thành công nhưng tải video thất bại: {e}"}
            else:
                if video_tasks.get(task_id, {}).get("force_stop"):
                    video_tasks[task_id]["message"] = "Đã hủy tiến trình!"
                    # Không set status = done ở đây, để UI tiếp tục cập nhật tiến trình xóa acc
                else:
                    video_tasks[task_id] = {"status": "error", "message": "Timeout 10 phút: Video không xuất hiện trên higgsfield.ai."}

            # ── BƯỚC 12: Xóa tài khoản (Delete Account) ─────────
            video_tasks[task_id]["message"] = video_tasks[task_id].get("message", "") + "\nĐang hủy hoạt động và Xóa tài khoản..."
            
            # Thoát khỏi chế độ xem video (Modal/Fullscreen) do lúc nãy ta đã click Play
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                page.keyboard.press("Escape")
                # Click chuột ra một góc trống để đảm bảo các menu/modal đang mở sẽ bị đóng
                page.mouse.click(10, 10)
                page.wait_for_timeout(1000)
            except: pass
            
            try:
                # Nếu bị force stop, tải lại trang để HỦY NGAY LẬP TỨC các file đang upload
                if video_tasks.get(task_id, {}).get("force_stop"):
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    
                # 1. Bấm Avatar (Sử dụng locator chính xác theo DOM của higgsfield)
                page.locator("button[aria-haspopup='menu']").filter(has=page.locator("img.rounded-full")).click(timeout=8000)
                
                def click_by_coords(texts, selector='button, p, div, span, a', retries=10):
                    import json, random
                    for _ in range(retries):
                        box = page.evaluate(f"""() => {{
                            const texts = {json.dumps(texts)};
                            const allBtns = Array.from(document.querySelectorAll('{selector}'));
                            const btn = allBtns.reverse().find(b => {{
                                if (!b.innerText) return false;
                                const rect = b.getBoundingClientRect();
                                if (rect.width === 0 || rect.height === 0) return false;
                                const style = window.getComputedStyle(b);
                                if (style.opacity === '0' || style.visibility === 'hidden' || style.display === 'none') return false;
                                const text = b.innerText.trim();
                                return texts.includes(text) || texts.some(t => text === t + ' >' || text === t + ' ❯' || text === t + ' 〉') || texts.some(t => text.includes(t) && text.length <= t.length + 5);
                            }});
                            
                            let clickable = btn;
                            while(clickable && clickable !== document.body) {{
                                const style = window.getComputedStyle(clickable);
                                if (style.cursor === 'pointer' || clickable.tagName === 'BUTTON' || clickable.tagName === 'A') {{
                                    break;
                                }}
                                clickable = clickable.parentElement;
                            }}
                            if (!clickable || clickable === document.body) clickable = btn;
                            
                            if (clickable.scrollIntoView) {{
                                clickable.scrollIntoView({{block: 'center', inline: 'center'}});
                            }}
                            const rect = clickable.getBoundingClientRect();
                            return {{
                                x: rect.x + rect.width / 2,
                                y: rect.y + rect.height / 2
                            }};
                        }}""")
                        if box:
                            tx = box['x'] + random.uniform(-2, 2)
                            ty = box['y'] + random.uniform(-2, 2)
                            page.mouse.move(tx, ty)
                            page.wait_for_timeout(100)
                            # Thực hiện click bằng hàm click chuẩn
                            page.mouse.click(tx, ty)
                            return True
                        page.wait_for_timeout(1000) # Đợi lâu hơn xíu giữa các lần thử
                    return False

                # 2. Bấm Settings / Cài đặt
                page.wait_for_timeout(2000)
                if not click_by_coords(['Settings', 'Cài đặt']): raise Exception("Không tìm thấy nút Settings / Cài đặt")
                
                # 3. Bấm Account / Tài khoản
                page.wait_for_timeout(2000)
                if not click_by_coords(['Account', 'Tài khoản']): raise Exception("Không tìm thấy nút Account / Tài khoản")
                
                # 4. Bấm Delete Account / Xóa tài khoản
                page.wait_for_timeout(2000)
                if not click_by_coords(['Delete Account', 'Xóa tài khoản']): raise Exception("Không tìm thấy nút Delete Account / Xóa tài khoản")
                
                # 5. Bấm Delete / Xóa
                page.wait_for_timeout(2000)
                if not click_by_coords(['Delete', 'Xóa'], 'button'): raise Exception("Không tìm thấy nút Delete / Xóa (Lần 1)")
                
                # 5.5. Bấm Xóa trong modal xác nhận nhỏ (Hủy / Xóa)
                page.wait_for_timeout(2000)
                print("[XoaNgay] Đang bấm nút Xóa màu đỏ trong modal xác nhận...")
                try:
                    clicked_modal = page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        // Tìm các nút có chữ Xóa hoặc Delete chính xác
                        const deleteBtns = btns.filter(b => b.innerText.trim() === 'Xóa' || b.innerText.trim() === 'Delete');
                        if (deleteBtns.length > 0) {
                            // Click nút cuối cùng (thường là nút trong modal vừa hiện ra)
                            deleteBtns[deleteBtns.length - 1].click();
                            return true;
                        }
                        return false;
                    }""")
                    if clicked_modal:
                        print("[XoaNgay] Đã click nút Xóa trong modal thành công!")
                    else:
                        print("[XoaNgay] Không tìm thấy nút Xóa trong modal bằng JS, thử Playwright...")
                        page.locator('button:has-text("Xóa"), button:has-text("Delete")').last.click(timeout=2000, force=True)
                except Exception as e:
                    print(f"[XoaNgay] Lỗi click nút Xóa trong modal: {e}")
                
                # 5.6. Bấm Xác nhận (nếu có popup Xác nhận tuổi)
                page.wait_for_timeout(2000)
                try:
                    clicked_confirm = page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        const confirmBtns = btns.filter(b => b.innerText.trim() === 'Xác nhận' || b.innerText.trim() === 'Confirm');
                        if (confirmBtns.length > 0) {
                            confirmBtns[confirmBtns.length - 1].click();
                            return true;
                        }
                        return false;
                    }""")
                    if clicked_confirm:
                        print("[XoaNgay] Đã click nút Xác nhận tuổi!")
                except Exception as e:
                    pass
                
                # 6. Bấm Xóa ngay - Dùng kịch bản ElementFromPoint siêu việt của User
                print("[XoaNgay] Đang bắt đầu bấm Xóa ngay bằng kịch bản ElementFromPoint...")
                
                success = False
                for attempt in range(6):
                    page.wait_for_timeout(2000)
                    frames_list = page.frames
                    print(f"[XoaNgay] Attempt {attempt+1}: Bơm mã JS vào tất cả {len(frames_list)} frames (như Extension)...")
                    
                    js_code = """
                        async () => {
                          const logo = document.querySelector("img.icon-ieQdCp");
                          if (!logo) return "KhongThayLogo";

                          // Vị trí: dưới logo 30px
                          const r = logo.getBoundingClientRect();
                          const size = 50;
                          const x = r.left + (r.width - size) / 2;
                          const y = r.bottom + 30;

                          // Tạo highlight
                          document.getElementById("test-square-highlight")?.remove();

                          const square = document.createElement("div");
                          square.id = "test-square-highlight";

                          Object.assign(square.style, {
                            position: "fixed",
                            left: `${x}px`,
                            top: `${y}px`,
                            width: `${size}px`,
                            height: `${size}px`,
                            boxSizing: "border-box",
                            border: "4px solid #ff0033",
                            borderRadius: "4px",
                            background: "rgba(255, 0, 51, .18)",
                            boxShadow: "0 0 18px 7px rgba(255, 0, 51, .75)",
                            zIndex: "2147483647",
                            pointerEvents: "none"
                          });

                          document.body.appendChild(square);
                          console.log("Đã highlight. Sẽ click sau 1.5 giây.");

                          await new Promise(resolve => setTimeout(resolve, 1500));

                          // Ẩn overlay để lấy chính phần tử phía dưới tâm ô
                          square.style.display = "none";
                          const target = document.elementFromPoint(x + size / 2, y + size / 2);
                          square.remove();

                          if (!target) return "KhongCoPhanTu";

                          const clickable = target.closest(
                            ".confirm-button-ZuDQ59, [role='button'], button, a, [onclick]"
                          ) || target;

                          console.log("Đang click phần tử:", clickable);
                          clickable.click();
                          
                          return "DaClick";
                        }
                    """
                    
                    clicked_this_round = False
                    for f in frames_list:
                        try:
                            result = f.evaluate(js_code)
                            if result == "DaClick":
                                print(f"     -> [Tuyệt vời] Đã vẽ highlight và CLICK TRÚNG ĐÍCH trong frame: {f.name or f.url}")
                                clicked_this_round = True
                                break
                        except Exception:
                            # Frame có thể bị huỷ hoặc lỗi kết nối, bỏ qua
                            pass
                            
                    if clicked_this_round:
                        page.wait_for_timeout(3000)
                        # Kiểm tra xem logo có biến mất khỏi tất cả frames chưa
                        still_there = False
                        for f in page.frames:
                            try:
                                has_logo = f.evaluate('() => !!document.querySelector("img.icon-ieQdCp")')
                                if has_logo:
                                    still_there = True
                                    break
                            except: pass
                            
                        if not still_there:
                            success = True
                            print("[XoaNgay] Xác nhận cửa sổ Xóa ngay đã đóng -> THÀNH CÔNG!")
                            break
                        else:
                            print("[XoaNgay] Vẫn còn thấy Logo, click chưa ăn hoặc mạng lag...")
                
                if not success:
                    print("[XoaNgay] Cảnh báo: Vượt quá số lần thử click Xóa ngay!")
                
                page.wait_for_timeout(2000)


                
                # Đợi web load và kiểm tra trạng thái Đăng xuất (chứng tỏ đã xóa thành công)
                try:
                    page.wait_for_timeout(3000)
                    # Kiểm tra xem có xuất hiện nút "Đăng nhập" (Login) hoặc có chuyển hướng URL from_logout không
                    page.evaluate("""() => {
                        const all = document.body.innerText;
                        const hasLoginBtn = all.includes('Đăng nhập') || all.includes('Log in') || all.includes('Sign in');
                        const isLoggedOutUrl = window.location.href.includes('from_logout');
                        
                        if (!hasLoginBtn && !isLoggedOutUrl && !all.includes('Account deleted') && !all.includes('đã xóa') && !all.includes('deleted')) {
                            throw new Error('Chưa thấy dấu hiệu đăng xuất/xóa tài khoản');
                        }
                    }""")
                    page.wait_for_timeout(1000) # Thêm 1 giây cho chắc cú sau khi thông báo hiện
                except Exception as e:
                    print(f"Chưa thấy dấu hiệu xóa thành công, đợi thêm 5s: {e}")
                    page.wait_for_timeout(5000)
                    # Lần 2 bắt buộc phải có, nếu không có quăng lỗi để ra catch
                    page.evaluate("""() => {
                        const all = document.body.innerText;
                        const hasLoginBtn = all.includes('Đăng nhập') || all.includes('Log in') || all.includes('Sign in');
                        const isLoggedOutUrl = window.location.href.includes('from_logout');
                        
                        if (!hasLoginBtn && !isLoggedOutUrl && !all.includes('Account deleted') && !all.includes('đã xóa') && !all.includes('deleted')) {
                            throw new Error('Timeout: Không thấy thông báo hoặc dấu hiệu xóa thành công (chưa thấy nút Đăng nhập)!');
                        }
                    }""")
                video_tasks[task_id]["message"] = video_tasks[task_id]["message"].replace("Đang hủy hoạt động và Xóa tài khoản...", "Đã xóa Account thành công!")
            except Exception as del_err:
                print(f"Lỗi khi xóa account: {del_err}")
                video_tasks[task_id]["message"] = video_tasks[task_id]["message"].replace("Đang hủy hoạt động và Xóa tài khoản...", "Gặp lỗi khi xóa Account!")
                
            # Đánh dấu done ở bước cuối cùng
            video_tasks[task_id]["status"] = "done"

            try: context.close()
            except: pass

    except Exception as e:
        # Bắt buộc đóng trình duyệt ngay lập tức nếu có lỗi hoặc văng để retry có thể lấy FP mới
        try: context.close()
        except: pass
        
        if "higgsfield_logout" in str(e):
            print(f"--- Bị văng! Báo cho frontend tự động thử lại task {task_id}...")
            video_tasks[task_id] = {
                "status": "higgsfield_logout", 
                "message": "Bị văng khỏi tài khoản, đang tự động thử lại bằng vân tay (Fingerprint) Chrome hoàn toàn mới..."
            }
            return
        video_tasks[task_id] = {"status": "error", "message": f"Lỗi hệ thống: {e}"}

    finally:
        # Tự động xóa ảnh upload sau khi task xong để tiết kiệm dung lượng
        # Nếu đang báo frontend retry thì KHÔNG xóa ảnh
        if video_tasks.get(task_id, {}).get("status") != "higgsfield_logout":
            for img_path in [img1_path, img2_path]:
                if img_path:
                    try:
                        p = Path(img_path)
                        if p.exists():
                            p.unlink()
                    except: pass





@app.post("/api/video/create")
async def create_video(
    prompt: str = Form(...),
    profile_id: str = Form(""),
    img1: UploadFile = File(None),
    img2: UploadFile = File(None),
    save_path: str = Form(None),
    is_headless: str = Form("false"),
    enable_ext: str = Form("false"),
    enable_ext_btn2: str = Form("false"),
    telegram_enabled: str = Form("false"),
    telegram_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    video_model: str = Form("Dreamina Seedance 2.0 Fast"),
    video_duration: str = Form("10s"),
    video_ratio: str = Form("9:16")
):
    # Lấy danh sách các profile đang bận
    used_profiles = set()
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            used_profiles.add(task.get("params", {}).get("profile_id"))
    for p in list_running():
        used_profiles.add(p["id"])

    if not profile_id:
        # Tự động gán profile rảnh
        all_profiles = manager.list_profiles()
        free_profiles = [p for p in all_profiles if p.id not in used_profiles]
        if not free_profiles:
            return JSONResponse(status_code=400, content={"message": "Không còn Profile nào trống. Vui lòng tạo thêm Profile hoặc chờ!"})
        profile_id = free_profiles[0].id
    else:
        # Kiểm tra xem profile được chọn có đang bận không
        if profile_id in used_profiles:
            return JSONResponse(status_code=400, content={"message": "Profile này đang bận (đang mở hoặc đang tạo video khác). Vui lòng chọn profile khác!"})

    headless_bool = (is_headless.lower() == "true")
    task_id = uuid_module.uuid4().hex[:10]
    
    # Save uploaded images
    upload_dir = Path(BASE_DIR) / "data" / "uploads"
    upload_dir.mkdir(exist_ok=True)
    
    img1_path = ""
    if img1 and img1.filename:
        img1_path = str(upload_dir / f"{task_id}_img1{Path(img1.filename).suffix}")
        with open(img1_path, "wb") as f:
            f.write(await img1.read())
    
    img2_path = ""
    if img2 and img2.filename:
        img2_path = str(upload_dir / f"{task_id}_img2{Path(img2.filename).suffix}")
        with open(img2_path, "wb") as f:
            f.write(await img2.read())

    video_tasks[task_id] = {
        "status": "pending", 
        "message": "Đang chuẩn bị...",
        "params": {
            "prompt": prompt,
            "img1_path": img1_path,
            "img2_path": img2_path,
            "profile_id": profile_id,
            "save_path": save_path,
            "is_headless": headless_bool,
            "enable_ext": (enable_ext.lower() == "true"),
            "enable_ext_btn2": (enable_ext_btn2.lower() == "true"),
            "tg_enabled": (telegram_enabled.lower() == "true"),
            "tg_token": telegram_token,
            "tg_chat_id": telegram_chat_id,
            "video_model": video_model,
            "video_duration": video_duration,
            "video_ratio": video_ratio
        }
    }
    
    t = threading.Thread(target=run_video_automation, args=(task_id, prompt, img1_path, img2_path, profile_id, save_path, headless_bool, (enable_ext.lower() == "true"), (enable_ext_btn2.lower() == "true"), (telegram_enabled.lower() == "true"), telegram_token, telegram_chat_id, video_model, video_duration, video_ratio), daemon=True)
    t.start()
    
    return {"ok": True, "task_id": task_id, "profile_id": profile_id}

@app.post("/api/video/retry/{task_id}")
def retry_video(task_id: str):
    task = video_tasks.get(task_id)
    if not task or "params" not in task:
        from fastapi import HTTPException
        raise HTTPException(404, "Task not found")
    
    p = task["params"]
    video_tasks[task_id]["status"] = "pending"
    video_tasks[task_id]["message"] = "Đang thử lại..."
    video_tasks[task_id].pop("force_stop", None) # Xóa cờ force_stop nếu có
    t = threading.Thread(target=run_video_automation, args=(task_id, p["prompt"], p["img1_path"], p["img2_path"], p["profile_id"], p.get("save_path"), p.get("is_headless", False), p.get("enable_ext", False), p.get("enable_ext_btn2", False), p.get("tg_enabled", False), p.get("tg_token", ""), p.get("tg_chat_id", ""), p.get("video_model", "Dreamina Seedance 2.0 Fast"), p.get("video_duration", "10s"), p.get("video_ratio", "9:16")), daemon=True)
    t.start()
    return {"ok": True}

@app.post("/api/video/stop/{task_id}")
def stop_video(task_id: str):
    if task_id in video_tasks:
        video_tasks[task_id]["force_stop"] = True
    return {"ok": True}

@app.get("/api/video/status/{task_id}")
def video_status(task_id: str):
    return video_tasks.get(task_id, {"status": "not_found"})

from fastapi import Request

@app.get("/api/video/download/{task_id}")
def download_video(task_id: str, request: Request):
    path = request.query_params.get("path")
    if path:
        video_path = Path(path)
    else:
        video_path = Path(BASE_DIR) / "data" / "videos" / f"{task_id}.mp4"
        
    if not video_path.exists():
        raise HTTPException(404, "Video not found")
    from fastapi.responses import FileResponse as FR
    return FR(str(video_path), media_type="video/mp4", filename=video_path.name)

@app.get("/api/debug/screenshot/{task_id}")
def get_debug_screenshot(task_id: str):
    """Trả về ảnh debug screenshot nút Xóa ngay đã highlight"""
    from fastapi.responses import FileResponse as FR
    task = video_tasks.get(task_id, {})
    ss_path = task.get("debug_screenshot")
    if ss_path and Path(ss_path).exists():
        return FR(ss_path, media_type="image/png")
    # Tìm file debug tự động
    ss_file = Path(BASE_DIR) / "data" / "debug_screenshots" / f"xoa_ngay_{task_id}.png"
    if ss_file.exists():
        return FR(str(ss_file), media_type="image/png")
    raise HTTPException(404, "Screenshot chưa sẵn sàng hoặc chưa được chụp")

from pydantic import BaseModel

class DeleteAccountDirectReq(BaseModel):
    profile_id: str

def run_delete_account_automation(task_id: str, profile_id: str):
    from playwright.sync_api import sync_playwright
    import time
    from pathlib import Path
    import json
    import random
    
    ext_path = str((Path(BASE_DIR) / "data" / "extensions" / "fingerprint_spoofer").absolute())
    profile = manager.get_profile(profile_id)
    if not profile:
        video_tasks[task_id] = {"status": "error", "message": "Profile not found"}
        return
        
    video_tasks[task_id] = {"status": "running", "message": "Đang mở trình duyệt..."}
    try:
        with pw_lock:
            p = sync_playwright().start()
        if True:
            browser = None
            context = None
            
            # Ưu tiên kết nối qua CDP nếu profile đang được mở (Nút 'Mở Chrome' đã được bấm)
            port_file = Path(profile.user_data_dir) / "cdp_port.txt"
            if port_file.exists():
                try:
                    port = int(port_file.read_text().strip())
                    browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
                    context = browser.contexts[0]
                except:
                    pass
            
            # Nếu không thể connect CDP thì mở trình duyệt mới
            if not context:
                context = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=False, is_headless=False)
            
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
                    
            # Playwright khi connect CDP thường tạo ra tab 'about:blank' rác -> đóng nó lại
            for pg in context.pages:
                if pg != page:
                    try: pg.close()
                    except: pass
            
            try: page.bring_to_front()
            except: pass
                
            page.goto("https://higgsfield.ai/chat", timeout=60000)
            page.wait_for_timeout(3000)
            
            # Kiểm tra đăng nhập
            avatar_btn = page.locator("button[aria-haspopup='menu']").filter(has=page.locator("img.rounded-full"))
            if not avatar_btn.count():
                video_tasks[task_id] = {"status": "error", "message": "Bạn chưa đăng nhập higgsfield trên Profile này! Vui lòng Mở Chrome và đăng nhập trước."}
                try: context.close()
                except: pass
                return
                
            video_tasks[task_id]["message"] = "Đang tiến hành Xóa tài khoản..."
            
            # 1. Bấm Avatar
            avatar_btn.first.click(timeout=8000)
            
            def click_by_coords(texts, selector='button, p, div, span, a', retries=10):
                import json, random
                for _ in range(retries):
                    box = page.evaluate(f"""() => {{
                        const texts = {json.dumps(texts)};
                        const allBtns = Array.from(document.querySelectorAll('{selector}'));
                        const btn = allBtns.reverse().find(b => {{
                            if (!b.innerText) return false;
                            const rect = b.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) return false;
                            const style = window.getComputedStyle(b);
                            if (style.opacity === '0' || style.visibility === 'hidden' || style.display === 'none') return false;
                            const text = b.innerText.trim();
                            return texts.includes(text) || texts.some(t => text === t + ' >' || text === t + ' ❯' || text === t + ' 〉') || texts.some(t => text.includes(t) && text.length <= t.length + 5);
                        }});
                        
                        let clickable = btn;
                        while(clickable && clickable !== document.body) {{
                            const style = window.getComputedStyle(clickable);
                            if (style.cursor === 'pointer' || clickable.tagName === 'BUTTON' || clickable.tagName === 'A') {{
                                break;
                            }}
                            clickable = clickable.parentElement;
                        }}
                        if (!clickable || clickable === document.body) clickable = btn;
                        
                        if (clickable.scrollIntoView) {{
                            clickable.scrollIntoView({{block: 'center', inline: 'center'}});
                        }}
                        const rect = clickable.getBoundingClientRect();
                        return {{
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2
                        }};
                    }}""")
                    if box:
                        tx = box['x'] + random.uniform(-2, 2)
                        ty = box['y'] + random.uniform(-2, 2)
                        page.mouse.move(tx, ty)
                        page.wait_for_timeout(100)
                        # Thực hiện click bằng hàm click chuẩn
                        page.mouse.click(tx, ty)
                        return True
                    page.wait_for_timeout(1000) # Đợi lâu hơn xíu giữa các lần thử
                return False

            def click_by_exact_selector(sel, retries=10):
                import random
                for _ in range(retries):
                    box = page.evaluate(f"""() => {{
                        const btn = document.querySelector('{sel}');
                        if (btn.scrollIntoView) {{
                            btn.scrollIntoView({{block: 'center', inline: 'center'}});
                        }}
                        const rect = btn.getBoundingClientRect();
                        return {{
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2
                        }};
                    }}""")
                    if box:
                        tx = box['x'] + random.uniform(-2, 2)
                        ty = box['y'] + random.uniform(-2, 2)
                        page.mouse.move(tx, ty)
                        page.wait_for_timeout(100)
                        page.mouse.click(tx, ty)
                        return True
                    page.wait_for_timeout(1000)
                return False

            # 2. Bấm Settings / Cài đặt
            page.wait_for_timeout(2000)
            if not click_by_coords(['Settings', 'Cài đặt']): raise Exception("Không tìm thấy nút Settings / Cài đặt")
            
            # 3. Bấm Account / Tài khoản
            page.wait_for_timeout(2000)
            if not click_by_coords(['Account', 'Tài khoản']): raise Exception("Không tìm thấy nút Account / Tài khoản")
            
            # 4. Bấm Delete Account / Xóa tài khoản
            page.wait_for_timeout(2000)
            if not click_by_coords(['Delete Account', 'Xóa tài khoản']): raise Exception("Không tìm thấy nút Delete Account / Xóa tài khoản")
            
            # 5. Bấm Delete / Xóa
            page.wait_for_timeout(2000)
            if not click_by_coords(['Delete', 'Xóa'], 'button'): raise Exception("Không tìm thấy nút Delete / Xóa")
            
            # 5.5. Bấm Xóa trong modal xác nhận nhỏ (Hủy / Xóa)
            page.wait_for_timeout(2000)
            print("[XoaNgay] Đang bấm nút Xóa màu đỏ trong modal xác nhận...")
            try:
                clicked_modal = page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    // Tìm các nút có chữ Xóa hoặc Delete chính xác
                    const deleteBtns = btns.filter(b => b.innerText.trim() === 'Xóa' || b.innerText.trim() === 'Delete');
                    if (deleteBtns.length > 0) {
                        // Click nút cuối cùng (thường là nút trong modal vừa hiện ra)
                        deleteBtns[deleteBtns.length - 1].click();
                        return true;
                    }
                    return false;
                }""")
                if clicked_modal:
                    print("[XoaNgay] Đã click nút Xóa trong modal thành công!")
                else:
                    print("[XoaNgay] Không tìm thấy nút Xóa trong modal bằng JS, thử Playwright...")
                    page.locator('button:has-text("Xóa"), button:has-text("Delete")').last.click(timeout=2000, force=True)
            except Exception as e:
                print(f"[XoaNgay] Lỗi click nút Xóa trong modal: {e}")
            
            # 5.6. Bấm Xác nhận (nếu có popup Xác nhận tuổi)
            page.wait_for_timeout(2000)
            try:
                clicked_confirm = page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const confirmBtns = btns.filter(b => b.innerText.trim() === 'Xác nhận' || b.innerText.trim() === 'Confirm');
                    if (confirmBtns.length > 0) {
                        confirmBtns[confirmBtns.length - 1].click();
                        return true;
                    }
                    return false;
                }""")
                if clicked_confirm:
                    print("[XoaNgay] Đã click nút Xác nhận tuổi!")
            except Exception as e:
                pass
            
            # 6. Bấm Xóa ngay - Dùng kịch bản ElementFromPoint siêu việt của User
            print("[XoaNgay] Đang bắt đầu bấm Xóa ngay bằng kịch bản ElementFromPoint...")
            
            success = False
            for attempt in range(6):
                page.wait_for_timeout(2000)
                frames_list = page.frames
                print(f"[XoaNgay] Attempt {attempt+1}: Bơm mã JS vào tất cả {len(frames_list)} frames (như Extension)...")
                
                js_code = """
                    async () => {
                      const logo = document.querySelector("img.icon-ieQdCp");
                      if (!logo) return "KhongThayLogo";

                      // Vị trí: dưới logo 30px
                      const r = logo.getBoundingClientRect();
                      const size = 50;
                      const x = r.left + (r.width - size) / 2;
                      const y = r.bottom + 30;

                      // Tạo highlight
                      document.getElementById("test-square-highlight")?.remove();

                      const square = document.createElement("div");
                      square.id = "test-square-highlight";

                      Object.assign(square.style, {
                        position: "fixed",
                        left: `${x}px`,
                        top: `${y}px`,
                        width: `${size}px`,
                        height: `${size}px`,
                        boxSizing: "border-box",
                        border: "4px solid #ff0033",
                        borderRadius: "4px",
                        background: "rgba(255, 0, 51, .18)",
                        boxShadow: "0 0 18px 7px rgba(255, 0, 51, .75)",
                        zIndex: "2147483647",
                        pointerEvents: "none"
                      });

                      document.body.appendChild(square);
                      console.log("Đã highlight. Sẽ click sau 1.5 giây.");

                      await new Promise(resolve => setTimeout(resolve, 1500));

                      // Ẩn overlay để lấy chính phần tử phía dưới tâm ô
                      square.style.display = "none";
                      const target = document.elementFromPoint(x + size / 2, y + size / 2);
                      square.remove();

                      if (!target) return "KhongCoPhanTu";

                      const clickable = target.closest(
                        ".confirm-button-ZuDQ59, [role='button'], button, a, [onclick]"
                      ) || target;

                      console.log("Đang click phần tử:", clickable);
                      clickable.click();
                      
                      return "DaClick";
                    }
                """
                
                clicked_this_round = False
                for f in frames_list:
                    try:
                        result = f.evaluate(js_code)
                        if result == "DaClick":
                            print(f"     -> [Tuyệt vời] Đã vẽ highlight và CLICK TRÚNG ĐÍCH trong frame: {f.name or f.url}")
                            clicked_this_round = True
                            break
                    except Exception:
                        # Frame có thể bị huỷ hoặc lỗi kết nối, bỏ qua
                        pass
                        
                if clicked_this_round:
                    page.wait_for_timeout(3000)
                    # Kiểm tra xem logo có biến mất khỏi tất cả frames chưa
                    still_there = False
                    for f in page.frames:
                        try:
                            has_logo = f.evaluate('() => !!document.querySelector("img.icon-ieQdCp")')
                            if has_logo:
                                still_there = True
                                break
                        except: pass
                        
                    if not still_there:
                        success = True
                        print("[XoaNgay] Xác nhận cửa sổ Xóa ngay đã đóng -> THÀNH CÔNG!")
                        break
                    else:
                        print("[XoaNgay] Vẫn còn thấy Logo, click chưa ăn hoặc mạng lag...")
            
            if not success:
                print("[XoaNgay] Cảnh báo: Vượt quá số lần thử click Xóa ngay!")
            
            page.wait_for_timeout(2000)
            
            try:
                page.wait_for_timeout(3000)
                page.evaluate("""() => {
                    const all = document.body.innerText;
                    if (!all.includes('Account deleted') && !all.includes('đã xóa') && !all.includes('deleted')) throw new Error('Not deleted yet');
                }""")
                page.wait_for_timeout(1000)
            except Exception as e:
                page.wait_for_timeout(5000)
                page.evaluate("""() => {
                    const all = document.body.innerText;
                    if (!all.includes('Account deleted') && !all.includes('đã xóa') && !all.includes('deleted')) throw new Error('Timeout: Không thấy thông báo xóa thành công!');
                }""")
            
            video_tasks[task_id]["message"] = "Đã xóa Account thành công!"
            video_tasks[task_id]["status"] = "done"
            
            try: context.close()
            except: pass

    except Exception as e:
        try: context.close()
        except: pass
        video_tasks[task_id]["status"] = "error"
        video_tasks[task_id]["message"] = f"Lỗi khi xóa account: {e}"


from app.models import CheckVideoReq
def run_check_video_automation(task_id: str, profile_id: str, is_headless: bool = False):
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

# Lưu các task_id đang check video để có thể dừng hàng loạt
check_video_task_ids = set()

@app.post("/api/video/check")
def api_check_video(req: CheckVideoReq):
    import uuid
    import threading
    task_id = str(uuid.uuid4())
    video_tasks[task_id] = {"status": "pending", "message": "Chuẩn bị kiểm tra video..."}
    check_video_task_ids.add(task_id)
    def _run_and_cleanup(*args):
        try:
            run_check_video_automation(*args)
        finally:
            check_video_task_ids.discard(task_id)
    t = threading.Thread(target=_run_and_cleanup, args=(task_id, req.profile_id, req.is_headless), daemon=True)
    t.start()
    return {"ok": True, "task_id": task_id}

@app.post("/api/video/check/stop_all")
def api_stop_all_check_video():
    """Dừng tất cả tiến trình check video đang chạy"""
    stopped = []
    for tid in list(check_video_task_ids):
        if tid in video_tasks:
            video_tasks[tid]["force_stop"] = True
            stopped.append(tid)
    return {"ok": True, "stopped": stopped}

@app.post("/api/video/delete_account_direct")
def api_delete_account_direct(req: DeleteAccountDirectReq):
    import uuid
    import threading
    task_id = str(uuid.uuid4())
    video_tasks[task_id] = {"status": "pending", "message": "Chuẩn bị xóa account..."}
    t = threading.Thread(target=run_delete_account_automation, args=(task_id, req.profile_id), daemon=True)
    t.start()
    return {"ok": True, "task_id": task_id}

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Antidetect Tool API running. Go to /docs for API docs"}

if __name__ == "__main__":
    # KHỞI CHẠY BACKGROUND WATCHER DOWNLOADS ĐỂ TỰ ĐỘNG ĐỔI ĐUÔI FILE LẠ THÀNH .MP4/.JPG
    def _watch_downloads_folder():
        import time, os
        from pathlib import Path
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        
        def _get_magic_ext(filepath):
            try:
                with open(filepath, 'rb') as f:
                    data = f.read(256)
                if not data or len(data) < 8: return ''
                b = data[:16]
                if data[:256].find(b'ftyp') >= 0: return '.mp4'
                if b[:3] == b'\xff\xd8\xff': return '.jpg'
                if b[:8] == b'\x89PNG\r\n\x1a\n': return '.png'
                if b[:4] == b'RIFF' and b[8:12] == b'WEBP': return '.webp'
                if b[:6] in (b'GIF87a', b'GIF89a'): return '.gif'
                if b[:4] == b'\x1aE\xdf\xa3': return '.webm'
            except: pass
            return ''

        while True:
            try:
                time.sleep(2)
                now = time.time()
                for f in downloads_dir.iterdir():
                    if not f.is_file(): continue
                    ext = f.suffix.lower()
                    # Không can thiệp nếu file đang down hoặc là temp
                    if ext == '.crdownload' or ext == '.tmp': continue
                    # Đã có đuôi hợp lệ thì bỏ qua
                    if ext in ('.mp4','.jpg','.png','.webp','.webm','.gif','.jpeg','.avi','.mov','.mkv'): continue
                    # Chỉ xử lý file tạo/sửa trong 15 phút gần đây
                    try:
                        if now - f.stat().st_mtime > 900: continue
                    except: continue
                    
                    real_ext = _get_magic_ext(f)
                    if real_ext:
                        new_path = f.with_name(f.stem + real_ext)
                        counter = 1
                        while new_path.exists():
                            new_path = f.with_name(f"{f.stem}_{counter}{real_ext}")
                            counter += 1
                        try:
                            f.rename(new_path)
                            print(f"[Watcher] Tự động đổi tên: {f.name} -> {new_path.name}")
                        except PermissionError:
                            pass # File có thể đang được Chrome ghi dở, bỏ qua chờ loop sau
                        except Exception as e:
                            pass
            except Exception as e:
                time.sleep(5)
                
    import threading
    threading.Thread(target=_watch_downloads_folder, daemon=True).start()
    
    import uvicorn
    print("""
╔══════════════════════════════════════════════════╗
║   Antidetect Unlimited V4 - Full Featured      ║
║   ✅ Cookie Import (BitBrowser format)         ║
║   ✅ Random Fingerprint (giữ cookie)           ║
║   ✅ Tabs persistence (đóng mở vẫn còn)        ║
║   ♾️ Unlimited Profiles                        ║
╚══════════════════════════════════════════════════╝

-> http://localhost:5333
    """)
    uvicorn.run("main:app", host="0.0.0.0", port=5333, reload=False)

