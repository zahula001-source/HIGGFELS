from . import browser_settings
"""
V19 - DAI TU THAT SU - Fix tab xoay 100%
- Xoa sach session + Preferences de khong bao gio restore 3 tab
- Chi mo 1 tab Google duy nhat, khong extension, khong proxy, khong gi het
- De test cho chac, sau do moi them IP + extension lai
"""
import os, sys, json, time, threading, subprocess, shutil, random
from pathlib import Path
from typing import Dict
from .fingerprint import get_proxy_dict

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

running_browsers: Dict[str, subprocess.Popen] = {}
running_lock = threading.RLock()
profile_locks = {}

def profile_lock(profile_id):
    with running_lock:
        return profile_locks.setdefault(profile_id, threading.RLock())

def clean_session_hard(user_data_dir):
    """Xoa TANH BANGH session cu"""
    try:
        default_dir = Path(user_data_dir) / "Default"
        # Xoa het file session
        patterns = ["Current Tabs", "Last Tabs", "Current Session", "Last Session", "Tabs", "Tab Groups", "Sessions", "Session Storage", "Local Storage"]
        if default_dir.exists():
            for item in default_dir.iterdir():
                try:
                    # Xoa bat ky file nao chua Session hoac Tabs
                    if "Session" in item.name or "Tabs" in item.name:
                        if item.is_file():
                            item.unlink()
                        else:
                            shutil.rmtree(item, ignore_errors=True)
                except:
                    pass
            # Xoa thu muc Sessions
            for d in ["Sessions", "Session Storage", "Local Storage"]:
                p = default_dir / d
                if p.exists():
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                    except:
                        pass
        
        # Tao Preferences moi tinh - KHONG restore
        pref_file = default_dir / "Preferences"
        default_dir.mkdir(parents=True, exist_ok=True)
        prefs = {
            "session": {
                "restore_on_startup": 0,
                "startup_urls": ["https://higgsfield.ai/ai/video?model=genjutsu"]
            },
            "startup_pages_migration_time": 0,
            "browser": {
                "has_seen_welcome_page": True
            }
        }
        try:
            pref_file.write_text(json.dumps(prefs), encoding="utf-8")
        except:
            pass
        print(f"Cleaned hard session at {user_data_dir}")
    except Exception as e:
        print(f"Clean hard err {e}")

