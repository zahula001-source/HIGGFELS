"""
Antidetect Unlimited V4 - Hß╗ù trß╗ú Cookie BitBrowser + Random Fingerprint + Tabs persistence
"""
import asyncio
import threading
pw_lock = threading.Lock()
from fastapi import FastAPI, HTTPException, Body, Request
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
        # ─Éß║┐m cookie imported
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
                raise HTTPException(400, f"Profile '{profile.name}' ─æang chß║íy ngß║ºm ─æß╗â tß║ío Video. Vui l├▓ng ─æß╗úi tß║ío xong!")
                
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
    """N├║t Random Fingerprint nh╞░ BitBrowser - ─æß╗òi ngay lß║¡p tß╗⌐c m├á vß║½n giß╗» cookie"""
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    
    was_running = is_running(profile_id)
    if was_running:
        close_profile(profile_id)
        import time
        time.sleep(1.5)
    
    new_p = manager.randomize_fingerprint(profile_id)
    
    # Nß║┐u ─æang chß║íy th├¼ mß╗ƒ lß║íi lu├┤n vß╗¢i fingerprint mß╗¢i (giß╗» nguy├¬n cookies)
    if was_running:
        result = launch_profile_with_fallback(new_p)
        if result["status"] == "launched":
            return {"ok": True, "message": f"─É├ú random fingerprint mß╗¢i ({new_p.os}) v├á mß╗ƒ lß║íi, cookies vß║½n giß╗»!", "profile": new_p.model_dump(), "pid": result["pid"]}
        else:
            return {"ok": True, "message": f"─É├ú random fingerprint mß╗¢i ({new_p.os}) nh╞░ng lß╗ùi mß╗ƒ lß║íi: {result.get('message')}", "profile": new_p.model_dump()}
    
    return {"ok": True, "message": f"─É├ú random fingerprint mß╗¢i: {new_p.os} - {new_p.fingerprint.get('random_id')}", "profile": new_p.model_dump()}

@app.post("/api/profiles/{profile_id}/import-cookies")
def import_cookies(profile_id: str, payload: dict = Body(...)):
    """Import cookies tß╗½ BitBrowser - d├ín JSON v├áo"""
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    
    cookies_raw = payload.get("cookies") or payload.get("cookie")
    if not cookies_raw:
        raise HTTPException(400, "Thiß║┐u tr╞░ß╗¥ng 'cookies' - d├ín JSON array tß╗½ BitBrowser")
    
    result = manager.import_cookies(profile_id, cookies_raw)
    if "error" in result:
        raise HTTPException(400, result["error"])
    
    # Nß║┐u ─æang chß║íy th├¼ b├ío cß║ºn restart
    if is_running(profile_id):
        result["need_restart"] = True
        result["message"] = f"─É├ú import {result['imported']}/{result['total']} cookies! ─É├│ng v├á mß╗ƒ lß║íi profile ─æß╗â cookie c├│ hiß╗çu lß╗▒c (tabs vß║½n giß╗»)."
    else:
        result["message"] = f"─É├ú import {result['imported']}/{result['total']} cookies! Mß╗ƒ profile l├¬n l├á d├╣ng ─æ╞░ß╗úc."
    
    return result

@app.get("/api/profiles/{profile_id}/export-cookies")
def export_cookies_endpoint(profile_id: str):
    profile = manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    
    if is_running(profile_id):
        raise HTTPException(400, "Vui l├▓ng ─É├ôNG profile tr╞░ß╗¢c khi xuß║Ñt cookie (Playwright ─æang lock th╞░ mß╗Ñc)!")
    
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
        raise HTTPException(500, f"Lß╗ùi ─æß╗ìc cookies: {e}")

