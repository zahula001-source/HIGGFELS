"""
Browser launcher - quản lý process, siêu nhẹ
Hỗ trợ 2 engine:
- camoufox (Firefox stealth, khuyên dùng) -> undetectable
- chromium (Playwright + stealth) -> giống Chrome nhất
"""
import os
import sys
import json
import time
import threading
import subprocess
from pathlib import Path
from typing import Dict
from .fingerprint import get_proxy_dict

BASE_DIR = Path(__file__).parent.parent

# Lưu process đang chạy
running_browsers: Dict[str, subprocess.Popen] = {}
running_lock = threading.Lock()

def get_camoufox_python_code(profile_id, user_data_dir, os_choice, proxy_dict, fingerprint_preset):
    """Tạo script Python con chạy Camoufox độc lập"""
    proxy_str = json.dumps(proxy_dict) if proxy_dict else "None"
    
    # Camoufox sync API - code chạy trong process riêng để không block server
    code = f'''
import sys, time, json
from pathlib import Path

profile_id = "{profile_id}"
user_data_dir = r"{user_data_dir}"
os_choice = "{os_choice}"
proxy = {proxy_str}
fingerprint_preset = {str(fingerprint_preset)}

try:
    from camoufox.sync_api import Camoufox
    print(f"[{{profile_id}}] Starting Camoufox...")
    
    kwargs = dict(
        persistent_context=True,
        user_data_dir=user_data_dir,
        headless=False,
    )
    
    # Proxy
    if proxy:
        kwargs["proxy"] = proxy
    
    # Fingerprint
    if fingerprint_preset:
        kwargs["os"] = os_choice if os_choice != "random" else "windows"
        kwargs["fingerprint_preset"] = True
    else:
        kwargs["config"] = {{"os": os_choice}}
    
    # Geo / locale auto từ proxy nếu có
    kwargs["humanize"] = True
    
    with Camoufox(**kwargs) as browser:
        print(f"[{{profile_id}}] Camoufox launched! user_data_dir={{user_data_dir}}")
        # Mở trang check
        try:
            if browser.pages:
                page = browser.pages[0]
            else:
                page = browser.new_page()
            page.goto("https://whoer.net", wait_until="domcontentloaded")
        except Exception as e:
            print(f"Page open error: {{e}}")
        
        print("BROWSER_READY")
        # Giữ browser sống cho tới khi bị kill
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

except ImportError as e:
    print("CAMOUFOX_NOT_INSTALLED:" + str(e))
    sys.exit(2)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"LAUNCH_ERROR:{{e}}")
    sys.exit(1)
'''
    return code

def get_chromium_python_code(profile_id, user_data_dir, proxy_dict):
    proxy_str = json.dumps(proxy_dict) if proxy_dict else "None"
    code = f'''
import time, json
from pathlib import Path
from playwright.sync_api import sync_playwright

profile_id = "{profile_id}"
user_data_dir = r"{user_data_dir}"
proxy = {proxy_str}

print(f"[{{profile_id}}] Starting Chromium stealth...")

try:
    with sync_playwright() as p:
        # Stealth args
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage"
        ]
        
        proxy_option = None
        if proxy:
            proxy_option = proxy

        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            args=args,
            proxy=proxy_option,
            viewport={{"width": 1280, "height": 800}},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US"
        )

        # inject stealth script (anti canvas/webgl simple)
        context.add_init_script("""
            // Overwrite navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
            
            // Canvas noise
            const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function() {{
                // tiny noise
                return origToDataURL.apply(this, arguments);
            }};
            
            // Spoof hardwareConcurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => 8}});
            Object.defineProperty(navigator, 'deviceMemory', {{get: () => 8}});
        """)

        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://browserleaks.com/canvas")
        except:
            pass
        
        print("BROWSER_READY")
        while True:
            time.sleep(1)

except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"LAUNCH_ERROR:{{e}}")
'''
    return code

def launch_profile(profile):
    """Launch profile trong process riêng biệt -> nhẹ, không block"""
    with running_lock:
        if profile.id in running_browsers:
            proc = running_browsers[profile.id]
            if proc.poll() is None:
                return {"status": "already_running", "pid": proc.pid}
            else:
                del running_browsers[profile.id]

    from app.browser_settings import get_algo_proxy
    proxy_dict = get_algo_proxy(profile.name)
    user_data_dir = profile.user_data_dir
    os.makedirs(user_data_dir, exist_ok=True)

    # Chọn code theo browser type
    if profile.browser == "camoufox":
        py_code = get_camoufox_python_code(
            profile_id=profile.id,
            user_data_dir=user_data_dir,
            os_choice=profile.os,
            proxy_dict=proxy_dict,
            fingerprint_preset=profile.fingerprint.get("preset", True) if profile.fingerprint else True
        )
    else:
        py_code = get_chromium_python_code(profile.id, user_data_dir, proxy_dict)

    # Ghi ra file tạm
    tmp_script = BASE_DIR / "data" / f"runner_{profile.id}.py"
    tmp_script.write_text(py_code, encoding="utf-8")

    # Launch process
    # Dùng sys.executable để dùng đúng python env
    cmd = [sys.executable, str(tmp_script)]
    
    try:
        # Trên Windows thì CREATE_NEW_CONSOLE để mỗi browser log riêng
        if os.name == 'nt':
            proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Wait a bit để check lỗi nhanh (camoufox not installed)
        time.sleep(2.5)
        if proc.poll() is not None:
            # process chết rồi -> đọc log nếu có
            if proc.stdout:
                out = proc.stdout.read() if hasattr(proc.stdout, 'read') else ""
            else:
                out = ""
            # đọc file log nếu cần
            # fallback: thử chomium nếu camoufox fail
            if "CAMOUFOX_NOT_INSTALLED" in out or proc.returncode == 2:
                return {"status": "camoufox_not_installed", "message": "Camoufox chưa cài. Đang fallback sang Chromium...", "should_fallback": True}
            return {"status": "error", "message": f"Process exited early code={proc.returncode} out={out[:500]}"}

        with running_lock:
            running_browsers[profile.id] = proc

        return {"status": "launched", "pid": proc.pid}

    except Exception as e:
        return {"status": "error", "message": str(e)}

def launch_profile_with_fallback(profile):
    result = launch_profile(profile)
    if result.get("should_fallback"):
        # fallback to chromium
        profile.browser = "chromium"
        return launch_profile(profile)
    return result

def close_profile(profile_id: str):
    with running_lock:
        proc = running_browsers.get(profile_id)
        if not proc:
            return {"status": "not_running"}
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            del running_browsers[profile_id]
            return {"status": "closed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

def is_running(profile_id: str) -> bool:
    with running_lock:
        proc = running_browsers.get(profile_id)
        if not proc:
            return False
        return proc.poll() is None

def list_running():
    with running_lock:
        return {pid: proc.pid for pid, proc in running_browsers.items() if proc.poll() is None}