def get_chromium_runner_simple(profile_id, user_data_dir, proxy_dict, fingerprint, startup_urls=None, startup_mode="once", port=None, enable_ext_btn2=False, enable_ext=True, profile_extensions="", headless=False):
    proxy_str = repr(proxy_dict)
    user_data_dir_fs = user_data_dir.replace("\\", "/")
    log_path = str((LOGS_DIR / f"launch_{profile_id}.log").as_posix())
    cookie_file = str((Path(user_data_dir) / "imported_cookies.json").as_posix())

    screen_str = fingerprint.get("screen", "1920x1080") if fingerprint else "1920x1080"
    try:
        sw, sh = map(int, screen_str.split("x"))
    except:
        sw, sh = 1920, 1080
    random_id = fingerprint.get("random_id", random.randint(100000,999999)) if fingerprint else random.randint(100000,999999)

    lines = []
    lines.append("import sys, time, json, traceback, random, os")
    lines.append("from pathlib import Path")
    lines.append(f'log_file = Path(r"{log_path}")')
    lines.append(f'cookie_path = Path(r"{cookie_file}")')
    lines.append('log_file.parent.mkdir(parents=True, exist_ok=True)')
    lines.append("def log(m):")
    lines.append("    print(str(m), flush=True)")
    lines.append("")
    lines.append(f'project_root = {str(BASE_DIR)!r}')
    lines.append(f'profile_id = "{profile_id}"')
    lines.append(f'user_data_dir = r"{user_data_dir_fs}"')
    lines.append(f'proxy = {proxy_str}')
    lines.append(f'sw = {sw}')
    lines.append(f'sh = {sh}')
    lines.append(f'random_id = {random_id}')
    
    import json
    lines.append(f'startup_urls_str = {json.dumps(startup_urls if startup_urls else "")}')
    lines.append(f'startup_mode = {json.dumps(startup_mode if startup_mode else "once")}')
    lines.append(f'cdp_port = {port}')
    lines.append(f'enable_ext_btn2 = {"True" if enable_ext_btn2 else "False"}')
    lines.append(f'enable_ext = {"True" if enable_ext else "False"}')
    lines.append(f'profile_extensions = {json.dumps(profile_extensions)}')
    
    lines.append(f'log("[{profile_id}] Chrome profile runner ID={random_id}")')
    lines.append(f'if proxy:')
    lines.append('    log("Proxy configured")')
    lines.append("")
    lines.append("context = None")
    lines.append("playwright = None")
    lines.append("runner_lock = None")
    lines.append("try:")
    lines.append("    import msvcrt")
    lines.append("    runner_lock = open(Path(user_data_dir) / 'runner.lock', 'a+b')")
    lines.append("    runner_lock.seek(0)")
    lines.append("    msvcrt.locking(runner_lock.fileno(), msvcrt.LK_NBLCK, 1)")
    lines.append("    stop_file = Path(user_data_dir) / 'runner.stop'")
    lines.append("    stop_file.unlink(missing_ok=True)")
    lines.append("    sys.path.insert(0, project_root)")
    lines.append("    from app.search_settings import google_search_extension")
    lines.append("    runtime_temp = Path(user_data_dir) / 'automation_tmp'")
    lines.append("    runtime_temp.mkdir(exist_ok=True)")
    lines.append("    os.environ['TEMP'] = os.environ['TMP'] = str(runtime_temp)")
    lines.append("    engine = os.environ.get('HIGGSFIELD_BROWSER_ENGINE', 'chrome').lower()")
    lines.append("    if engine == 'cloakbrowser':")
    lines.append("        from cloakbrowser import launch_persistent_context")
    lines.append("    elif engine == 'chrome':")
    lines.append("        from playwright.sync_api import sync_playwright")
    lines.append("        playwright = sync_playwright().start()")
    lines.append("        launch_persistent_context = playwright.chromium.launch_persistent_context")
    lines.append("    else:")
    lines.append("        raise ValueError('HIGGSFIELD_BROWSER_ENGINE must be chrome or cloakbrowser')")
    lines.append("    args = [")
    lines.append('        "--disable-blink-features=AutomationControlled",')
    lines.append('        "--no-first-run",')
    lines.append('        "--no-default-browser-check",')
    lines.append('        "--restore-last-session",')
    lines.append(f'        "--window-size={sw},{sh}",')
    lines.append('        "--remote-debugging-port=0",')
    lines.append('        "--lang=vi-VN",')
    lines.append('        "--accept-lang=vi-VN,vi",')
    lines.append(f'        "--fingerprint={random_id}",')
    lines.append(f'        "--fingerprint-timezone=Asia/Ho_Chi_Minh",')
    lines.append(f'        "--fingerprint-locale=vi-VN",')
    lines.append(f'        "--fingerprint-platform=windows",')
    lines.append("    ]")
    
    if headless:
        lines.append("    args.append('--window-position=-32000,-32000')")
        
    lines.append("    launch_args = dict(")
    lines.append("        user_data_dir=user_data_dir,")
    lines.append("        headless=False,")
    lines.append("        args=args,")
    lines.append('        downloads_path=str(Path.home() / "Downloads"),')
    lines.append('        accept_downloads=True,')
    lines.append("    )")
    code_no_ext = """
    if enable_ext and profile_extensions:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
        try:
            from extensions import resolve_extension_paths
            exts = resolve_extension_paths(profile_extensions, Path(user_data_dir))
            if exts:
                launch_args["extension_paths"] = exts
        except Exception as e:
            log(f"Extension resolve err: {e}")

    if proxy:
        launch_args["proxy"] = proxy

    log("Launching browser...")
    if engine == "chrome":
        launch_args["channel"] = "chrome"
        launch_args["no_viewport"] = True
        launch_args["ignore_default_args"] = ["--disable-extensions"]
        launch_args["args"] = [arg for arg in args if not arg.startswith("--fingerprint")]
        exts = launch_args.pop("extension_paths", [])
        if exts:
            log("WARNING: Chrome may restrict unpacked extensions; use a supported browser build if needed.")
            launch_args["args"].extend(["--disable-extensions-except=" + ",".join(exts), "--load-extension=" + ",".join(exts)])
        log("Engine=chrome; CloakBrowser fingerprint emulation is not active")
    else:
        launch_args.setdefault("extension_paths", []).append(google_search_extension(user_data_dir))
        log("Engine=cloakbrowser; Google address-bar search enabled")
    context = launch_persistent_context(**launch_args)
    closed = [False]
    context.on("close", lambda *_: closed.__setitem__(0, True))

        
    try:
        import time
        for _ in range(20):
            active_port_file = Path(user_data_dir) / "DevToolsActivePort"
            if active_port_file.exists():
                lines_port = active_port_file.read_text().splitlines()
                if lines_port:
                    Path(user_data_dir, "cdp_port.txt").write_text(lines_port[0])
                    break
            time.sleep(0.5)
    except: pass

    log(f"Launched, pages={len(context.pages)}")
    
    # Khong dung accept_downloads=True de Chrome download native 100%
    # Tranh Playwright block event loop gay loi .crdownload hoac crash


    try:
        # Playwright tự động nhét 1 tab about:blank vào, mình sẽ xóa nó đi nếu có tab cũ được khôi phục
        if context.pages:
            context.pages[0].wait_for_timeout(1000) # Đợi tab cũ khôi phục
        
        # Xóa tab about:blank nhưng KHÔNG BAO GIỜ đóng hết sạch tab
        pages = context.pages
        if len(pages) > 1:
            blank_pages = [pg for pg in pages if pg.url == "about:blank"]
            if len(blank_pages) == len(pages):
                # Tất cả đều là blank, giữ lại 1 cái
                try: pages[0].goto("https://higgsfield.ai/ai/video?model=genjutsu", wait_until="domcontentloaded")
                except: pass
                for pg in blank_pages[1:]:
                    try: pg.close()
                    except: pass
            else:
                # Có tab khác blank, đóng hết blank
                for pg in blank_pages:
                    try: pg.close()
                    except: pass
        elif len(pages) == 1 and pages[0].url == "about:blank":
            try:
                pages[0].goto("https://higgsfield.ai/ai/video?model=genjutsu", wait_until="domcontentloaded")
            except:
                pass
    except:
        pass

    try:
        if startup_urls_str:
            urls = [u.strip() for u in startup_urls_str.splitlines() if u.strip()]
            if startup_mode == 'once':
                flag_file = Path(user_data_dir) / 'startup_once.flag'
                if not flag_file.exists():
                    for u in urls:
                        try: context.new_page().goto(u, timeout=10000)
                        except: pass
                    flag_file.touch()
            else: # always
                existing_urls = [pg.url for pg in context.pages]
                for u in urls:
                    u_norm = u.replace("https://", "").replace("http://", "").strip("/")
                    if not any(u_norm in eu for eu in existing_urls):
                        try: context.new_page().goto(u, timeout=10000)
                        except: pass
    except Exception as e:
        log(f"Startup urls err {e}")

    # Cookie
    if cookie_path.exists():
        try:
            cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
            for i in range(0, len(cookies), 30):
                chunk = cookies[i:i+30]
                try:
                    context.add_cookies(chunk)
                except:
                    for c in chunk:
                        try:
                            context.add_cookies([c])
                        except:
                            pass
            log(f"Cookies {len(cookies)} OK")
        except Exception as e:
            log(f"Cookie err {e}")



    # Tu dong click Extension Fingerprint Spoofer neu co cai
    try:
        if not enable_ext:
            raise RuntimeError("Extension configuration disabled")
        ext_page = context.new_page()
        ext_page.goto("chrome-extension://facgnnelgcipeopfbjcajpaibhhdjgcp/popup.html", wait_until="load", timeout=5000)
        ext_page.wait_for_timeout(1000)
        
        import random
        # Nút 1 (Navigator) luôn bật, nút 2 (Canvas) chỉ bật nếu enable_ext_btn2
        buttons_to_click = ["Spoof Navigator"]
        if enable_ext_btn2:
            if random.random() > 0.5:
                buttons_to_click.append("Spoof Canvas")
        else:
            # Đảm bảo tắt nút 2 nếu nó đang bật (click để toggle off)
            try:
                canvas_btn = ext_page.locator("text='Spoof Canvas'")
                # Nếu nút đang được kích hoạt (màu đỏ) thì click để tắt
                cls = canvas_btn.get_attribute("class") or ""
                style = canvas_btn.evaluate("el => el.style.background + el.style.backgroundColor + window.getComputedStyle(el).backgroundColor")
                if "red" in str(style).lower() or "rgb(239" in str(style) or "active" in cls.lower():
                    canvas_btn.click(timeout=1000)
            except: pass
        for btn in buttons_to_click:
            try:
                ext_page.locator(f"text='{btn}'").click(timeout=1000)
                ext_page.wait_for_timeout(300)
            except:
                pass
        
        ext_page.close()
        log("Extension Fingerprint Spoofer auto-configured!")
    except Exception:
        try:
            ext_page.close()
        except:
            pass

    # Giữ browser sống cho đến khi đóng HẾT SẠCH tab
    # Quan trọng: dùng biến 'page_item' thay vì 'p' để tránh shadow biến 'p' của playwright!
    # Pump events so closing Chrome also ends the runner and updates the UI.
    pages = [pg for pg in context.pages if not pg.is_closed()]
    if closed[0] or not pages:
        raise RuntimeError("Browser closed before it became ready")
    pages[0].wait_for_timeout(500)
    if closed[0]:
        raise RuntimeError("Browser closed during startup")
    log("BROWSER_READY")
    while not closed[0] and not stop_file.exists():
        pages = [pg for pg in context.pages if not pg.is_closed()]
        if not pages:
            break
        try:
            pages[0].wait_for_timeout(500)
        except Exception as exc:
            if type(exc).__name__ == "CloakBrowserLicenseError":
                raise
            if closed[0] or not context.pages:
                break
            if pages[0].is_closed():
                continue
            raise
    log("BROWSER_CLOSED")
except Exception as e:
    log(f"FATAL {e}")
    log(traceback.format_exc())
    sys.exit(1)
finally:
    if context is not None:
        try: context.close()
        except Exception: pass
    if playwright is not None:
        try: playwright.stop()
        except Exception: pass
    if runner_lock is not None:
        runner_lock.close()
"""
    lines.append(code_no_ext)
    return "\n".join(lines)