@app.get("/api/profiles/{profile_id}/logs")
def get_logs(profile_id: str):
    log_file = BASE_DIR / "data" / "logs" / f"launch_{profile_id}.log"
    if not log_file.exists():
        return {"log": "Ch╞░a c├│ log"}
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
        folder_path = filedialog.askdirectory(title="Chß╗ìn th╞░ mß╗Ñc l╞░u Video")
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
        raise HTTPException(400, "Profile ─æang kh├┤ng chß║íy hoß║╖c kh├┤ng c├│ CDP port. H├úy mß╗ƒ lß║íi Chrome!")
        
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
                # Thß╗¡ connect nhiß╗üu lß║ºn ─æß╗â chß╗¥ browser khß╗ƒi ─æß╗Öng xong (nß║┐u bß╗ï gß╗ìi ─æß╗ông thß╗¥i vß╗¢i /launch)
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
                    print("Auto signup: Kh├┤ng thß╗â kß║┐t nß╗æi tß╗¢i Chrome, vui l├▓ng thß╗¡ lß║íi.")
                    try: p.stop()
                    except: pass
                    return
                    
                # T├¼m tab ─æang ß╗ƒ trang higgsfield, nß║┐u kh├┤ng c├│ th├¼ mß╗ƒ mß╗¢i
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
                    print(f"Lß╗ùi khi lß║Ñy/tß║ío tab Higgsfield: {e}")
                    try: p.stop()
                    except: pass
                    return
                
                # B1: Click n├║t Login hoß║╖c Sign up (nß║┐u ─æang ß╗ƒ trang chß╗º https://higgsfield.ai)
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
                        # Fallback: t├¼m bß║▒ng JS
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
                
                # B2: ─Éß╗úi popup "Welcome to Higgsfield" xuß║Ñt hiß╗çn hoß║╖c ph├ít hiß╗çn ─æ├ú login
                try:
                    for _ in range(15):
                        if "quiz" in page.url or "/ai/video" in page.url:
                            print("─É├ú ph├ít hiß╗çn URL login sß║╡n, bß╗Å qua chß╗¥ popup!")
                            break
                        wel_loc = page.locator("text=Welcome to Higgsfield")
                        if wel_loc.count() > 0 and wel_loc.first.is_visible():
                            print("Welcome to Higgsfield popup appeared!")
                            break
                        page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"Lß╗ùi chß╗¥ popup: {e}")
                
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
                    print(f"Lß╗ùi click Microsoft: {e}")
                
                # ─Éß╗úi chuyß╗ân sang trang login.microsoftonline.com
                page.wait_for_timeout(3000)
                print(f"Current URL after click: {page.url}")
                
                # === ─Éß╗ìc th├┤ng tin t├ái khoß║ún tß╗½ ms_account.txt ===
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
                    # ─Éß╗úi trang MS login hoß║╖c trang higgsfield (nß║┐u ─æ├ú login)
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
                    
                    # ─Éiß╗ün email v├áo ├┤ input
                    try:
                        import time
                        if "higgsfield.ai" in page.url: raise ValueError("Already logged in, skipping email")
                        email_input = page.locator('input[type="email"], input[name="loginfmt"], input[id="i0116"]')
                        email_input.wait_for(state="visible", timeout=10000)
                        email_input.click()
                        time.sleep(0.3)
                        email_input.fill(ms_email)
                        page.wait_for_timeout(500)
                        print(f"Filled email: {ms_email}")
                        
                        # Click n├║t Tiß║┐p theo / Next
                        next_btn = page.locator('input[type="submit"][value="Tiß║┐p theo"], input[type="submit"][value="Next"], input#idSIButton9, button:has-text("Tiß║┐p theo"), button:has-text("Next")')
                        if next_btn.count() > 0:
                            next_btn.first.click()
                        else:
                            page.keyboard.press("Enter")
                        print("Clicked Next after email")
                        page.wait_for_timeout(3000)
                        
                    except Exception as e:
                        print(f"Error filling email: {e}")
                    
                    # Kiß╗âm tra xem c├│ bß╗ï chuyß╗ân h╞░ß╗¢ng sang trang "X├íc minh email cß╗ºa bß║ín" (chß╗ìn ph╞░╞íng thß╗⌐c x├íc thß╗▒c) kh├┤ng
                    # Nß║┐u c├│, bß║Ñm "Sß╗¡ dß╗Ñng mß║¡t khß║⌐u cß╗ºa bß║ín" ─æß╗â quay lß║íi form mß║¡t khß║⌐u
                    try:
                        page.wait_for_timeout(1000)
                        if "higgsfield.ai" in page.url: raise ValueError("Already logged in, skipping use password")
                        use_pwd_btn = page.locator('a#iUsePasswordLink, a#idA_PWD_SwitchToPassword, span:has-text("Sß╗¡ dß╗Ñng mß║¡t khß║⌐u"), text="Sß╗¡ dß╗Ñng mß║¡t khß║⌐u", text="Use your password"')
                        if use_pwd_btn.count() > 0 and use_pwd_btn.first.is_visible():
                            use_pwd_btn.first.click(force=True)
                            print("Clicked 'Sß╗¡ dß╗Ñng mß║¡t khß║⌐u cß╗ºa bß║ín' (Use your password)")
                            page.wait_for_timeout(2000)
                    except:
                        pass
                        
                    # ─Éiß╗ün mß║¡t khß║⌐u
                    
                    # ─Éiß╗ün mß║¡t khß║⌐u
                    try:
                        if "higgsfield.ai" in page.url: raise ValueError("Already logged in, skipping password")
                        pwd_input = page.locator('input[type="password"], input[name="passwd"], input[id="i0118"]')
                        pwd_input.wait_for(state="visible", timeout=10000)
                        pwd_input.click()
                        time.sleep(0.3)
                        pwd_input.fill(ms_password)
                        page.wait_for_timeout(500)
                        print(f"Filled password")
                        
                        # Click n├║t Tiß║┐p theo / Sign in
                        signin_btn = page.locator('input[type="submit"][value="Tiß║┐p theo"], input[type="submit"][value="Sign in"], input#idSIButton9, button:has-text("Tiß║┐p theo"), button:has-text("Sign in")')
                        if signin_btn.count() > 0:
                            signin_btn.first.click()
                        else:
                            page.keyboard.press("Enter")
                        print("Clicked Sign in after password")
                        page.wait_for_timeout(4000)
                    except Exception as e:
                        print(f"Error filling password: {e}")
                    
                    # Xß╗¡ l├╜ trang "Gi├║p bß║úo vß╗ç t├ái khoß║ún cß╗ºa bß║ín" ΓåÆ Click "Th├¬m email"
                    try:
                        if "higgsfield.ai" in page.url: raise ValueError("Already logged in, skipping protection")
                        # ─Éß╗úi trang bß║úo vß╗ç hoß║╖c redirect
                        for _ in range(15):
                            cur_url = page.url
                            if "account.live.com/interrupt" in cur_url or "credentialaction" in cur_url:
                                break
                            page.wait_for_timeout(1000)
                        
                        if "account.live.com/interrupt" in page.url or "credentialaction" in page.url:
                            print("Trang bao ve tai khoan detected!")
                            # Click n├║t "Th├¬m email"
                            them_email_btn = page.locator('button:has-text("Th├¬m email"), input[value="Th├¬m email"], a:has-text("Th├¬m email")')
                            if them_email_btn.count() > 0:
                                them_email_btn.first.click()
                                print("Clicked 'Th├¬m email'!")
                            else:
                                page.evaluate("""() => {
                                    const all = document.querySelectorAll('button, input[type=submit], a');
                                    for (let el of all) {
                                        const t = (el.innerText || el.value || '').trim();
                                        if (t === 'Th├¬m email' || t.includes('Them email') || t.toLowerCase().includes('add email')) {
                                            el.click();
                                            return;
                                        }
                                    }
                                }""")
                                print("Clicked 'Th├¬m email' via JS fallback")
                            page.wait_for_timeout(2000)
                            
                            # === TinyHost API: Lß║Ñy email temp ─æß╗â x├íc minh ===
                            import urllib.request, json as json_mod, re as re_mod, string, random as random_mod
                            
                            def tinyhost_get_random_domain():
                                """Lß║Ñy domain ngß║½u nhi├¬n tß╗½ TinyHost API"""
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
                            
                            def tinyhost_check_inbox(domain, user, keyword="M├ú bß║úo mß║¡t"):
                                """Poll inbox t├¼m email chß╗⌐a keyword"""
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
                                """Tr├¡ch xuß║Ñt m├ú OTP 6 chß╗» sß╗æ tß╗½ body email"""
                                # T├¼m "M├ú bß║úo mß║¡t: XXXXXX" hoß║╖c 6 chß╗» sß╗æ ─æß╗⌐ng ri├¬ng
                                m = re_mod.search(r'[Mm]├ú bß║úo mß║¡t[:\s]+(\d{6})', text)
                                if m: return m.group(1)
                                m = re_mod.search(r'security code[:\s]+(\d{6})', text, re_mod.IGNORECASE)
                                if m: return m.group(1)
                                # T├¼m mß╗ìi chuß╗ùi 6 chß╗» sß╗æ
                                codes = re_mod.findall(r'\b(\d{6})\b', text)
                                if codes: return codes[0]
                                return None
                            
                            # Tß║ío email temp ngß║½u nhi├¬n
                            temp_domain = tinyhost_get_random_domain()
                            temp_user = ''.join(random_mod.choices(string.ascii_lowercase, k=6)) + ''.join(random_mod.choices(string.digits, k=4))
                            temp_email = f"{temp_user}@{temp_domain}"
                            print(f"Temp email for verification: {temp_email}")
                            
                            # Trang "Th├¬m ─æß╗ïa chß╗ë email" - ─æiß╗ün email temp v├áo
                            try:
                                # ─Éß╗úi trang "Th├¬m ─æß╗ïa chß╗ë email" load
                                email_selector = 'input[type="email"], input[name="EmailAddress"], input#iProofEmail, input[name="Email"], input#Email, input.fui-Input__input, input[type="text"]'
                                page.wait_for_selector(email_selector, timeout=10000)
                                email_field = page.locator(email_selector).first
                                email_field.wait_for(state="visible", timeout=5000)
                                email_field.fill(temp_email)
                                page.wait_for_timeout(500)
                                print(f"Filled temp email: {temp_email}")
                                
                                # Click Tiß║┐p theo
                                next_btn = page.locator('input[type="submit"], button[type="submit"], button:has-text("Tiß║┐p theo"), button:has-text("Next")')
                                if next_btn.count() > 0:
                                    next_btn.first.click()
                                else:
                                    page.keyboard.press("Enter")
                                print("Clicked Next after temp email")
                                page.wait_for_timeout(3000)
                            except Exception as e:
                                print(f"Error filling temp email: {e}")
                            
                            # === Poll TinyHost API ─æß╗â lß║Ñy m├ú OTP ===
                            otp_code = None
                            print(f"Polling TinyHost inbox for OTP... ({temp_email})")
                            for attempt in range(20):  # thß╗¡ 20 lß║ºn, mß╗ùi lß║ºn c├ích 5 gi├óy = 100s tß╗òng
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
                                # ─Éiß╗ün m├ú OTP v├áo trang "Nhß║¡p m├ú cß╗ºa bß║ín"
                                # Microsoft d├╣ng 6 ├┤ input ri├¬ng biß╗çt hoß║╖c 1 ├┤ nhß║¡p 6 sß╗æ
                                try:
                                    # Thß╗¡ 6 ├┤ ri├¬ng biß╗çt tr╞░ß╗¢c
                                    otp_inputs = page.locator('input[id^="codeEntry-"], input[id^="idTxtBx_SAOTCC_OTC_"], input[maxlength="1"]')
                                    if otp_inputs.count() >= 6:
                                        for i, digit in enumerate(otp_code):
                                            if i < otp_inputs.count():
                                                otp_inputs.nth(i).fill(digit)
                                                page.wait_for_timeout(100)
                                        print(f"Filled OTP in 6 separate inputs: {otp_code}")
                                    else:
                                        # 1 ├┤ nhß║¡p dß║íng text/number
                                        single_input = page.locator('input[type="text"], input[type="tel"], input[type="number"]').first
                                        single_input.fill(otp_code)
                                        print(f"Filled OTP in single input: {otp_code}")
                                    
                                    page.wait_for_timeout(500)
                                    
                                    # Click Tiß║┐p theo ─æß╗â x├íc nhß║¡n
                                    confirm_btn = page.locator('input[type="submit"], button[type="submit"], button:has-text("Tiß║┐p theo"), button:has-text("Verify"), button:has-text("Next")')
                                    if confirm_btn.count() > 0:
                                        confirm_btn.first.click()
                                    else:
                                        page.keyboard.press("Enter")
                                    print("Submitted OTP code!")
                                    page.wait_for_timeout(3000)
                                    
                                    # Xß╗¡ l├╜ chuß╗ùi trang sau khi nhß║¡p m├ú OTP
                                    # (─É├ú chuyß╗ân v├▓ng lß║╖p pop-up ra ngo├ái)
                                except Exception as e:
                                    print(f"Error filling OTP: {e}")
                            else:
                                print("OTP not received within timeout. Manual intervention needed.")
                    except Exception as e:
                        print(f"Error on protection page: {e}")
                    
                    # === V├▓ng lß║╖p to├án cß║ºu xß╗¡ l├╜ c├íc trang sau khi ─æ─âng nhß║¡p (Quiz, Yes/Accept, FIDO, Turnstile) ===
                    print("Handling post-login popups...")
                    for _ in range(30):
                        page.wait_for_timeout(2000)
                        cur_url = page.url
                        
                        if "higgsfield.ai/ai/video" in cur_url and "quiz" not in cur_url:
                            # ─Éß╗úi th├¬m 3s ─æß╗â chß║»c chß║»n React kh├┤ng redirect ng╞░ß╗úc vß╗ü Quiz
                            page.wait_for_timeout(3000)
                            if "quiz" not in page.url:
                                print("─É├ú ─æ─âng nhß║¡p th├ánh c├┤ng v├áo Higgsfield!")
                                break
                            
                        # 0.5 Kiß╗âm tra popup Congratulations (Upgrade promotion)
                        try:
                            congrats = page.locator('text=Congratulations')
                            if congrats.count() > 0 and congrats.first.is_visible():
                                print("─É├ú gß║╖p popup Congratulations! ─É─âng k├╜ ho├án tß║Ñt.")
                                break
                        except: pass
                            
                        # Xß╗¡ l├╜ trang Quiz (Khß║úo s├ít ng╞░ß╗¥i d├╣ng mß╗¢i)
                        if "higgsfield.ai/quiz" in cur_url:
                            # Khß╗ƒi tß║ío bß╗Ö nhß╗¢ tß║ím ─æß╗â kh├┤ng click lß║íi ─æ├íp ├ín c┼⌐ (tr├ính kß║╣t ß╗ƒ slide 1)
                            if not hasattr(page, 'quiz_clicked_options'):
                                page.quiz_clicked_options = set()

                            # 0. Kiß╗âm tra lß╗ùi "Couldn't save your answer"
                            try:
                                error_toast = page.locator('text="Couldn\'t save your answer"')
                                if error_toast.count() > 0 and error_toast.first.is_visible():
                                    print("Quiz: Bß╗ï lß╗ùi 'Couldn't save your answer', ─æang tß║úi lß║íi trang...")
                                    page.reload()
                                    page.wait_for_timeout(3000)
                                    continue
                            except: pass

                            # 1. Bß║Ñm n├║t Chß║Ñp nhß║¡n Cookie nß║┐u c├│
                            try:
                                page.evaluate("""() => {
                                    const btns = document.querySelectorAll('button');
                                    for(let b of btns) {
                                        if (b.innerText.includes('Chß║Ñp nhß║¡n tß║Ñt cß║ú') || b.innerText.includes('Accept all')) {
                                            b.click();
                                        }
                                    }
                                }""")
                            except: pass
                            
                            # 1.5 Kiß╗âm tra trang Claim Username (B╞░ß╗¢c cuß╗æi c├╣ng)
                            try:
                                if page.locator('text="Claim your username"').count() > 0:
                                    terms_label = page.locator('label:has-text("I agree to the Terms of Use")').locator("visible=true")
                                    if terms_label.count() > 0:
                                        # Click checkbox
                                        terms_box = terms_label.first.bounding_box()
                                        if terms_box:
                                            page.mouse.click(terms_box["x"] + 10, terms_box["y"] + terms_box["height"] / 2)
                                            print("Quiz: T├¡ch chß╗ìn 'I agree to the Terms of Use'")
                                            page.wait_for_timeout(500)
                            except Exception as e:
                                pass

                            # 2. Click c├íc ─æ├íp ├ín bß║▒ng Tß╗ìa ─æß╗Ö chuß╗Öt vß║¡t l├╜ (v╞░ß╗út qua mß╗ìi giß╗¢i hß║ín cß╗ºa React)
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
                                            # Di chuyß╗ân v├á click chuß╗Öt thß║¡t v├áo ch├¡nh giß╗»a phß║ºn tß╗¡
                                            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                            print(f"Quiz: Mouse clicked option '{q_text}'")
                                            page.quiz_clicked_options.add(q_text)
                                            page.wait_for_timeout(800)
                                            
                                            # Kiß╗âm tra xem n├║t Continue ─æ├ú s├íng l├¬n ch╞░a (nß║┐u s├íng rß╗ôi th├¼ nghß╗ë click c├íc ─æ├íp ├ín kh├íc)
                                            cont_btn = page.locator('button:has-text("Continue")').locator("visible=true")
                                            if cont_btn.count() > 0 and not cont_btn.first.is_disabled():
                                                break
                                except Exception as e:
                                    pass
                                    
                            # 3. Bß║Ñm Continue sau khi ─æ├ú chß╗ìn xong (Kß╗â cß║ú popup Start with Higgsfield Academy)
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
                            
                        # 1. N├║t "Tr├┤ng rß║Ñt ─æ╞░ß╗úc!" / "Looks good!"
                        looks_good_btn = page.locator('#iLooksGood, input[value*="Tr├┤ng rß║Ñt ─æ╞░ß╗úc"], input[value*="Looks good"]')
                        if looks_good_btn.count() > 0 and looks_good_btn.first.is_visible():
                            looks_good_btn.first.click()
                            print("Clicked 'Tr├┤ng rß║Ñt ─æ╞░ß╗úc!' (Looks good)")
                            continue
                            
                        # 2. Trang chß╗º Higgsfield bß║»t ─æ─âng nhß║¡p lß║íi
                        if "higgsfield.ai/auth/sign-in" in cur_url or ("higgsfield.ai" in cur_url and "login.microsoftonline" not in cur_url):
                            ms_btn = page.locator('button:has-text("Continue with Microsoft"), div:has-text("Continue with Microsoft")')
                            if ms_btn.count() > 0 and ms_btn.first.is_visible():
                                ms_btn.first.click()
                                print("Clicked 'Continue with Microsoft' again after redirect")
                                continue
                                
                        # 3. Form nhß║¡p email lß║íi (nß║┐u c├│)
                        email_input = page.locator('input[type="email"], input[name="loginfmt"]')
                        if email_input.count() > 0 and email_input.first.is_visible():
                            email_input.first.fill(ms_email)
                            page.keyboard.press("Enter")
                            print("Filled email again")
                            continue
                            
                        # 4. Form nhß║¡p password lß║íi (nß║┐u c├│)
                        pwd_input = page.locator('input[type="password"], input[name="passwd"]')
                        if pwd_input.count() > 0 and pwd_input.first.is_visible():
                            pwd_input.first.fill(ms_password)
                            page.keyboard.press("Enter")
                            print("Filled password again")
                            continue
                            
                        # 5. Trang thiß║┐t lß║¡p Security Key (bß║úng ─æen FIDO2) -> Bß║Ñm Hß╗ºy (Cancel)
                        if "fido" in cur_url or "fido/create" in cur_url:
                            # Cß╗æ gß║»ng tß║»t dialog native cß╗ºa Windows (Security key)
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                            cancel_btn = page.locator('#iCancel, a#iCancel, button#iCancel, input[value="Hß╗ºy"], input[value="Cancel"], a:has-text("Hß╗ºy"), button:has-text("Hß╗ºy")')
                            if cancel_btn.count() > 0 and cancel_btn.first.is_visible():
                                cancel_btn.first.click()
                                print("Clicked Cancel for Security Key setup")
                                continue
                                
                        # 6. N├║t C├│ (Yes) / Chß║Ñp nhß║¡n (Accept) - Duy tr├¼ ─æ─âng nhß║¡p / Cho ph├⌐p ß╗⌐ng dß╗Ñng
                        yes_btn = page.locator('input#idSIButton9, button#idSIButton9, button#acceptButton, input#acceptButton, input[value="C├│"], input[value="Yes"], input[value="Chß║Ñp nhß║¡n"], input[value="Accept"], button:text-is("C├│"), button:text-is("Yes"), button:has-text("Chß║Ñp nhß║¡n")')
                        if yes_btn.count() > 0 and yes_btn.first.is_visible():
                            yes_btn.first.click(force=True)
                            print("Clicked Yes / Accept")
                            continue
                            
                        # 7. T├¡ch chß╗ìn Cloudflare Turnstile "X├íc minh bß║ín l├á con ng╞░ß╗¥i"
                        try:
                            # Nß║┐u nß║▒m ngo├ái c├╣ng
                            cf_checkbox = page.locator('input[type="checkbox"][aria-label*="con ng╞░ß╗¥i"], input[type="checkbox"][aria-label*="human"]')
                            if cf_checkbox.count() > 0 and cf_checkbox.first.is_visible():
                                cf_checkbox.first.click(force=True, position={"x": 5, "y": 5})
                                print("Clicked Turnstile checkbox (main frame)")
                                continue
                                
                            # Nß║┐u nß║▒m trong iframe
                            cf_iframe = page.frame_locator('iframe[src*="cloudflare.com"], iframe[src*="turnstile"]')
                            cf_checkbox_iframe = cf_iframe.locator('input[type="checkbox"]')
                            if cf_checkbox_iframe.count() > 0:
                                cf_checkbox_iframe.first.click(force=True)
                                print("Clicked Turnstile checkbox (in iframe)")
                                continue
                        except Exception:
                            pass
                else:
                    print("Kh├┤ng c├│ th├┤ng tin t├ái khoß║ún MS. Vui l├▓ng bß║Ñm n├║t 'D├ín mail' ─æß╗â th├¬m t├ái khoß║ún tr╞░ß╗¢c!")
                
                # ====== B╞»ß╗ÜC CUß╗ÉI C├ÖNG: KIß╗éM TRA FREE GENS ======
                if "auth/sign-in" not in page.url:
                    print("─Éang kiß╗âm tra trß║íng th├íi Free Gens...")
                    try:
                        page.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=30000)
                        
                        def check_free_gens():
                            page.wait_for_timeout(4000)
                            if page.locator('text="Use free gens"').count() > 0:
                                return True
                            return False
                            
                        is_free = check_free_gens()
                        if not is_free:
                            print("Ch╞░a thß║Ñy 'Use free gens', reload trang...")
                            page.reload(timeout=30000)
                            is_free = check_free_gens()
                            if not is_free:
                                print("Vß║½n ch╞░a thß║Ñy 'Use free gens', reload lß║ºn cuß╗æi...")
                                page.reload(timeout=30000)
                                is_free = check_free_gens()
                                
                        p_obj = manager.get_profile(profile.id)
                        if p_obj:
                            if is_free:
                                p_obj.notes = "free gen"
                                print("=> Cß║¡p nhß║¡t thß║╗ th├ánh 'free gen' (Xanh l├í)")
                            else:
                                p_obj.notes = "kh├┤ng free"
                                print("=> Cß║¡p nhß║¡t thß║╗ th├ánh 'kh├┤ng free' (V├áng)")
                            manager._save()
                    except Exception as e:
                        print(f"Lß╗ùi khi kiß╗âm tra Free Gens: {e}")
                
        except Exception as e:
            print(f"Auto signup FATAL err: {e}")
        finally:
            try:
                p.stop()
            except: pass
            try:
                close_profile(profile.id)
                print(f"─É├ú ─æ├│ng Chrome cho profile {profile.name} sau khi ho├án tß║Ñt kiß╗âm tra.")
            except: pass

    threading.Thread(target=run_auto_signup, daemon=True).start()
    return {"ok": True, "message": "Bß║»t ─æß║ºu Auto Login Higgsfield (Microsoft)..."}

