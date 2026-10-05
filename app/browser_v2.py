"""
Browser launcher V2 - fix tải chậm, mở nhanh 2-3s
- Chỉ tải Camoufox 1 lần duy nhất, lock không cho tải song song
- Lần sau mở instant
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

running_browsers: Dict[str, subprocess.Popen] = {}
running_lock = threading.Lock()

LOCK_FILE = BASE_DIR / "data" / ".camoufox_fetch.lock"
CACHE_MARKER = BASE_DIR / "data" / ".camoufox_ready"

def get_camoufox_cache_path():
    """Lấy đường dẫn cache mặc định của Camoufox trên Windows"""
    local_app = os.getenv("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    # Camoufox lưu ở LocalAppData\camoufox\camoufox
    cache_base = Path(local_app) / "camoufox" / "camoufox"
    return cache_base

def is_camoufox_binary_ready():
    """Check xem binary đã tải chưa"""
    cache_base = get_camoufox_cache_path()
    # Tìm folder camoufox-* trong cache
    if not cache_base.exists():
        return False
    # Có ít nhất 1 folder win.x86_64 hoặc similar và có firefox.exe bên trong
    for child in cache_base.rglob("firefox.exe"):
        if child.exists() and child.stat().st_size > 10_000_000: # >10MB mới là đã giải nén xong
            return True
    # Check thêm marker của chúng ta
    if CACHE_MARKER.exists():
        return True
    return False

def ensure_camoufox_once():
    """Đảm bảo chỉ tải 1 lần, nếu đang tải thì đợi"""
    if is_camoufox_binary_ready():
        return True
    
    # Nếu đang có lock thì đợi
    if LOCK_FILE.exists():
        print("[*] Camoufox đang được tải ở process khác, đợi...")
        # Đợi tối đa 10 phút
        for _ in range(600):
            if is_camoufox_binary_ready():
                return True
            if not LOCK_FILE.exists():
                break
            time.sleep(1)
    
    # Tạo lock
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        print("[*] Bắt đầu tải Camoufox binary lần đầu (500MB, chỉ 1 lần duy nhất)...")
        print("    Tải từ GitHub, nếu mạng VN chậm thì đợi ~3-5 phút nhé")
        
        # Dùng CLI chính thức để fetch - chuẩn nhất
        cmd = [sys.executable, "-m", "camoufox", "fetch"]
        proc = subprocess.run(cmd, capture_output=False, text=True)
        
        if is_camoufox_binary_ready() or proc.returncode == 0:
            CACHE_MARKER.write_text("ready", encoding="utf-8")
            print("[OK] Camoufox đã sẵn sàng! Lần sau mở chỉ 2-3s")
            return True
        else:
            print(f"[WARN] Fetch return code {proc.returncode}, nhưng thử tiếp vẫn được")
            return False
    finally:
        if LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink()
            except:
                pass

def get_camoufox_python_code_fast(profile_id, user_data_dir, os_choice, proxy_dict, fingerprint_preset):
    proxy_str = json.dumps(proxy_dict) if proxy_dict else "None"
    
    code = f'''
import sys, time, json
from pathlib import Path

profile_id = "{profile_id}"
user_data_dir = r"{user_data_dir}"
os_choice = "{os_choice}"
proxy = {proxy_str}
fingerprint_preset = {str(fingerprint_preset)}

print(f"[{{profile_id}}] Launching fast...")

try:
    from camoufox.sync_api import Camoufox
    
    kwargs = dict(
        persistent_context=True,
        user_data_dir=user_data_dir,
        headless=False,
    )
    
    if proxy:
        kwargs["proxy"] = proxy
    
    if fingerprint_preset:
        kwargs["os"] = os_choice if os_choice != "random" else "windows"
        kwargs["fingerprint_preset"] = True
    else:
        kwargs["config"] = {{"os": os_choice}}
    
    kwargs["humanize"] = True
    
    # Tắt update check để mở nhanh hơn (nếu không cần update liên tục)
    # kwargs["check_update"] = False
    
    with Camoufox(**kwargs) as browser:
        print(f"[{{profile_id}}] READY - {{user_data_dir}}")
        try:
            if browser.pages:
                page = browser.pages[0]
            else:
                page = browser.new_page()
            # Không auto mở whoer nữa để mở nhanh hơn, bạn tự gõ
            # page.goto("https://whoer.net", wait_until="domcontentloaded")
        except Exception as e:
            print(f"Page error: {{e}}")
        
        print("BROWSER_READY")
        while True:
            time.sleep(1)

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
    from app.browser_settings import get_global_args
    extra = get_global_args()
    code = f'''
import time, json
from playwright.sync_api import sync_playwright

profile_id = "{profile_id}"
user_data_dir = r"{user_data_dir}"
proxy = {proxy_str}
extra_args = {json.dumps(extra)}

print(f"[{{profile_id}}] Starting Chromium (instant)...")

with sync_playwright() as p:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ] + extra_args
    context = p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        args=args,
        proxy=proxy,
        viewport={{"width": 1280, "height": 800}},
    )
    context.add_init_script("""Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});""")
    page = context.pages[0] if context.pages else context.new_page()
    print("BROWSER_READY")
    while True:
        time.sleep(1)
'''
    return code

def launch_profile(profile):
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

    # QUAN TRỌNG: Nếu là camoufox thì đảm bảo binary đã tải xong 1 lần
    if profile.browser == "camoufox":
        if not is_camoufox_binary_ready():
            # Nếu chưa ready thì chỉ cho 1 profile tải, các profile khác đợi
            # Nhưng ở đây ta vẫn cho launch, process con sẽ tự fetch và lock
            # Để tránh 2 process cùng tải, ta ensure ở parent trước
            ensure_camoufox_once()

    if profile.browser == "camoufox":
        py_code = get_camoufox_python_code_fast(
            profile_id=profile.id,
            user_data_dir=user_data_dir,
            os_choice=profile.os,
            proxy_dict=proxy_dict,
            fingerprint_preset=profile.fingerprint.get("preset", True) if profile.fingerprint else True
        )
    else:
        py_code = get_chromium_python_code(profile.id, user_data_dir, proxy_dict)

    tmp_script = BASE_DIR / "data" / f"runner_{profile.id}.py"
    tmp_script.write_text(py_code, encoding="utf-8")

    cmd = [sys.executable, str(tmp_script)]
    
    try:
        if os.name == 'nt':
            proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        time.sleep(1.5)
        if proc.poll() is not None:
            # Đọc lỗi nếu có
            return {"status": "error", "message": f"Exit code {proc.returncode}"}

        with running_lock:
            running_browsers[profile.id] = proc

        return {"status": "launched", "pid": proc.pid}

    except Exception as e:
        return {"status": "error", "message": str(e)}

def launch_profile_with_fallback(profile):
    result = launch_profile(profile)
    if result.get("should_fallback"):
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