allocated_ports = set()
def get_free_port():
    import socket
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]
            if port not in allocated_ports:
                allocated_ports.add(port)
                return port

def launch_profile(profile, req=None):
    # Different profiles launch concurrently; same-profile operations serialize.
    with profile_lock(profile.id):
        try:
            return _launch_profile(profile, req)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


def _launch_profile(profile, req=None):
    with running_lock:
        if profile.id in running_browsers:
            proc = running_browsers[profile.id]
            if proc.poll() is None:
                return {"status": "already_running", "pid": proc.pid}
            else:
                del running_browsers[profile.id]

    proxy_dict = get_proxy_dict(profile.proxy) if profile.proxy else None
    user_data_dir = profile.user_data_dir
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    # Dọn dẹp profile trước khi mở để tránh lỗi tự đóng hoặc kẹt
    # Chrome owns its profile locks. Do not kill browsers or delete their locks.
    log_file = LOGS_DIR / f"launch_{profile.id}.log"
    if log_file.exists():
        try:
            log_file.unlink()
        except:
            pass

    fp_path = Path(user_data_dir) / "fingerprint.json"
    if not fp_path.exists():
        try:
            fp_path.write_text(json.dumps(profile.fingerprint, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except:
            pass

    startup_urls = req.startup_urls if req else None
    startup_mode = req.startup_mode if req else None
    enable_ext_btn2 = req.enable_ext_btn2 if req else False
    enable_ext = req.enable_ext if req else False
    profile_extensions = getattr(profile, "extensions", "") if profile else ""
    port = get_free_port()
    headless = getattr(req, 'headless', False) if req else False
    
    py_code = get_chromium_runner_simple(profile.id, user_data_dir, proxy_dict, profile.fingerprint, startup_urls, startup_mode, port, enable_ext_btn2, enable_ext, profile_extensions, headless=headless)

    tmp_script = DATA_DIR / f"runner_{profile.id}.py"
    tmp_script.write_text(py_code, encoding="utf-8")

    cmd = [sys.executable, str(tmp_script)]
    try:
        log_file_handle = open(log_file, "w", encoding="utf-8", errors="ignore")
        try:
            proc = subprocess.Popen(cmd, stdout=log_file_handle, stderr=subprocess.STDOUT,
                                    creationflags=0x08000000, cwd=str(BASE_DIR))
        finally:
            log_file_handle.close()
        ready = False
        for _ in range(180):
            time.sleep(0.5)
            if proc.poll() is not None:
                try:
                    log_file_handle.close()
                except:
                    pass
                txt = log_file.read_text(encoding="utf-8", errors="ignore")[-5000:] if log_file.exists() else "No log"
                return {"status": "error", "message": f"Exit {proc.returncode}\n{txt}"}
            if log_file.exists():
                try:
                    if "BROWSER_READY" in log_file.read_text(encoding="utf-8", errors="ignore"):
                        ready = True
                        break
                except:
                    pass
        if not ready or proc.poll() is not None:
            if proc.poll() is None:
                Path(user_data_dir, "runner.stop").touch()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, creationflags=0x08000000)
            txt = log_file.read_text(encoding="utf-8", errors="ignore")[-5000:]
            return {"status": "error", "message": "Browser did not become ready.\n" + txt}
        proc.profile_dir = str(user_data_dir)
        with running_lock:
            running_browsers[profile.id] = proc
        return {"status": "launched", "pid": proc.pid}
    except Exception as e:
        import traceback
        return {"status": "error", "message": f"{e}\n{traceback.format_exc()}"}

def launch_profile_with_fallback(profile, req=None):
    return launch_profile(profile, req)

def close_profile(profile_id: str):
    with profile_lock(profile_id):
        with running_lock:
            proc = running_browsers.get(profile_id)
        if not proc or proc.poll() is not None:
            with running_lock:
                running_browsers.pop(profile_id, None)
            return {"status": "not_running"}
        try:
            Path(proc.profile_dir, "runner.stop").touch()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                result = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                        capture_output=True, creationflags=0x08000000)
                if result.returncode and proc.poll() is None:
                    raise RuntimeError("Could not stop the profile process tree")
                proc.wait(timeout=5)
            with running_lock:
                running_browsers.pop(profile_id, None)
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