@app.post("/api/profiles/{profile_id}/set-ms-account")
def set_ms_account(profile_id: str, payload: dict = Body(...)):
    """L╞░u th├┤ng tin t├ái khoß║ún Microsoft v├áo profile. Format: email|password|token|guid"""
    profile = manager.get_profile(profile_id)
    if not profile: raise HTTPException(404, "Profile not found")
    
    raw = payload.get("raw", "").strip()
    if not raw:
        raise HTTPException(400, "Thiß║┐u dß╗» liß╗çu t├ái khoß║ún")
    
    parts = raw.split("|")
    if len(parts) < 2:
        raise HTTPException(400, "Sai ─æß╗ïnh dß║íng. Cß║ºn: email|password hoß║╖c email|password|token|guid")
    
    email = parts[0].strip()
    password = parts[1].strip()
    
    acc_file = Path(profile.user_data_dir) / "ms_account.txt"
    acc_file.parent.mkdir(parents=True, exist_ok=True)
    acc_file.write_text(raw, encoding="utf-8")
    
    return {"ok": True, "email": email, "message": f"─É├ú l╞░u t├ái khoß║ún {email}"}


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
    """Mß╗ƒ tr├¼nh duyß╗çt vß╗¢i Random FP v├á k├¡ch hoß║ít extension
    only_navigator=True: chß╗ë bß║¡t n├║t 1 (Spoof Navigator) - d├╣ng khi cß║ºn tß║úi ß║únh
    close_old_tabs=True: ─æ├│ng hß║┐t c├íc tab c┼⌐ khi mß╗ƒ l├¬n (chß╗ë d├╣ng cho video creation)
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
    # Bß╗Å tß║úi extension theo y├¬u cß║ºu
    ignore_args = []
    args.append("--disable-extensions")
    if is_headless:
        # Tß║»t chß║┐ ─æß╗Ö headless thß║¡t ─æß╗â tr├ính bß╗ï website ph├ít hiß╗çn/cß║»t x├⌐n DOM
        # Thay v├áo ─æ├│, ─æß║⌐y cß╗¡a sß╗ò ra t├¡t ngo├ái m├án h├¼nh ─æß╗â giß║Ñu giao diß╗çn ─æi (vß║½n tiß║┐t kiß╗çm t├ái nguy├¬n m├á an to├án 100%)
        # ─É├ú comment lß║íi theo y├¬u cß║ºu ng╞░ß╗¥i d├╣ng ─æß╗â lu├┤n hiß╗ân thß╗ï Chrome
        # args.append("--window-position=-32000,-32000")
        # args.append("--window-size=1366,768")
        pass
        
    engine = os.environ.get("HIGGSFIELD_BROWSER_ENGINE", "chrome").lower()
    if engine == "cloakbrowser":
        from cloakbrowser import launch_persistent_context
        # CloakBrowser tß╗▒ ─æß╗Öng xß╗¡ l├╜ extension_paths v├á ignore_default_args
        cloak_args = [a for a in args if not a.startswith("--load-extension") and a != "--disable-extensions"]
        cloak_kwargs = {
            "user_data_dir": profile.user_data_dir,
            "headless": False,
            "args": cloak_args,
            "accept_downloads": True,
            "downloads_path": str(Path.home() / "Downloads")
        }
        # if ext_path:
        #     cloak_kwargs["extension_paths"] = [ext_path]
            
        context = launch_persistent_context(**cloak_kwargs)
    else:
        context = p.chromium.launch_persistent_context(
            profile.user_data_dir,
            headless=False,
            **browser_launch_options(),
            ignore_default_args=ignore_args,
            args=args,
            accept_downloads=True,
            downloads_path=str(Path.home() / "Downloads"),
        )

    # Chrome tß╗▒ xß╗¡ l├╜ download 100% native - Kh├┤ng chß║╖n, kh├┤ng xß╗¡ l├╜ bß║▒ng Playwright ─æß╗â tr├ính crash/lß╗ùi .crdownload


    return context

def _activate_canvas_spoof(context, ext_path):
    """K├¡ch hoß║ít Spoof Canvas SAU khi ─æ├ú upload ß║únh th├ánh c├┤ng"""
    return # Kh├┤ng mß╗ƒ popup extension n├áy nß╗»a theo y├¬u cß║ºu
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
            video_tasks[task_id]["message"] = "Trang y├¬u cß║ºu ─æ─âng nhß║¡p. ─Éang tß╗▒ ─æß╗Öng ─æiß╗ün mß║¡t khß║⌐u..."
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
                    # Fallback nß║┐u click/type lß╗ùi
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
    """─Éiß╗ün prompt + upload ß║únh v├áo bfl.ai. Trß║ú vß╗ü True nß║┐u OK."""
    _handle_auto_login(page, video_tasks, task_id)
    
    # ─Éß╗úi textarea
    try:
        page.wait_for_selector("textarea[placeholder*='Describe']", timeout=15000)
    except:
        return False

    # ─Éiß╗ün prompt bß║▒ng JS (tr├ính overlay chß║╖n)
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
        # Nß║┐u l├á retry, ß║únh ─æ├ú ─æ╞░ß╗úc l╞░u ß╗ƒ session bfl.ai n├¬n KH├öNG Cß║ªN Tß║óI Lß║áI
        video_tasks[task_id] = {"status": "running", "message": "Form ─æ├ú sß║╡n s├áng (bß╗Å qua b╞░ß╗¢c tß║úi ß║únh)."}
        return True

    # Bß╗Å ß║únh c┼⌐ tr╞░ß╗¢c khi tß║úi ß║únh mß╗¢i (kß╗â cß║ú khi kh├┤ng c├│ ß║únh mß╗¢i c┼⌐ng bß╗Å)
    try:
        page.evaluate("""() => {
            const removeBtns = document.querySelectorAll("button[aria-label^='Remove']");
            removeBtns.forEach(b => b.click());
        }""")
        page.wait_for_timeout(1000)
    except:
        pass

    # Click n├║t "All parameters" ─æß╗â hiß╗çn phß║ºn tß║úi ß║únh (giao diß╗çn bfl.ai mß╗¢i cß║¡p nhß║¡t)
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
        # Upload ß║únh 1 - Start frame (Spoof Canvas CH╞»A ─æ╞░ß╗úc bß║¡t ß╗ƒ b╞░ß╗¢c n├áy)
        video_tasks[task_id] = {"status": "running", "message": "─Éang tß║úi ß║únh 1 (Start frame)..."}
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
                video_tasks[task_id] = {"status": "running", "message": f"Cß║únh b├ío tß║úi ß║únh 1: {e}"}

    # Γ£à ß║ónh 1 ─æ├ú upload th├ánh c├┤ng ΓåÆ Giß╗¥ mß╗¢i bß║¡t Spoof Canvas an to├án
    if img1_ok:
        video_tasks[task_id] = {"status": "running", "message": "ß║ónh 1 OK! ─Éang k├¡ch hoß║ít Spoof Canvas..."}
        _activate_canvas_spoof(context, ext_path)
        page.wait_for_timeout(500)

    # Upload ß║únh 2 - End frame (optional)
    if img2_path and Path(img2_path).exists():
        video_tasks[task_id] = {"status": "running", "message": "─Éang tß║úi ß║únh 2 (End frame)..."}
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
    """Kiß╗âm tra xem c├│ xuß║Ñt hiß╗çn 'GENERATING' hoß║╖c 'QUEUED' ß╗ƒ giß╗»a m├án h├¼nh kh├┤ng v├á lß║Ñy text"""
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
    """Kiß╗âm tra xem c├│ bß╗ï lß╗ùi hß╗ç thß╗æng (Rate limited, 503, Over capacity) kh├┤ng"""
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
    """Lß║Ñy URL video Mß╗ÜI nhß║Ñt c├│ chß╗⌐a prompt t╞░╞íng ß╗⌐ng. ─Éß║úm bß║úo 100% kh├┤ng bß║»t nhß║ºm video c┼⌐."""
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
        print(f"Lß╗ùi gß╗¡i Telegram: {e}")

def run_video_automation(task_id, prompt, media_paths, profile_id, save_path, is_headless=False, enable_ext=False, enable_ext_btn2=False, tg_enabled=False, tg_token="", tg_chat_id=""):
    """Background thread: mß╗ƒ higgsfield.ai, ─æ─âng nhß║¡p Microsoft, upload ß║únh, nhß║¡p prompt v├á tß║ío video."""
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

    video_tasks[task_id] = {"status": "running", "message": "─Éang mß╗ƒ tr├¼nh duyß╗çt..."}
    video_tasks_chat[task_id] = {"messages": [], "queue": []}
    is_retrying = False

    def sync_chat(pg):
        if task_id not in video_tasks_chat: return
        try:
            msgs = pg.evaluate("""() => {
                try {
                    // C├üCH CHß║«C CHß║«N NHß║ñT: Bß║»t thß║│ng v├áo tr├íi tim cß╗ºa mß╗ìi tin nhß║»n (khung chß╗⌐a chß╗»)
                    let textContainers = Array.from(document.querySelectorAll('.container-enLQFx, .container-fBOrXO, [data-message-id]'));
                    
                    if (textContainers.length === 0) return [{role: "bot", text: "DEBUG: Kh├┤ng t├¼m thß║Ñy bß║Ñt kß╗│ thß║╗ text n├áo trong DOM!"}];

                    const results = textContainers.map(node => {
                        // Tr├ính lß║Ñy tr├╣ng lß║╖p nß║┐u querySelectorAll lß║Ñy cß║ú cha lß║½n con
                        // ╞»u ti├¬n lß║Ñy text tß╗½ container trong c├╣ng
                        let txt = node.innerText || node.textContent || "";
                        txt = txt.replace('Tß║úi vß╗ü cho Windows', '').trim();
                        
                        // X├íc ─æß╗ïnh User/Bot bß║▒ng c├ích d├▓ ng╞░ß╗úc l├¬n c├íc thß║╗ cha xem c├│ ─æß║╖c ─æiß╗âm cß╗ºa User kh├┤ng
                        const isUser = node.classList.contains('justify-end') || 
                                       (node.closest && node.closest('.justify-end') !== null) ||
                                       (node.parentElement && node.parentElement.classList.contains('justify-end'));
                                       
                        return { role: isUser ? "user" : "bot", text: txt };
                    }).filter(Boolean);
                    
                    if (results.length === 0) return [{role: "bot", text: `DEBUG: T├¼m thß║Ñy ${textContainers.length} thß║╗ nh╞░ng bß╗ï filter do rß╗ùng!`}];
                    
                    // Lß╗ìc bß╗Å c├íc tin nhß║»n bß╗ï tr├╣ng lß║╖p (giß╗» lß║íi c├íi d├ái nhß║Ñt nß║┐u bß╗ï lß╗ông nhau)
                    const uniqueResults = [];
                    for(let r of results) {
                        const existing = uniqueResults.find(x => x.text === r.text || x.text.includes(r.text) || r.text.includes(x.text));
                        if(!existing) {
                            uniqueResults.push(r);
                        } else if (r.text.length > existing.text.length) {
                            // Cß║¡p nhß║¡t lß║íi nß║┐u t├¼m thß║Ñy chuß╗ùi bao h├ám d├ái h╞ín
                            existing.text = r.text;
                        }
                    }
                    return uniqueResults;
                } catch(e) {
                    return [{role: "bot", text: "Lß╗ùi b├│c t├ích: " + e.message}];
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
        engine = os.environ.get("HIGGSFIELD_BROWSER_ENGINE", "chrome").lower()
        if engine == "cloakbrowser":
            p = None
            context = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=enable_ext_btn2, is_headless=is_headless)
        else:
            with pw_lock:
                p = sync_playwright().start()
            context = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=enable_ext_btn2, is_headless=is_headless)
            
        # T├íi sß╗¡ dß╗Ñng tab ─æß║ºu ti├¬n nß║┐u c├│ ─æß╗â tr├ính mß╗ƒ nhiß╗üu tab
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
                    print(f"Lß╗ùi lß║Ñy page, thß╗¡ lß║íi sau 1s: {e}")
                    time.sleep(1)
        
        if not page:
            raise Exception("Kh├┤ng thß╗â khß╗ƒi tß║ío tab Chrome. Vui l├▓ng tß║»t thß╗º c├┤ng Chrome cß╗ºa profile n├áy v├á thß╗¡ lß║íi!")
            
        # ─É├│ng c├íc tab d╞░ thß╗½a
        for i in range(1, len(context.pages)):
            try: context.pages[i].close()
            except: pass

        # (─É├â Bß╗Ä Cß║«T COOKIE HIGGSFIELD ─Éß╗é GIß╗« TRß║áNG TH├üI LOGIN Tß╗¬ PROFILE)
        # video_tasks[task_id] = {"status": "running", "message": "─Éang giß║ú lß║¡p m├íy t├¡nh ho├án to├án mß╗¢i (Clear Cookies)..."}
        # ... ─æoß║ín code x├│a cookie ─æ├ú bß╗ï v├┤ hiß╗çu h├│a ...

        # ΓöÇΓöÇ B╞»ß╗ÜC 1: Mß╗ƒ higgsfield.ai/chat ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        video_tasks[task_id] = {"status": "running", "message": "─Éang mß╗ƒ higgsfield.ai/ai/video..."}
        page.goto("https://higgsfield.ai/ai/video?model=genjutsu", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        
        # Xß╗¡ l├╜ trang lß╗ùi "This page is temporarily unavailable"
        try:
            if page.locator("text='This page is temporarily unavailable'").is_visible(timeout=3000):
                video_tasks[task_id] = {"status": "running", "message": "higgsfield bß╗ï lß╗ùi tß║ím thß╗¥i, ─æang ß║Ñn Refresh..."}
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
                        el.innerText.trim() === 'X├íc nhß║¡n' ||
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

        # ΓöÇΓöÇ B╞»ß╗ÜC 2: Kiß╗âm tra ─æ├ú login ch╞░a (Dß╗▒a v├áo sß╗▒ tß╗ôn tß║íi cß╗ºa n├║t Log In) ΓöÇΓöÇ
        video_tasks[task_id] = {"status": "running", "message": "Kiß╗âm tra trß║íng th├íi ─æ─âng nhß║¡p..."}
        already_logged_in = False
        try:
            # ─Éß╗úi cho trang load xong v├á c├íc phß║ºn tß╗¡ ß╗òn ─æß╗ïnh
            try:
                page.wait_for_load_state("load", timeout=10000) # D├╣ng load thay v├¼ networkidle cho lß║╣
            except:
                pass
            
            # ΓöÇΓöÇ B╞»ß╗ÜC 2: Kiß╗âm tra ─æ├ú login ch╞░a (Chß╗¥ giao diß╗çn load xong chß╗» 'Use free gens' hoß║╖c n├║t 'Log In') ΓöÇΓöÇ
            is_logged_in = False
            try:
                import re
                # V├▓ng lß║╖p chß╗¥ th├┤ng minh (tß╗æi ─æa 15 gi├óy) ─æß╗â React load xong dß╗» liß╗çu
                for _ in range(30):
                    # 1. Qu├⌐t t├¼m chß╗» "Use free gens" (dß║Ñu hiß╗çu chß║»c chß║»n ─æ├ú login)
                    try:
                        # D├╣ng JS cho chß║»c v├¼ text c├│ thß╗â nß║▒m rß║úi r├íc
                        has_free_gens = page.evaluate("() => document.body.innerText.toLowerCase().includes('use free gens')")
                        if has_free_gens:
                            is_logged_in = True
                            print("--- ─É├ú thß║Ñy 'Use free gens' -> ─É├ú login!")
                            break
                    except: pass
                    
                    # 2. Qu├⌐t t├¼m n├║t Avatar ─æ├ú ─æ─âng nhß║¡p
                    try:
                        avatar_loc = page.locator('button[aria-label="Account menu"], button[aria-haspopup="menu"], button:has(.rounded-full), div[role="button"]:has(.rounded-full)').filter(has_not_text=re.compile(r"^(─É─âng nhß║¡p|Log In|Sign In)$", re.IGNORECASE))
                        if avatar_loc.count() > 0 and avatar_loc.first.is_visible():
                            is_logged_in = True
                            print("--- ─É├ú thß║Ñy n├║t Avatar -> ─É├ú login!")
                            break
                    except: pass

                    # 3. Qu├⌐t t├¼m n├║t Log In (nß║┐u thß║Ñy n├║t n├áy ngh─⌐a l├á chß║»c chß║»n CH╞»A login)
                    try:
                        login_btn = page.locator("button, a").filter(has_text=re.compile(r"^(─É─âng nhß║¡p|Log In|Login|Sign In)$", re.IGNORECASE))
                        if login_btn.count() > 0 and login_btn.first.is_visible():
                            print("--- ─É├ú thß║Ñy n├║t Log In -> Ch╞░a login!")
                            break # Tho├ít v├▓ng lß║╖p, is_logged_in vß║½n l├á False
                    except: pass
                    
                    page.wait_for_timeout(500)
                    
            except Exception as inner_e:
                print(f"Lß╗ùi soi trß║íng th├íi login: {inner_e}")
                pass
            
            already_logged_in = is_logged_in
            print(f"--- [B╞»ß╗ÜC 2] Kß║┐t quß║ú qu├⌐t trß║íng th├íi: {'─É├â LOGIN Tß╗¬ TR╞»ß╗ÜC' if already_logged_in else 'CH╞»A LOGIN (Sß║╜ chß║íy B╞░ß╗¢c 3 & 4)'}")
        except Exception as e:
            print(f"--- Lß╗ùi kiß╗âm tra login: {e}")
            already_logged_in = False

        if not already_logged_in:
            # Qu├⌐t xem c├│ modal "Log In to Unlock More Features" ─æang mß╗ƒ sß║╡n kh├┤ng
            is_modal_open = False
            try:
                is_modal_open = page.locator("text='Log In to Unlock More Features'").is_visible(timeout=2000)
            except:
                pass
            
            if not is_modal_open:
                # ΓöÇΓöÇ B╞»ß╗ÜC 3: ß║ñn "─É─âng nhß║¡p" / "Log In" ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
                video_tasks[task_id] = {"status": "running", "message": "─Éang mß╗ƒ bß║úng ─É─âng nhß║¡p..."}
                
                try:
                    # V├▓ng lß║╖p ß║Ñn n├║t Log In cho ─æß║┐n khi bß║úng hiß╗çn ra (tß╗æi ─æa 5 lß║ºn)
                    for _ in range(5):
                        # T├¼m n├║t Log In (th╞░ß╗¥ng nß║▒m g├│c phß║úi tr├¬n c├╣ng)
                        login_btn = page.locator("button, a").filter(has_text=re.compile(r"^(─É─âng nhß║¡p|Log In|Login|Sign In)$", re.IGNORECASE)).first
                        if login_btn.is_visible():
                            box = login_btn.bounding_box()
                            if box:
                                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                page.wait_for_timeout(300)
                                page.mouse.down()
                                page.wait_for_timeout(150)
                                page.mouse.up()
                                page.wait_for_timeout(500)
                                # Fallback click JS nß║┐u mouse click bß╗ï xß╗ït
                                page.evaluate("""(btn) => { if(btn) btn.click(); }""", login_btn.element_handle())
                        else:
                            # Nß║┐u kh├┤ng thß║Ñy n├║t Log In, thß╗¡ t├¼m n├║t bß║Ñt kß╗│ ß╗ƒ g├│c tr├¬n b├¬n phß║úi
                            page.evaluate("""() => {
                                const btns = Array.from(document.querySelectorAll('button'));
                                const loginBtn = btns.find(b => b.innerText && b.innerText.toLowerCase().includes('log'));
                                if(loginBtn) loginBtn.click();
                            }""")
                        
                        page.wait_for_timeout(2000) # ─Éß╗úi 2s ─æß╗â bß║úng bung ra rß╗ôi check lß║íi
                        
                        try:
                            is_modal = page.locator("text='Log In to Unlock More Features'").is_visible(timeout=1000)
                            if is_modal:
                                print("--- ─É├ú thß║Ñy bß║úng Log In to Unlock More Features!")
                                break
                        except:
                            pass
                except Exception as e:
                    print(f"--- Lß╗ùi khi ß║Ñn n├║t Log In: {e}")
            else:
                print("--- Bß║úng ─æ─âng nhß║¡p ─æ├ú mß╗ƒ sß║╡n!")

            # ΓöÇΓöÇ B╞»ß╗ÜC 4: ß║ñn "Continue with Microsoft" / "Tiß║┐p tß╗Ñc bß║▒ng Microsoft" ΓöÇΓöÇ
            try:
                video_tasks[task_id] = {"status": "running", "message": "─Éang d├▓ tß╗ìa ─æß╗Ö n├║t Microsoft ─æß╗â click thß║¡t..."}
                
                # Chß╗¥ 3s cho popup c├│ thß╗¥i gian bung ra ho├án chß╗ënh
                page.wait_for_timeout(3000)
                
                # D├╣ng JS lß║Ñy tß╗ìa ─æß╗Ö (x, y, width, height) cß╗ºa n├║t thay v├¼ click ß║úo bß║▒ng JS (v├¼ JS click ß║úo bß╗ï web bß╗Å qua)
                js_get_rect = """
                () => {
                    let btn = document.evaluate(
                      "//button[.//*[normalize-space()='Continue with Microsoft']]",
                      document,
                      null,
                      XPathResult.FIRST_ORDERED_NODE_TYPE,
                      null
                    ).singleNodeValue;
                    
                    if (!btn) {
                        const btns = Array.from(document.querySelectorAll('button'));
                        btn = btns.find(b => b.innerText && b.innerText.includes('Microsoft'));
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
                for i in range(15): # Lß║╖p 15 lß║ºn (tß╗æi ─æa 30s)
                    try:
                        rect_info = page.evaluate(js_get_rect)
                        if rect_info and rect_info.get("found"):
                            # D├╣ng Playwright di chuß╗Öt Vß║¼T L├¥ ─æß║┐n tß╗ìa ─æß╗Ö t├óm n├║t v├á nhß║Ñp ─æ├║p nh╞░ ng╞░ß╗¥i thß║¡t
                            center_x = rect_info["x"] + rect_info["width"] / 2
                            center_y = rect_info["y"] + rect_info["height"] / 2
                            
                            page.mouse.move(center_x, center_y, steps=10)
                            page.wait_for_timeout(500)
                            
                            # Click lß║ºn 1
                            page.mouse.down()
                            page.wait_for_timeout(100)
                            page.mouse.up()
                            page.wait_for_timeout(200)
                            
                            # Click lß║ºn 2
                            page.mouse.down()
                            page.wait_for_timeout(150)
                            page.mouse.up()
                            
                            # Kiß╗âm tra xem bß║úng popup ─æ├ú biß║┐n mß║Ñt ch╞░a (chß╗⌐ng tß╗Å click ─ân, mß╗ƒ popup Microsoft)
                            page.wait_for_timeout(3000)
                            check_still_there = page.evaluate(js_get_rect)
                            if not check_still_there.get("found"):
                                print(f"--- [B╞»ß╗ÜC 4] ─É├ú CLICK THß║¼T th├ánh c├┤ng n├║t Microsoft ß╗ƒ lß║ºn thß╗¡ {i+1}!")
                                success_click = True
                                break
                            else:
                                print(f"--- [B╞»ß╗ÜC 4] Lß║ºn {i+1}: ─É├ú ß║Ñn chuß╗Öt vß║¡t l├╜ nh╞░ng popup ch╞░a tß║»t, thß╗¡ lß║íi...")
                        else:
                            print(f"--- [B╞»ß╗ÜC 4] Lß║ºn {i+1}: Ch╞░a thß║Ñy n├║t Microsoft. C├│ thß╗â do click Log In hß╗Ñt, ─æang thß╗¡ click lß║íi Log In...")
                            try:
                                # T├¼m n├║t bß║▒ng nhiß╗üu c├ích ─æß╗â chß║»c chß║»n kh├┤ng tr╞░ß╗út
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
                        print(f"--- [B╞»ß╗ÜC 4] Lß╗ùi JS lß║ºn {i+1}: {js_err}")
                    
                    page.wait_for_timeout(2000)
                
                if not success_click:
                    # CHß║╢N CHß║áY M├Ö QU├üNG: B├ío lß╗ùi v├á dß╗½ng tiß║┐n tr├¼nh
                    video_tasks[task_id] = {"status": "error", "message": "Lß╗ùi: Qu├í thß╗¥i gian chß╗¥ n├║t Continue with Microsoft."}
                    print("====== [Lß╗ûI] KH├öNG THß╗é ß║ñN N├ÜT MICROSOFT, Dß╗¬NG TIß║╛N TR├îNH TR├üNH CHß║áY M├Ö QU├üNG ======")
                    return
                
                # ─É├ú click th├ánh c├┤ng, chß╗¥ Microsoft Auth xß╗¡ l├╜
                page.wait_for_timeout(6000)
            except Exception as e:
                print(f"\n====== Lß╗ûI B╞»ß╗ÜC 4 ======\n{str(e)}\n========================\n")
                video_tasks[task_id] = {"status": "error", "message": f"Lß╗ùi ß╗ƒ b╞░ß╗¢c ─æ─âng nhß║¡p Microsoft: {str(e)}"}
                return # Ng─ân chß║íy tiß║┐p xuß╗æng c├íc b╞░ß╗¢c tß║ío video

            # ΓöÇΓöÇ B╞»ß╗ÜC 5 & 6: Xß╗¡ l├╜ X├íc nhß║¡n tuß╗òi (nß║┐u c├│) v├á Chß╗¥ ─æ─âng nhß║¡p th├ánh c├┤ng ΓöÇΓöÇ
            video_tasks[task_id] = {"status": "running", "message": "─Éang chß╗¥ ─æ─âng nhß║¡p ho├án tß║Ñt..."}
            try:
                page.wait_for_timeout(4000) # ─Éß╗úi trang load xong sau khi Auth
                
                login_success = False
                for _ in range(15): # Lß║╖p tß╗æi ─æa ~30s
                    # 0. Qu├⌐t xem c├│ bß╗ï b├ío lß╗ùi Limit tß╗½ server higgsfield kh├┤ng
                    try:
                        limit_msg = page.evaluate("""() => {
                            const texts = ['Maximum number of attempts reached', "Couldn't load", 'experiencing high demand'];
                            return texts.find(t => document.body && document.body.innerText.includes(t));
                        }""")
                        if limit_msg:
                            video_tasks[task_id] = {"status": "limit", "message": f"T├ái khoß║ún ─æ├ú bß╗ï Limit: {limit_msg}"}
                            print(f"====== [LIMIT] T├ÇI KHOß║óN Bß╗è GIß╗ÜI Hß║áN: {limit_msg} ======")
                            return
                    except: pass
                    
                    # 1. Qu├⌐t xem c├│ dialog x├íc nhß║¡n tuß╗òi kh├┤ng, nß║┐u c├│ th├¼ click
                    check_age_popup(page)
                    
                    page.wait_for_timeout(1000)
                    
                    # 2. Bß║Ñm v├áo n├║t Avatar bß║▒ng Playwright (nh╞░ ng╞░ß╗¥i thß║¡t) thay v├¼ JS
                    try:
                        # N├║t button c├│ aria-haspopup="menu" v├á chß╗⌐a thß║╗ img.rounded-full
                        avatar_loc = page.locator('button[aria-haspopup="menu"]:has(img.rounded-full)').first
                        if avatar_loc.count() > 0:
                            avatar_loc.click(timeout=2000)
                    except:
                        pass
                        
                    page.wait_for_timeout(1000)
                    
                    # 3. Kiß╗âm tra xem menu Settings c├│ xß╗ò ra kh├┤ng
                    has_settings = page.evaluate("""() => {
                        const allBtns = Array.from(document.querySelectorAll('button, p, div, span'));
                        return allBtns.some(b => b.innerText && (b.innerText.includes('Settings') || b.innerText.includes('C├ái ─æß║╖t')));
                    }""")
                    
                    if has_settings:
                        login_success = True
                        # Click ra ngo├ái ─æß╗â ─æ├│ng menu Settings
                        page.mouse.click(0, 0)
                        page.wait_for_timeout(500)
                        break
                        
                    page.wait_for_timeout(1000)

                if login_success:
                    video_tasks[task_id] = {"status": "running", "message": "Γ£à ─É─âng nhß║¡p th├ánh c├┤ng! ─Éang chuß║⌐n bß╗ï tß║ío video..."}
                else:
                    raise Exception("Kh├┤ng t├¼m thß║Ñy menu Settings, ─æ─âng nhß║¡p c├│ thß╗â ─æ├ú thß║Ñt bß║íi.")
                    
            except Exception as e:
                video_tasks[task_id] = {"status": "error", "message": f"─É─âng nhß║¡p thß║Ñt bß║íi: {e}"}
                try: context.close()
                except: pass
                return
        else:
            video_tasks[task_id] = {"status": "running", "message": "Γ£à ─É├ú ─æ─âng nhß║¡p sß║╡n! ─Éang chuß║⌐n bß╗ï tß║ío video..."}

        page.wait_for_timeout(1500)

        # ─Éß╗Ç PH├ÆNG WEB Tß╗░ V─éNG (LOGOUT)
        if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Microsoft'))"):
            raise Exception("T├ái khoß║ún higgsfield bß╗ï v─âng (Logout) giß╗»a chß╗½ng. Vui l├▓ng tß║»t v├á CHß║áY Lß║áI profile n├áy!")


        # ΓöÇΓöÇ B╞»ß╗ÜC 7.5: Chß╗ìn Model, Duration, Ratio ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        video_tasks[task_id] = {"status": "running", "message": "─Éang chß╗ìn c├ái ─æß║╖t video..."}
        try:
            # Chß╗ìn Model
            if video_model:
                page.locator('button[data-input-engine-actionbar-control-key="video-model"]').click(timeout=500, force=True)
                page.wait_for_timeout(500)
                page.evaluate(f"""(text) => {{
                    const items = Array.from(document.querySelectorAll('div[role="menuitem"], div[role="menuitemradio"], div[role="option"], button'));
                    const item = items.find(el => el.innerText && el.innerText.trim().includes(text));
                    if(item) item.click();
                }}""", video_model)
                page.wait_for_timeout(500)
            
            # Chß╗ìn Duration
            if video_duration:
                page.locator('button[data-input-engine-actionbar-control-key="video-duration"]').click(timeout=500, force=True)
                page.wait_for_timeout(500)
                page.evaluate(f"""(text) => {{
                    const items = Array.from(document.querySelectorAll('div[role="menuitem"], div[role="menuitemradio"], div[role="option"], button'));
                    const item = items.find(el => el.innerText && el.innerText.trim() === text);
                    if(item) item.click();
                }}""", video_duration)
                page.wait_for_timeout(500)
                
            # Chß╗ìn Ratio
            if video_ratio:
                page.locator('button[data-input-engine-actionbar-control-key="video-ratio"]').click(timeout=500, force=True)
                page.wait_for_timeout(500)
                page.evaluate(f"""(text) => {{
                    const items = Array.from(document.querySelectorAll('div[role="menuitem"], div[role="menuitemradio"], div[role="option"], button'));
                    const item = items.find(el => el.innerText && el.innerText.trim() === text);
                    if(item) item.click();
                }}""", video_ratio)
                page.wait_for_timeout(500)
        except Exception as e:
            # ß║¿n print lß╗ùi ─æß╗â tr├ính l├ám ng╞░ß╗¥i d├╣ng hoang mang (do n├║t n├áy l├á cß╗ºa web kh├íc, tr├¬n higgsfield c├│ thß╗â kh├┤ng c├│)
            pass # Bß╗Å qua nß║┐u lß╗ùi, web c├│ thß╗â d├╣ng mß║╖c ─æß╗ïnh

        # ─Éß╗Ç PH├ÆNG WEB Tß╗░ V─éNG (LOGOUT)
        if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Microsoft'))"):
            raise Exception("higgsfield_logout")

        # ΓöÇΓöÇ B╞»ß╗ÜC 8: Upload ß║únh & Video theo giao diß╗çn Mß╗ÜI ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        images_to_upload = []
        videos_to_upload = []
        
        if media_paths:
            for path in media_paths:
                if path and Path(path).exists():
                    if path.lower().endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv')):
                        videos_to_upload.append(path)
                    else:
                        images_to_upload.append(path)

        def handle_media_upload_modal(pg):
            # Xß╗¡ l├╜ modal "Media upload agreement" nß║┐u hiß╗çn ra
            try:
                agree_btn = pg.locator('button:has-text("I agree, continue")')
                if agree_btn.is_visible(timeout=2000):
                    agree_btn.click(timeout=3000)
                    pg.wait_for_timeout(1000)
                    return True
            except: pass
            return False

        def upload_and_select(pg, btn_aria_label, file_paths):
            print(f"--- B?t d?u upload cho {btn_aria_label}, s? lu?ng file: {len(file_paths)}")
            if not file_paths: return
            try:
                # 1. Click v├áo khu vß╗▒c Add media (ß║ónh hoß║╖c Video)
                pg.locator(f'button[aria-label="{btn_aria_label}"]').click(timeout=5000)
                pg.wait_for_timeout(1500)
                handle_media_upload_modal(pg)
                
                # 2. Click n├║t Upload media
                upload_btn = pg.locator('button[aria-label="Upload media"]').last
                if not upload_btn.is_visible():
                    upload_btn = pg.locator('button[aria-label="Upload media"]').last
                
                try:
                    with pg.expect_file_chooser(timeout=3000) as fc_info:
                        upload_btn.click(timeout=5000, force=True)
                    fc_info.value.set_files(file_paths)
                except:
                    # C├│ thß╗â do modal "I agree" hiß╗çn ra thay v├¼ file dialog, thß╗¡ xß╗¡ l├╜
                    print("  -> Intercept file chooser failed. Handling modal...")
                    handle_media_upload_modal(pg)
                    # Thß╗¡ lß║íi
                    with pg.expect_file_chooser(timeout=8000) as fc_info:
                        upload_btn.click(timeout=5000, force=True)
                    fc_info.value.set_files(file_paths)
                    
                # Cß╗░C Kß╗▓ QUAN TRß╗îNG: Ngay sau khi chß╗ìn file Video, popup "Edit reference" sß║╜ hiß╗çn ra ─æß╗â bß║»t Confirm tr╞░ß╗¢c!
                # N├║t Confirm nß║▒m trong popup Edit reference, c├│ cß║Ñu tr├║c <span class="col-start-1 row-start-1">Confirm</span>
                try:
                    confirm_btn = pg.locator('button:has(span.col-start-1.row-start-1:text-is("Confirm"))').last
                    if not confirm_btn.is_visible(timeout=3000):
                        confirm_btn = pg.locator('button:has-text("Confirm")').last
                        
                    if confirm_btn.is_visible(timeout=2000):
                        print("  -> Thß║Ñy n├║t Confirm cß╗ºa Edit reference, tiß║┐n h├ánh bß║Ñm...")
                        confirm_btn.click(timeout=3000, force=True)
                        pg.wait_for_timeout(2000) # ─Éß╗úi popup ─æ├│ng
                except Exception as inner_e:
                    print(f"  -> Kh├┤ng thß║Ñy Confirm modal ngay sau khi upload (hoß║╖c up ß║únh n├¬n kh├┤ng c├│).")
                    
                # 3. Chß╗¥ qu├í tr├¼nh upload xong (Mß║Ñt chß╗» Uploading...)
                try:
                    uploading_indicator = pg.locator('text="Uploading..."')
                    uploading_indicator.wait_for(state="hidden", timeout=60000)
                except: pass
                pg.wait_for_timeout(2000) # ─Éß╗úi th├¬m t├¡ cho list update
                
                # Kiß╗âm tra lß╗ùi Failed to upload media
                if pg.locator('text="Failed to upload media"').is_visible(timeout=1000):
                    print("  -> Cß║óNH B├üO: Bß╗ï lß╗ùi 'Failed to upload media'!")
                    raise Exception("ReloadRequired")
                
                # 4. Chß╗ìn c├íc file vß╗½a upload (Click nh╞░ ng╞░ß╗¥i thß║¡t)
                print(f"  -> ─Éang chß╗ìn {len(file_paths)} file vß╗½a upload...")
                items = pg.locator('div[data-assets-picker-selectable-card="true"]')
                count = items.count()
                
                # Click chß╗ìn N file ─æß║ºu ti├¬n t╞░╞íng ß╗⌐ng sß╗æ file vß╗½a up
                for i in range(min(len(file_paths), count)):
                    try:
                        # Phß║úi r├¬ chuß╗Öt v├á click vß║¡t l├╜
                        box = items.nth(i).bounding_box()
                        if box:
                            pg.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                            pg.wait_for_timeout(200)
                            pg.mouse.down()
                            pg.wait_for_timeout(100)
                            pg.mouse.up()
                        else:
                            items.nth(i).click(timeout=3000, force=True)
                        pg.wait_for_timeout(1500)
                    except: pass
                    
                # 5. Tß║»t modal upload bß║▒ng n├║t X (nß║┐u c├│, th╞░ß╗¥ng d├ánh cho tß║úi ß║únh)
                try:
                    close_btn = pg.locator('button[aria-label="Close"], button svg.lucide-x').first
                    if close_btn.is_visible(timeout=2000):
                        print("  -> ─É├│ng bß║úng upload media (bß║▒ng n├║t X)...")
                        close_btn.click()
                        pg.wait_for_timeout(1000)
                except: pass
                
            except Exception as e:
                print(f"Lß╗ùi upload {btn_aria_label}: {e}")

        # Upload ß║ónh v├á Video (C├│ c╞í chß║┐ Retry nß║┐u bß╗ï lß╗ùi Failed to upload media)
        for attempt in range(3):
            try:
                if images_to_upload:
                    try:
                        objects_tab = page.locator('button[role="tab"]:has-text("Objects swap")').first
                        if objects_tab.is_visible(timeout=2000):
                            objects_tab.click(timeout=3000)
                            page.wait_for_timeout(1000)
                    except: pass
                    print(f"=== Bß║«T ─Éß║ªU UPLOAD ß║óNH ({len(images_to_upload)} file) (Lß║ºn {attempt+1}) ===")
                    video_tasks[task_id] = {"status": "running", "message": f"─Éang tß║úi {len(images_to_upload)} ß║únh l├¬n..."}
                    upload_and_select(page, "Add reference images", images_to_upload)
                    
                    # Bß║Ñm ra ngo├ái (─æß╗â ─æ├│ng popup nß║┐u c├│, gi├║p hiß╗çn n├║t tß║úi video)
                    try:
                        page.mouse.click(10, 10)
                        page.wait_for_timeout(1000)
                    except: pass
                    
                if videos_to_upload:
                    if images_to_upload:
                        # Nß║┐u c├│ ß║únh, ta ─æang ß╗ƒ tab Objects swap -> n├║t upload video l├á "Add a reference video to edit"
                        video_btn_label = "Add a reference video to edit"
                    else:
                        # Nß║┐u kh├┤ng c├│ ß║únh, vß╗ü tab Motion transfer -> n├║t upload video l├á "Add a reference video to extract motion"
                        try:
                            motion_tab = page.locator('button[role="tab"]:has-text("Motion transfer")').first
                            if motion_tab.is_visible(timeout=2000):
                                motion_tab.click(timeout=3000)
                                page.wait_for_timeout(1000)
                        except: pass
                        video_btn_label = "Add a reference video to extract motion"
                        
                    print(f"=== Bß║«T ─Éß║ªU UPLOAD VIDEO ({len(videos_to_upload)} file) (Lß║ºn {attempt+1}) ===")
                    video_tasks[task_id] = {"status": "running", "message": f"─Éang tß║úi {len(videos_to_upload)} video l├¬n..."}
                    upload_and_select(page, video_btn_label, videos_to_upload)
                break # Th├ánh c├┤ng th├¼ tho├ít loop
            except Exception as e:
                if "ReloadRequired" in str(e):
                    print("  -> ─Éang tß║úi lß║íi trang ─æß╗â l├ám lß║íi tß╗½ ─æß║ºu...")
                    video_tasks[task_id] = {"status": "running", "message": "Video bß╗ï lß╗ùi, ─æang tß║úi lß║íi trang ─æß╗â thß╗¡ lß║íi..."}
                    page.reload()
                    page.wait_for_load_state('networkidle')
                    page.wait_for_timeout(3000)
                    if attempt == 2:
                        raise Exception("─É├ú thß╗¡ tß║úi lß║íi trang 3 lß║ºn nh╞░ng upload media vß║½n b├ío Failed!")
                    continue
                raise e

        # ─Éß╗Ç PH├ÆNG WEB Tß╗░ V─éNG (LOGOUT)
        if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Microsoft'))"):
            raise Exception("T├ái khoß║ún higgsfield bß╗ï v─âng (Logout) giß╗»a chß╗½ng. Vui l├▓ng tß║»t v├á CHß║áY Lß║áI profile n├áy!")
            
        check_age_popup(page)
        # ΓöÇΓöÇ B╞»ß╗ÜC 9: Bß║¡t c├┤ng tß║»c Prompt v├á ─æiß╗ün ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        if prompt:
            print(f"=== ─ÉIß╗ÇN PROMPT: {prompt[:30]}... ===")
            video_tasks[task_id] = {"status": "running", "message": "─Éang nhß║¡p prompt..."}
            try:
                # Bß║¡t c├┤ng tß║»c "Prompt"
                prompt_toggle = page.locator('span[aria-label="Toggle prompt"]')
                if prompt_toggle.is_visible(timeout=3000):
                    if prompt_toggle.get_attribute("aria-checked") == "false":
                        print("  -> Bß║¡t c├┤ng tß║»c Prompt")
                        prompt_toggle.click(timeout=3000)
                        page.wait_for_timeout(1000)
                
                # ─Éiß╗ün prompt
                prompt_input = page.locator('div[aria-label="Prompt"][contenteditable="true"]')
                if prompt_input.is_visible(timeout=3000):
                    prompt_input.fill("")
                    page.wait_for_timeout(500)
                    # D├╣ng page.evaluate ─æß╗â bypass react 
                    page.evaluate("(text) => { document.querySelector('div[aria-label=\"Prompt\"][contenteditable=\"true\"]').textContent = text; }", prompt)
                    prompt_input.type(" ") # k├¡ch hoß║ít sß╗▒ kiß╗çn input
                    page.wait_for_timeout(500)
            except Exception as e:
                print(f"Lß╗ùi nhß║¡p prompt: {e}")

        # ΓöÇΓöÇ B╞»ß╗ÜC 10: Bß║¡t c├┤ng tß║»c "Use free gens" v├á nhß║Ñn Generate ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        print("=== Bß║¼T FREE GENS V├Ç NHß║ñN GENERATE ===")
        video_tasks[task_id] = {"status": "running", "message": "─Éang nhß║Ñn n├║t Generate..."}
        try:
            # Bß║¡t c├┤ng tß║»c Use free gens
            free_gens = page.locator('button[aria-label="Use free gens"]')
            if free_gens.is_visible(timeout=2000):
                if free_gens.get_attribute("aria-checked") == "false":
                    free_gens.click(timeout=3000)
                    page.wait_for_timeout(1000)
            
            # Nhß║Ñn n├║t Generate
            generate_btn = page.locator('button:has-text("Generate")').last
            if generate_btn.is_visible(timeout=3000):
                print("  -> ─É├ú thß║Ñy n├║t Generate, tiß║┐n h├ánh click!")
                generate_btn.click(timeout=3000)
                page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Lß╗ùi nhß║Ñn Generate: {e}")


        video_tasks[task_id] = {"status": "running", "message": "Γ£à ─É├ú gß╗¡i y├¬u cß║ºu! ─Éang chß╗¥ higgsfield.ai tß║ío video..."}

        # ΓöÇΓöÇ B╞»ß╗ÜC 11: ─Éß╗úi video xuß║Ñt hiß╗çn (tß╗æi ─æa 10 ph├║t) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        video_url = None
        video_urls = []
        for i in range(600):
            page.wait_for_timeout(1000)
            
            # Cß║¡p nhß║¡t log chat
            sync_chat(page)
            
            # CH├Ü ├¥: ─Éß╗ü ph├▓ng web tß╗▒ v─âng acc giß╗»a chß╗½ng (nh╞░ l├║c ─æang chß╗¥ video)
            if "from_logout=1" in page.url:
                raise Exception("higgsfield_logout")
                
            check_age_popup(page)
                
            if video_tasks.get(task_id, {}).get("force_stop"):
                print(f"--- Task {task_id} bß╗ï force_stop. Tho├ít v├▓ng lß║╖p chß╗¥ video.")
                break
            
            try:
                # Qu├⌐t xem c├│ popup Log In bß║Ñt ngß╗¥ hiß╗çn l├¬n kh├┤ng
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
                    return btns.some(b => b.innerText && b.innerText.includes('Continue with Microsoft'));
                }""")
                if has_login_modal:
                    raise Exception("higgsfield_logout")
            except Exception as eval_e:
                if "higgsfield_logout" in str(eval_e):
                    raise
            
            try:
                # Cuß╗Ön xuß╗æng cuß╗æi v├á Hover ─æß╗â ├⌐p higgsfield tß║úi thß║╗ video (Lazy load)
                page.evaluate("""() => {
                    // 1. Cuß╗Ön m├án h├¼nh xuß╗æng cuß╗æi c├╣ng
                    const scrollers = document.querySelectorAll('.v_list_row, .container-enLQFx, .block-video-MzfWVN, [data-message-id]');
                    if (scrollers.length > 0) {
                        scrollers[scrollers.length - 1].scrollIntoView({behavior: 'smooth', block: 'end'});
                    }
                    
                    // 2. Hover v├áo tß║Ñt cß║ú c├íc v├╣ng c├│ khß║ú n─âng chß╗⌐a video
                    const targets = document.querySelectorAll('.v_list_row, .block-video-MzfWVN, .image-box-grid-EYaIcP, .video-player-wrapper-IZ7Zoq, .xgplayer');
                    targets.forEach(t => {
                        try { t.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})); } catch(e){}
                    });
                    
                    // 3. Click thß║│ng v├áo n├║t Play hoß║╖c ß║únh ─æß║íi diß╗çn ─æß╗â ├ëP n├│ tß║úi luß╗ông video (Bß║»t buß╗Öc phß║úi Play mß╗¢i lß║Ñy ─æ╞░ß╗úc link)
                    const playBtns = document.querySelectorAll('.play-icon-gWzeeV, .xg-icon-play, [aria-label="play"], .video-hover-button-group-container-mh06XY, .image-box-grid-EYaIcP img');
                    playBtns.forEach(b => {
                        try { 
                            b.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})); 
                            b.click(); // Phß║úi CLICK th├¼ xgplayer mß╗¢i b╞ím link v├áo thß║╗ <video>
                        } catch(e){}
                    });
                }""")
                page.wait_for_timeout(1000) # Chß╗¥ 1 gi├óy ─æß╗â n├│ nß║íp link sau khi click
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
            video_tasks[task_id]["message"] = f"─Éang chß╗¥ higgsfield.ai tß║ío video... {mins:02d}:{secs:02d}"

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
                        # Dß╗░ PH├ÆNG 3 Lß╗ÜP ─Éß╗é Tß║óI VIDEO TH├ÇNH C├öNG 100%
                        success = False
                        err_msg = ""
                        
                        # Lß╗¢p 1: Tß║úi bß║▒ng Playwright API (th├¬m User-Agent v├á Referer ─æß╗â tr├ính bß╗ï CDN block g├óy lß╗ùi ETIMEDOUT)
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
                            
                        # Lß╗¢p 2: Nß║┐u Lß╗¢p 1 thß║Ñt bß║íi (bß╗ï block kß║┐t nß╗æi), tß║úi trß╗▒c tiß║┐p bß║▒ng JS trong l├▓ng Page
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
                                err_msg = f"JS Fetch Lß╗ùi: {e}"
                                
                        # Lß╗¢p 3: Ph╞░╞íng ├ín cuß╗æi c├╣ng, bß║»n sang tab mß╗¢i ─æß╗â ├⌐p tr├¼nh duyß╗çt tß║úi
                        if not success:
                            try:
                                dl_page = context.new_page()
                                dl_page.goto(video_url, timeout=30000)
                                dl_page.wait_for_timeout(5000)
                                # File tß║úi vß╗ü sß║╜ r╞íi v├áo _on_download event cß╗ºa Playwright, nh╞░ng ta kh├┤ng biß║┐t t├¬n file. 
                                # C├ích tß╗æt nhß║Ñt l├á b├ío lß╗ùi ─æß╗â retry nß║┐u 2 lß╗¢p tr├¬n thß║Ñt bß║íi.
                                dl_page.close()
                                raise Exception(f"Tß║úi video thß║Ñt bß║íi sau 3 c├ích. Lß╗ùi gß╗æc: {err_msg}")
                            except Exception as e:
                                raise e
                               
                    # Phß║ºn n├áy chß║íy chung cho cß║ú 2 tr╞░ß╗¥ng hß╗úp tß║úi th├ánh c├┤ng (blob hoß║╖c http)
                    if tg_enabled:
                        _send_video_to_telegram(str(out_file), tg_token, tg_chat_id)
                    all_urls = [f"/api/video/download/{task_id}?path={urllib.parse.quote(str(out_file))}"]
                    all_result_urls.extend(all_urls)
                video_tasks[task_id]["result_urls"] = all_result_urls
                video_tasks[task_id]["message"] = f"≡ƒÄë {len(video_urls)} Video tß║ío xong! ─Éang hiß╗ân thß╗ï l├¬n Tool..."
                page.wait_for_timeout(3000)
            except Exception as e:
                video_tasks[task_id] = {"status": "error", "message": f"Tß║ío th├ánh c├┤ng nh╞░ng tß║úi video thß║Ñt bß║íi: {e}"}
        else:
            if video_tasks.get(task_id, {}).get("force_stop"):
                video_tasks[task_id]["message"] = "─É├ú hß╗ºy tiß║┐n tr├¼nh!"
                # Kh├┤ng set status = done ß╗ƒ ─æ├óy, ─æß╗â UI tiß║┐p tß╗Ñc cß║¡p nhß║¡t tiß║┐n tr├¼nh x├│a acc
            else:
                video_tasks[task_id] = {"status": "error", "message": "Timeout 10 ph├║t: Video kh├┤ng xuß║Ñt hiß╗çn tr├¬n higgsfield.ai."}

        # ΓöÇΓöÇ B╞»ß╗ÜC 12: X├│a t├ái khoß║ún (Delete Account) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        video_tasks[task_id]["message"] = video_tasks[task_id].get("message", "") + "\n─Éang hß╗ºy hoß║ít ─æß╗Öng v├á X├│a t├ái khoß║ún..."
        
        # Tho├ít khß╗Åi chß║┐ ─æß╗Ö xem video (Modal/Fullscreen) do l├║c n├úy ta ─æ├ú click Play
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            page.keyboard.press("Escape")
            # Click chuß╗Öt ra mß╗Öt g├│c trß╗æng ─æß╗â ─æß║úm bß║úo c├íc menu/modal ─æang mß╗ƒ sß║╜ bß╗ï ─æ├│ng
            page.mouse.click(10, 10)
            page.wait_for_timeout(1000)
        except: pass
        
        try:
            # Nß║┐u bß╗ï force stop, tß║úi lß║íi trang ─æß╗â Hß╗ªY NGAY Lß║¼P Tß╗¿C c├íc file ─æang upload
            if video_tasks.get(task_id, {}).get("force_stop"):
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                
            # 1. Bß║Ñm Avatar (Sß╗¡ dß╗Ñng locator ch├¡nh x├íc theo DOM cß╗ºa higgsfield)
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
                            return texts.includes(text) || texts.some(t => text === t + ' >' || text === t + ' Γ¥»' || text === t + ' πÇë') || texts.some(t => text.includes(t) && text.length <= t.length + 5);
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
                        # Thß╗▒c hiß╗çn click bß║▒ng h├ám click chuß║⌐n
                        page.mouse.click(tx, ty)
                        return True
                    page.wait_for_timeout(1000) # ─Éß╗úi l├óu h╞ín x├¡u giß╗»a c├íc lß║ºn thß╗¡
                return False

            # 2. Bß║Ñm Settings / C├ái ─æß║╖t
            page.wait_for_timeout(2000)
            if not click_by_coords(['Settings', 'C├ái ─æß║╖t']): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Settings / C├ái ─æß║╖t")
            
            # 3. Bß║Ñm Account / T├ái khoß║ún
            page.wait_for_timeout(2000)
            if not click_by_coords(['Account', 'T├ái khoß║ún']): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Account / T├ái khoß║ún")
            
            # 4. Bß║Ñm Delete Account / X├│a t├ái khoß║ún
            page.wait_for_timeout(2000)
            if not click_by_coords(['Delete Account', 'X├│a t├ái khoß║ún']): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Delete Account / X├│a t├ái khoß║ún")
            
            # 5. Bß║Ñm Delete / X├│a
            page.wait_for_timeout(2000)
            if not click_by_coords(['Delete', 'X├│a'], 'button'): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Delete / X├│a (Lß║ºn 1)")
            
            # 5.5. Bß║Ñm X├│a trong modal x├íc nhß║¡n nhß╗Å (Hß╗ºy / X├│a)
            page.wait_for_timeout(2000)
            print("[XoaNgay] ─Éang bß║Ñm n├║t X├│a m├áu ─æß╗Å trong modal x├íc nhß║¡n...")
            try:
                clicked_modal = page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    // T├¼m c├íc n├║t c├│ chß╗» X├│a hoß║╖c Delete ch├¡nh x├íc
                    const deleteBtns = btns.filter(b => b.innerText.trim() === 'X├│a' || b.innerText.trim() === 'Delete');
                    if (deleteBtns.length > 0) {
                        // Click n├║t cuß╗æi c├╣ng (th╞░ß╗¥ng l├á n├║t trong modal vß╗½a hiß╗çn ra)
                        deleteBtns[deleteBtns.length - 1].click();
                        return true;
                    }
                    return false;
                }""")
                if clicked_modal:
                    print("[XoaNgay] ─É├ú click n├║t X├│a trong modal th├ánh c├┤ng!")
                else:
                    print("[XoaNgay] Kh├┤ng t├¼m thß║Ñy n├║t X├│a trong modal bß║▒ng JS, thß╗¡ Playwright...")
                    page.locator('button:has-text("X├│a"), button:has-text("Delete")').last.click(timeout=2000, force=True)
            except Exception as e:
                print(f"[XoaNgay] Lß╗ùi click n├║t X├│a trong modal: {e}")
            
            # 5.6. Bß║Ñm X├íc nhß║¡n (nß║┐u c├│ popup X├íc nhß║¡n tuß╗òi)
            page.wait_for_timeout(2000)
            try:
                clicked_confirm = page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const confirmBtns = btns.filter(b => b.innerText.trim() === 'X├íc nhß║¡n' || b.innerText.trim() === 'Confirm');
                    if (confirmBtns.length > 0) {
                        confirmBtns[confirmBtns.length - 1].click();
                        return true;
                    }
                    return false;
                }""")
                if clicked_confirm:
                    print("[XoaNgay] ─É├ú click n├║t X├íc nhß║¡n tuß╗òi!")
            except Exception as e:
                pass
            
            # 6. Bß║Ñm X├│a ngay - D├╣ng kß╗ïch bß║ún ElementFromPoint si├¬u viß╗çt cß╗ºa User
            print("[XoaNgay] ─Éang bß║»t ─æß║ºu bß║Ñm X├│a ngay bß║▒ng kß╗ïch bß║ún ElementFromPoint...")
            
            success = False
            for attempt in range(6):
                page.wait_for_timeout(2000)
                frames_list = page.frames
                print(f"[XoaNgay] Attempt {attempt+1}: B╞ím m├ú JS v├áo tß║Ñt cß║ú {len(frames_list)} frames (nh╞░ Extension)...")
                
                js_code = """
                    async () => {
                      const logo = document.querySelector("img.icon-ieQdCp");
                      if (!logo) return "KhongThayLogo";

                      // Vß╗ï tr├¡: d╞░ß╗¢i logo 30px
                      const r = logo.getBoundingClientRect();
                      const size = 50;
                      const x = r.left + (r.width - size) / 2;
                      const y = r.bottom + 30;

                      // Tß║ío highlight
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
                      console.log("─É├ú highlight. Sß║╜ click sau 1.5 gi├óy.");

                      await new Promise(resolve => setTimeout(resolve, 1500));

                      // ß║¿n overlay ─æß╗â lß║Ñy ch├¡nh phß║ºn tß╗¡ ph├¡a d╞░ß╗¢i t├óm ├┤
                      square.style.display = "none";
                      const target = document.elementFromPoint(x + size / 2, y + size / 2);
                      square.remove();

                      if (!target) return "KhongCoPhanTu";

                      const clickable = target.closest(
                        ".confirm-button-ZuDQ59, [role='button'], button, a, [onclick]"
                      ) || target;

                      console.log("─Éang click phß║ºn tß╗¡:", clickable);
                      clickable.click();
                      
                      return "DaClick";
                    }
                """
                
                clicked_this_round = False
                for f in frames_list:
                    try:
                        result = f.evaluate(js_code)
                        if result == "DaClick":
                            print(f"     -> [Tuyß╗çt vß╗¥i] ─É├ú vß║╜ highlight v├á CLICK TR├ÜNG ─É├ìCH trong frame: {f.name or f.url}")
                            clicked_this_round = True
                            break
                    except Exception:
                        # Frame c├│ thß╗â bß╗ï huß╗╖ hoß║╖c lß╗ùi kß║┐t nß╗æi, bß╗Å qua
                        pass
                        
                if clicked_this_round:
                    page.wait_for_timeout(3000)
                    # Kiß╗âm tra xem logo c├│ biß║┐n mß║Ñt khß╗Åi tß║Ñt cß║ú frames ch╞░a
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
                        print("[XoaNgay] X├íc nhß║¡n cß╗¡a sß╗ò X├│a ngay ─æ├ú ─æ├│ng -> TH├ÇNH C├öNG!")
                        break
                    else:
                        print("[XoaNgay] Vß║½n c├▓n thß║Ñy Logo, click ch╞░a ─ân hoß║╖c mß║íng lag...")
            
            if not success:
                print("[XoaNgay] Cß║únh b├ío: V╞░ß╗út qu├í sß╗æ lß║ºn thß╗¡ click X├│a ngay!")
            
            page.wait_for_timeout(2000)


            
            # ─Éß╗úi web load v├á kiß╗âm tra trß║íng th├íi ─É─âng xuß║Ñt (chß╗⌐ng tß╗Å ─æ├ú x├│a th├ánh c├┤ng)
            try:
                page.wait_for_timeout(3000)
                # Kiß╗âm tra xem c├│ xuß║Ñt hiß╗çn n├║t "─É─âng nhß║¡p" (Login) hoß║╖c c├│ chuyß╗ân h╞░ß╗¢ng URL from_logout kh├┤ng
                page.evaluate("""() => {
                    const all = document.body.innerText;
                    const hasLoginBtn = all.includes('─É─âng nhß║¡p') || all.includes('Log in') || all.includes('Sign in');
                    const isLoggedOutUrl = window.location.href.includes('from_logout');
                    
                    if (!hasLoginBtn && !isLoggedOutUrl && !all.includes('Account deleted') && !all.includes('─æ├ú x├│a') && !all.includes('deleted')) {
                        throw new Error('Ch╞░a thß║Ñy dß║Ñu hiß╗çu ─æ─âng xuß║Ñt/x├│a t├ái khoß║ún');
                    }
                }""")
                page.wait_for_timeout(1000) # Th├¬m 1 gi├óy cho chß║»c c├║ sau khi th├┤ng b├ío hiß╗çn
            except Exception as e:
                print(f"Ch╞░a thß║Ñy dß║Ñu hiß╗çu x├│a th├ánh c├┤ng, ─æß╗úi th├¬m 5s: {e}")
                page.wait_for_timeout(5000)
                # Lß║ºn 2 bß║»t buß╗Öc phß║úi c├│, nß║┐u kh├┤ng c├│ qu─âng lß╗ùi ─æß╗â ra catch
                page.evaluate("""() => {
                    const all = document.body.innerText;
                    const hasLoginBtn = all.includes('─É─âng nhß║¡p') || all.includes('Log in') || all.includes('Sign in');
                    const isLoggedOutUrl = window.location.href.includes('from_logout');
                    
                    if (!hasLoginBtn && !isLoggedOutUrl && !all.includes('Account deleted') && !all.includes('─æ├ú x├│a') && !all.includes('deleted')) {
                        throw new Error('Timeout: Kh├┤ng thß║Ñy th├┤ng b├ío hoß║╖c dß║Ñu hiß╗çu x├│a th├ánh c├┤ng (ch╞░a thß║Ñy n├║t ─É─âng nhß║¡p)!');
                    }
                }""")
            video_tasks[task_id]["message"] = video_tasks[task_id]["message"].replace("─Éang hß╗ºy hoß║ít ─æß╗Öng v├á X├│a t├ái khoß║ún...", "─É├ú x├│a Account th├ánh c├┤ng!")
        except Exception as del_err:
            print(f"Lß╗ùi khi x├│a account: {del_err}")
            video_tasks[task_id]["message"] = video_tasks[task_id]["message"].replace("─Éang hß╗ºy hoß║ít ─æß╗Öng v├á X├│a t├ái khoß║ún...", "Gß║╖p lß╗ùi khi x├│a Account!")
            
        # ─É├ính dß║Ñu done ß╗ƒ b╞░ß╗¢c cuß╗æi c├╣ng
        video_tasks[task_id]["status"] = "done"

        try: context.close()
        except: pass

    except Exception as e:
        # Bß║»t buß╗Öc ─æ├│ng tr├¼nh duyß╗çt ngay lß║¡p tß╗⌐c nß║┐u c├│ lß╗ùi hoß║╖c v─âng ─æß╗â retry c├│ thß╗â lß║Ñy FP mß╗¢i
        try: context.close()
        except: pass
    
        if "higgsfield_logout" in str(e):
            print(f"--- Bß╗ï v─âng! B├ío cho frontend tß╗▒ ─æß╗Öng thß╗¡ lß║íi task {task_id}...")
            video_tasks[task_id] = {
                "status": "higgsfield_logout", 
                "message": "Bß╗ï v─âng khß╗Åi t├ái khoß║ún, ─æang tß╗▒ ─æß╗Öng thß╗¡ lß║íi bß║▒ng v├ón tay (Fingerprint) Chrome ho├án to├án mß╗¢i..."
            }
            return
        video_tasks[task_id] = {"status": "error", "message": f"Lß╗ùi hß╗ç thß╗æng: {e}"}

    finally:
        # Tß╗▒ ─æß╗Öng x├│a ß║únh upload sau khi task xong ─æß╗â tiß║┐t kiß╗çm dung l╞░ß╗úng
        # Nß║┐u ─æang b├ío frontend retry th├¼ KH├öNG x├│a ß║únh
        if video_tasks.get(task_id, {}).get("status") != "higgsfield_logout":
            media_paths_cleanup = media_paths if 'media_paths' in locals() else []
            for img_path in media_paths_cleanup:
                if img_path:
                    try:
                        p_file = Path(img_path)
                        if p_file.exists():
                            p_file.unlink()
                    except: pass

        if 'context' in locals() and context is not None:
            try: context.close()
            except: pass
        if 'p' in locals() and p is not None:
            try: p.stop()
            except: pass





from typing import List, Optional

@app.post("/api/video/create")
async def create_video(request: Request):
    try:
        form = await request.form()
    except Exception as e:
        return JSONResponse(status_code=400, content={"message": f"Lß╗ùi xß╗¡ l├╜ file upload: {e}", "detail": str(e)})

    prompt = form.get("prompt")
    if not prompt:
        return JSONResponse(status_code=400, content={"message": "Thiß║┐u prompt!"})

    profile_id = form.get("profile_id", "")
    images = form.getlist("images") if "images" in form else []
    
    upload_video = form.get("upload_video")
    if isinstance(upload_video, str): upload_video = None
    
    video_duration = form.get("video_duration", "")
    video_ratio = form.get("video_ratio", "")
    save_path = form.get("save_path", "")
    is_headless = form.get("is_headless", "false")
    enable_ext = form.get("enable_ext", "false")
    enable_ext_btn2 = form.get("enable_ext_btn2", "false")
    telegram_enabled = form.get("telegram_enabled", "false")
    telegram_token = form.get("telegram_token", "")
    telegram_chat_id = form.get("telegram_chat_id", "")

    # Lß║Ñy danh s├ích c├íc profile ─æang bß║¡n
    used_profiles = set()
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            used_profiles.add(task.get("params", {}).get("profile_id"))
    for p in list_running():
        used_profiles.add(p["id"])

    if not profile_id:
        # Tß╗▒ ─æß╗Öng g├ín profile rß║únh
        all_profiles = manager.list_profiles()
        free_profiles = [p for p in all_profiles if p.id not in used_profiles]
        if not free_profiles:
            return JSONResponse(status_code=400, content={"message": "Kh├┤ng c├▓n Profile n├áo trß╗æng. Vui l├▓ng tß║ío th├¬m Profile hoß║╖c chß╗¥!"})
        profile_id = free_profiles[0].id
    else:
        # Kiß╗âm tra xem profile ─æ╞░ß╗úc chß╗ìn c├│ ─æang bß║¡n kh├┤ng
        if profile_id in used_profiles:
            return JSONResponse(status_code=400, content={"message": "Profile n├áy ─æang bß║¡n (─æang mß╗ƒ hoß║╖c ─æang tß║ío video kh├íc). Vui l├▓ng chß╗ìn profile kh├íc!"})

    headless_bool = (is_headless.lower() == "true")
    task_id = uuid_module.uuid4().hex[:10]
    
    # Save uploaded images
    upload_dir = Path(BASE_DIR) / "data" / "uploads"
    upload_dir.mkdir(exist_ok=True)
    
    img1_path = ""
    img2_path = ""
    saved_paths = []
    
    if images:
        for idx, img in enumerate(images):
            if img and img.filename:
                ext = Path(img.filename).suffix
                if not ext: ext = ".png"
                path = str(upload_dir / f"{task_id}_img{idx}{ext}")
                with open(path, "wb") as f:
                    f.write(await img.read())
                saved_paths.append(path)
                
    if upload_video and upload_video.filename:
        ext = Path(upload_video.filename).suffix
        if not ext: ext = ".mp4"
        path = str(upload_dir / f"{task_id}_vid{ext}")
        with open(path, "wb") as f:
            f.write(await upload_video.read())
        saved_paths.append(path)
        
    img1_path = saved_paths[0] if len(saved_paths) > 0 else ""
    img2_path = saved_paths[1] if len(saved_paths) > 1 else ""

    video_tasks[task_id] = {
        "status": "pending", 
        "message": "─Éang chuß║⌐n bß╗ï...",
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
            "tg_chat_id": telegram_chat_id
        }
    }
    
    t = threading.Thread(target=run_video_automation, args=(task_id, prompt, saved_paths, profile_id, save_path, headless_bool, (enable_ext.lower() == "true"), (enable_ext_btn2.lower() == "true"), (telegram_enabled.lower() == "true"), telegram_token, telegram_chat_id), daemon=True)
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
    video_tasks[task_id]["message"] = "─Éang thß╗¡ lß║íi..."
    video_tasks[task_id].pop("force_stop", None) # X├│a cß╗¥ force_stop nß║┐u c├│    media_paths = p.get("media_paths", [])
    if not media_paths:
        if p.get("img1_path"): media_paths.append(p["img1_path"])
        if p.get("img2_path"): media_paths.append(p["img2_path"])

    t = threading.Thread(target=run_video_automation, args=(task_id, p["prompt"], media_paths, p.get("profile_id"), p.get("save_path"), p.get("is_headless", False), p.get("enable_ext", False), p.get("enable_ext_btn2", False), p.get("tg_enabled", False), p.get("tg_token", ""), p.get("tg_chat_id", "")), daemon=True)
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
    """Trß║ú vß╗ü ß║únh debug screenshot n├║t X├│a ngay ─æ├ú highlight"""
    from fastapi.responses import FileResponse as FR
    task = video_tasks.get(task_id, {})
    ss_path = task.get("debug_screenshot")
    if ss_path and Path(ss_path).exists():
        return FR(ss_path, media_type="image/png")
    # T├¼m file debug tß╗▒ ─æß╗Öng
    ss_file = Path(BASE_DIR) / "data" / "debug_screenshots" / f"xoa_ngay_{task_id}.png"
    if ss_file.exists():
        return FR(str(ss_file), media_type="image/png")
    raise HTTPException(404, "Screenshot ch╞░a sß║╡n s├áng hoß║╖c ch╞░a ─æ╞░ß╗úc chß╗Ñp")

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
        
    video_tasks[task_id] = {"status": "running", "message": "─Éang mß╗ƒ tr├¼nh duyß╗çt..."}
    try:
        with pw_lock:
            p = sync_playwright().start()
        if True:
            browser = None
            context = None
            
            # ╞»u ti├¬n kß║┐t nß╗æi qua CDP nß║┐u profile ─æang ─æ╞░ß╗úc mß╗ƒ (N├║t 'Mß╗ƒ Chrome' ─æ├ú ─æ╞░ß╗úc bß║Ñm)
            port_file = Path(profile.user_data_dir) / "cdp_port.txt"
            if port_file.exists():
                try:
                    port = int(port_file.read_text().strip())
                    browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
                    context = browser.contexts[0]
                except:
                    pass
            
            # Nß║┐u kh├┤ng thß╗â connect CDP th├¼ mß╗ƒ tr├¼nh duyß╗çt mß╗¢i
            if not context:
                context = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=False, is_headless=False)
            
            # T├¼m tab higgsfield.ai ─æ├ú mß╗ƒ sß║╡n, nß║┐u kh├┤ng c├│ th├¼ lß║Ñy tab ─æß║ºu ti├¬n
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
                    
            # Playwright khi connect CDP th╞░ß╗¥ng tß║ío ra tab 'about:blank' r├íc -> ─æ├│ng n├│ lß║íi
            for pg in context.pages:
                if pg != page:
                    try: pg.close()
                    except: pass
            
            try: page.bring_to_front()
            except: pass
                
            page.goto("https://higgsfield.ai/chat", timeout=60000)
            page.wait_for_timeout(3000)
            
            # Kiß╗âm tra ─æ─âng nhß║¡p
            avatar_btn = page.locator("button[aria-haspopup='menu']").filter(has=page.locator("img.rounded-full"))
            if not avatar_btn.count():
                video_tasks[task_id] = {"status": "error", "message": "Bß║ín ch╞░a ─æ─âng nhß║¡p higgsfield tr├¬n Profile n├áy! Vui l├▓ng Mß╗ƒ Chrome v├á ─æ─âng nhß║¡p tr╞░ß╗¢c."}
                try: context.close()
                except: pass
                return
                
            video_tasks[task_id]["message"] = "─Éang tiß║┐n h├ánh X├│a t├ái khoß║ún..."
            
            # 1. Bß║Ñm Avatar
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
                            return texts.includes(text) || texts.some(t => text === t + ' >' || text === t + ' Γ¥»' || text === t + ' πÇë') || texts.some(t => text.includes(t) && text.length <= t.length + 5);
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
                        # Thß╗▒c hiß╗çn click bß║▒ng h├ám click chuß║⌐n
                        page.mouse.click(tx, ty)
                        return True
                    page.wait_for_timeout(1000) # ─Éß╗úi l├óu h╞ín x├¡u giß╗»a c├íc lß║ºn thß╗¡
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

            # 2. Bß║Ñm Settings / C├ái ─æß║╖t
            page.wait_for_timeout(2000)
            if not click_by_coords(['Settings', 'C├ái ─æß║╖t']): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Settings / C├ái ─æß║╖t")
            
            # 3. Bß║Ñm Account / T├ái khoß║ún
            page.wait_for_timeout(2000)
            if not click_by_coords(['Account', 'T├ái khoß║ún']): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Account / T├ái khoß║ún")
            
            # 4. Bß║Ñm Delete Account / X├│a t├ái khoß║ún
            page.wait_for_timeout(2000)
            if not click_by_coords(['Delete Account', 'X├│a t├ái khoß║ún']): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Delete Account / X├│a t├ái khoß║ún")
            
            # 5. Bß║Ñm Delete / X├│a
            page.wait_for_timeout(2000)
            if not click_by_coords(['Delete', 'X├│a'], 'button'): raise Exception("Kh├┤ng t├¼m thß║Ñy n├║t Delete / X├│a")
            
            # 5.5. Bß║Ñm X├│a trong modal x├íc nhß║¡n nhß╗Å (Hß╗ºy / X├│a)
            page.wait_for_timeout(2000)
            print("[XoaNgay] ─Éang bß║Ñm n├║t X├│a m├áu ─æß╗Å trong modal x├íc nhß║¡n...")
            try:
                clicked_modal = page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    // T├¼m c├íc n├║t c├│ chß╗» X├│a hoß║╖c Delete ch├¡nh x├íc
                    const deleteBtns = btns.filter(b => b.innerText.trim() === 'X├│a' || b.innerText.trim() === 'Delete');
                    if (deleteBtns.length > 0) {
                        // Click n├║t cuß╗æi c├╣ng (th╞░ß╗¥ng l├á n├║t trong modal vß╗½a hiß╗çn ra)
                        deleteBtns[deleteBtns.length - 1].click();
                        return true;
                    }
                    return false;
                }""")
                if clicked_modal:
                    print("[XoaNgay] ─É├ú click n├║t X├│a trong modal th├ánh c├┤ng!")
                else:
                    print("[XoaNgay] Kh├┤ng t├¼m thß║Ñy n├║t X├│a trong modal bß║▒ng JS, thß╗¡ Playwright...")
                    page.locator('button:has-text("X├│a"), button:has-text("Delete")').last.click(timeout=2000, force=True)
            except Exception as e:
                print(f"[XoaNgay] Lß╗ùi click n├║t X├│a trong modal: {e}")
            
            # 5.6. Bß║Ñm X├íc nhß║¡n (nß║┐u c├│ popup X├íc nhß║¡n tuß╗òi)
            page.wait_for_timeout(2000)
            try:
                clicked_confirm = page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const confirmBtns = btns.filter(b => b.innerText.trim() === 'X├íc nhß║¡n' || b.innerText.trim() === 'Confirm');
                    if (confirmBtns.length > 0) {
                        confirmBtns[confirmBtns.length - 1].click();
                        return true;
                    }
                    return false;
                }""")
                if clicked_confirm:
                    print("[XoaNgay] ─É├ú click n├║t X├íc nhß║¡n tuß╗òi!")
            except Exception as e:
                pass
            
            # 6. Bß║Ñm X├│a ngay - D├╣ng kß╗ïch bß║ún ElementFromPoint si├¬u viß╗çt cß╗ºa User
            print("[XoaNgay] ─Éang bß║»t ─æß║ºu bß║Ñm X├│a ngay bß║▒ng kß╗ïch bß║ún ElementFromPoint...")
            
            success = False
            for attempt in range(6):
                page.wait_for_timeout(2000)
                frames_list = page.frames
                print(f"[XoaNgay] Attempt {attempt+1}: B╞ím m├ú JS v├áo tß║Ñt cß║ú {len(frames_list)} frames (nh╞░ Extension)...")
                
                js_code = """
                    async () => {
                      const logo = document.querySelector("img.icon-ieQdCp");
                      if (!logo) return "KhongThayLogo";

                      // Vß╗ï tr├¡: d╞░ß╗¢i logo 30px
                      const r = logo.getBoundingClientRect();
                      const size = 50;
                      const x = r.left + (r.width - size) / 2;
                      const y = r.bottom + 30;

                      // Tß║ío highlight
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
                      console.log("─É├ú highlight. Sß║╜ click sau 1.5 gi├óy.");

                      await new Promise(resolve => setTimeout(resolve, 1500));

                      // ß║¿n overlay ─æß╗â lß║Ñy ch├¡nh phß║ºn tß╗¡ ph├¡a d╞░ß╗¢i t├óm ├┤
                      square.style.display = "none";
                      const target = document.elementFromPoint(x + size / 2, y + size / 2);
                      square.remove();

                      if (!target) return "KhongCoPhanTu";

                      const clickable = target.closest(
                        ".confirm-button-ZuDQ59, [role='button'], button, a, [onclick]"
                      ) || target;

                      console.log("─Éang click phß║ºn tß╗¡:", clickable);
                      clickable.click();
                      
                      return "DaClick";
                    }
                """
                
                clicked_this_round = False
                for f in frames_list:
                    try:
                        result = f.evaluate(js_code)
                        if result == "DaClick":
                            print(f"     -> [Tuyß╗çt vß╗¥i] ─É├ú vß║╜ highlight v├á CLICK TR├ÜNG ─É├ìCH trong frame: {f.name or f.url}")
                            clicked_this_round = True
                            break
                    except Exception:
                        # Frame c├│ thß╗â bß╗ï huß╗╖ hoß║╖c lß╗ùi kß║┐t nß╗æi, bß╗Å qua
                        pass
                        
                if clicked_this_round:
                    page.wait_for_timeout(3000)
                    # Kiß╗âm tra xem logo c├│ biß║┐n mß║Ñt khß╗Åi tß║Ñt cß║ú frames ch╞░a
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
                        print("[XoaNgay] X├íc nhß║¡n cß╗¡a sß╗ò X├│a ngay ─æ├ú ─æ├│ng -> TH├ÇNH C├öNG!")
                        break
                    else:
                        print("[XoaNgay] Vß║½n c├▓n thß║Ñy Logo, click ch╞░a ─ân hoß║╖c mß║íng lag...")
            
            if not success:
                print("[XoaNgay] Cß║únh b├ío: V╞░ß╗út qu├í sß╗æ lß║ºn thß╗¡ click X├│a ngay!")
            
            page.wait_for_timeout(2000)
            
            try:
                page.wait_for_timeout(3000)
                page.evaluate("""() => {
                    const all = document.body.innerText;
                    if (!all.includes('Account deleted') && !all.includes('─æ├ú x├│a') && !all.includes('deleted')) throw new Error('Not deleted yet');
                }""")
                page.wait_for_timeout(1000)
            except Exception as e:
                page.wait_for_timeout(5000)
                page.evaluate("""() => {
                    const all = document.body.innerText;
                    if (!all.includes('Account deleted') && !all.includes('─æ├ú x├│a') && !all.includes('deleted')) throw new Error('Timeout: Kh├┤ng thß║Ñy th├┤ng b├ío x├│a th├ánh c├┤ng!');
                }""")
            
            video_tasks[task_id]["message"] = "─É├ú x├│a Account th├ánh c├┤ng!"
            video_tasks[task_id]["status"] = "done"
            
            try: context.close()
            except: pass

    except Exception as e:
        try: context.close()
        except: pass
        video_tasks[task_id]["status"] = "error"
        video_tasks[task_id]["message"] = f"Lß╗ùi khi x├│a account: {e}"


from app.models import CheckVideoReq
def run_check_video_automation(task_id: str, profile_id: str, is_headless: bool = False):
    from playwright.sync_api import sync_playwright
    import time, os
    from pathlib import Path
    
    video_tasks[task_id] = {"status": "running", "message": "─Éang mß╗ƒ tr├¼nh duyß╗çt ─æß╗â kiß╗âm tra..."}
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
            
            # T├¼m tab higgsfield.ai ─æ├ú mß╗ƒ sß║╡n, nß║┐u kh├┤ng c├│ th├¼ lß║Ñy tab ─æß║ºu ti├¬n
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
                    
            # ─É├│ng tß║Ñt cß║ú c├íc tab kh├íc (bao gß╗ôm cß║ú about:blank hoß║╖c tab kh├┤i phß╗Ñc)
            for pg in context.pages:
                if pg != page:
                    try: pg.close()
                    except: pass
            
            try: page.bring_to_front()
            except: pass
            
            video_tasks[task_id]["message"] = "─Éang v├áo trang Genjutsu..."
            page.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=60000)
            
            # Wait a bit
            page.wait_for_timeout(5000)
            
            video_tasks[task_id]["message"] = "─Éang chuyß╗ân sang tab History..."
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
            video_tasks[task_id]["message"] = "─Éang kiß╗âm tra trß║íng th├íi video..."
            
            generating_start_time = None  # Thß╗¥i ─æiß╗âm bß║»t ─æß║ºu Generating
            generating_countdown_done = False  # ─É├ú qua 15 ph├║t ch╞░a
            buffer_countdown_done = False  # ─É├ú qua 5 ph├║t b├╣ ch╞░a
            
            while True:
                # Kiß╗âm tra cß╗¥ dß╗½ng
                if video_tasks.get(task_id, {}).get("force_stop"):
                    video_tasks[task_id]["status"] = "error"
                    video_tasks[task_id]["message"] = "≡ƒ¢æ ─É├ú dß╗½ng theo y├¬u cß║ºu!"
                    context.close()
                    with pw_lock:
                        p.stop()
                    return
                # Lß║Ñy trß║íng th├íi hiß╗çn tß║íi
                status_info = page.evaluate("""() => {
                    // Kiß╗âm tra Processing
                    let spans = document.querySelectorAll('span');
                    for(let s of spans) {
                        if(s.innerText && s.innerText.trim() === 'Processing') return 'processing';
                    }
                    // Kiß╗âm tra Generating
                    for(let s of spans) {
                        if(s.innerText && s.innerText.trim() === 'Generating') return 'generating';
                    }
                    // Kiß╗âm tra video ─æ├ú xong ch╞░a (trong assets-grid)
                    let grid = document.getElementById('assets-grid');
                    if(grid) {
                        let completed = grid.querySelector('[data-job-status="completed"] video');
                        if(completed && completed.src && completed.src.includes('http')) return 'done';
                    }
                    return 'unknown';
                }""")
                
                now = time.time()
                
                if status_info == 'processing':
                    # Trß║íng th├íi Processing ΓåÆ chß╗¥
                    generating_start_time = None  # Reset nß║┐u quay lß║íi processing
                    generating_countdown_done = False
                    buffer_countdown_done = False
                    video_tasks[task_id]["message"] = "─Éang chß╗¥ video tß║ío xong (Processing)..."
                    page.wait_for_timeout(3000)
                    
                elif status_info == 'generating':
                    # Trß║íng th├íi Generating ΓåÆ bß║»t ─æß║ºu ─æß║┐m ng╞░ß╗úc
                    if generating_start_time is None:
                        generating_start_time = now
                        generating_countdown_done = False
                        buffer_countdown_done = False
                    
                    elapsed = now - generating_start_time
                    
                    if not generating_countdown_done:
                        # ─Éß║┐m ng╞░ß╗úc 15 ph├║t (900 gi├óy)
                        remaining = max(0, 900 - elapsed)
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        video_tasks[task_id]["message"] = f"ΓÅ│ Sß║»p ra rß╗ôi! C├▓n khoß║úng {mins} ph├║t {secs} gi├óy nß╗»a..."
                        if elapsed >= 900:
                            generating_countdown_done = True
                    elif not buffer_countdown_done:
                        # Hß║┐t 15 ph├║t, ─æß║┐m th├¬m 5 ph├║t b├╣
                        extra_elapsed = elapsed - 900
                        remaining = max(0, 300 - extra_elapsed)
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        video_tasks[task_id]["message"] = f"ΓÅ│ Th├¬m ch├║t nß╗»a th├┤i! B├╣ giß╗¥ c├▓n {mins} ph├║t {secs} gi├óy..."
                        if extra_elapsed >= 300:
                            buffer_countdown_done = True
                    else:
                        # ─É├ú qua 20 ph├║t vß║½n ch╞░a ra ΓåÆ vß║½n chß╗¥
                        video_tasks[task_id]["message"] = "ΓÅ│ ─Éang chß╗¥ video... (c├│ thß╗â mß║Ñt th├¬m ch├║t thß╗¥i gian)"
                    
                    page.wait_for_timeout(3000)
                    
                elif status_info == 'done':
                    # Video ─æ├ú xong!
                    video_tasks[task_id]["message"] = "Γ£à Video ─æ├ú sß║╡n s├áng, ─æang tß║úi xuß╗æng..."
                    break
                else:
                    # Kh├┤ng r├╡ trß║íng th├íi ΓåÆ kiß╗âm tra th├¬m xem c├│ video ch╞░a
                    has_video = page.evaluate("""() => {
                        let grid = document.getElementById('assets-grid');
                        if(grid) {
                            let completed = grid.querySelector('[data-job-status="completed"] video');
                            if(completed && completed.src && completed.src.includes('http')) return true;
                        }
                        return false;
                    }""")
                    if has_video:
                        video_tasks[task_id]["message"] = "Γ£à Video ─æ├ú sß║╡n s├áng, ─æang tß║úi xuß╗æng..."
                        break
                    else:
                        video_tasks[task_id]["message"] = "─Éang chß╗¥ video tß║ío xong..."
                        page.wait_for_timeout(3000)
                    
            page.wait_for_timeout(2000)
            
            # Get Video URLs - CHß╗ê Lß║ñY VIDEO TRONG assets-grid (video kß║┐t quß║ú thß║¡t)
            video_urls = page.evaluate("""() => {
                let urls = [];
                // ╞»u ti├¬n lß║Ñy tß╗½ #assets-grid vß╗¢i data-job-status="completed"
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
                // Nß║┐u kh├┤ng t├¼m ─æ╞░ß╗úc trong grid, fallback lß║Ñy video tß╗½ history c├│ URL cloudfront/cdn
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
                    video_tasks[task_id]["message"] = "─É├ú tß║úi xong!"
                except Exception as e:
                    video_tasks[task_id] = {"status": "error", "message": f"Lß╗ùi khi tß║úi video: {e}"}
            else:
                video_tasks[task_id] = {"status": "error", "message": "Kh├┤ng t├¼m thß║Ñy video n├áo!"}
                
            page.wait_for_timeout(2000)
            context.close()
            with pw_lock:
                p.stop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        video_tasks[task_id] = {"status": "error", "message": str(e)}

# L╞░u c├íc task_id ─æang check video ─æß╗â c├│ thß╗â dß╗½ng h├áng loß║ít
check_video_task_ids = set()

@app.post("/api/video/check")
def api_check_video(req: CheckVideoReq):
    import uuid
    import threading
    task_id = str(uuid.uuid4())
    video_tasks[task_id] = {"status": "pending", "message": "Chuß║⌐n bß╗ï kiß╗âm tra video..."}
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
    """Dß╗½ng tß║Ñt cß║ú tiß║┐n tr├¼nh check video ─æang chß║íy"""
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
    video_tasks[task_id] = {"status": "pending", "message": "Chuß║⌐n bß╗ï x├│a account..."}
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
    # KHß╗₧I CHß║áY BACKGROUND WATCHER DOWNLOADS ─Éß╗é Tß╗░ ─Éß╗ÿNG ─Éß╗öI ─ÉU├öI FILE Lß║á TH├ÇNH .MP4/.JPG
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
                    # Kh├┤ng can thiß╗çp nß║┐u file ─æang down hoß║╖c l├á temp
                    if ext == '.crdownload' or ext == '.tmp': continue
                    # ─É├ú c├│ ─æu├┤i hß╗úp lß╗ç th├¼ bß╗Å qua
                    if ext in ('.mp4','.jpg','.png','.webp','.webm','.gif','.jpeg','.avi','.mov','.mkv'): continue
                    # Chß╗ë xß╗¡ l├╜ file tß║ío/sß╗¡a trong 15 ph├║t gß║ºn ─æ├óy
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
                            print(f"[Watcher] Tß╗▒ ─æß╗Öng ─æß╗òi t├¬n: {f.name} -> {new_path.name}")
                        except PermissionError:
                            pass # File c├│ thß╗â ─æang ─æ╞░ß╗úc Chrome ghi dß╗ƒ, bß╗Å qua chß╗¥ loop sau
                        except Exception as e:
                            pass
            except Exception as e:
                time.sleep(5)
                
    import threading
    threading.Thread(target=_watch_downloads_folder, daemon=True).start()
    
    import uvicorn
    print("""
ΓòöΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòù
Γòæ   Antidetect Unlimited V4 - Full Featured      Γòæ
Γòæ   Γ£à Cookie Import (BitBrowser format)         Γòæ
Γòæ   Γ£à Random Fingerprint (giß╗» cookie)           Γòæ
Γòæ   Γ£à Tabs persistence (─æ├│ng mß╗ƒ vß║½n c├▓n)        Γòæ
Γòæ   ΓÖ╛∩╕Å Unlimited Profiles                        Γòæ
ΓòÜΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓòÉΓò¥

-> http://localhost:5333
    """)
    uvicorn.run("main:app", host="0.0.0.0", port=5333, reload=False)

