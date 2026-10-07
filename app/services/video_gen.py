from app.services.video_history import confirm_generation, refresh_video_history
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
from app.services.browser_navigation import install_vpn_welcome_guard

def _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=False, is_headless=False, engine="chrome", generate_ip=False):
    """Mở trình duyệt với Random FP và kích hoạt extension
    only_navigator=True: chỉ bật nút 1 (Spoof Navigator) - dùng khi cần tải ảnh
    close_old_tabs=True: đóng hết các tab cũ khi mở lên (chỉ dùng cho video creation)
    """
    # Nếu chrome đang mở, ưu tiên dùng chrome đó
    from app.browser import prepare_chrome_136_profile
    runtime_dir = profile.user_data_dir if engine == "cloakbrowser" else prepare_chrome_136_profile(profile.user_data_dir)
    port_file = Path(runtime_dir) / "cdp_port.txt"
    if port_file.exists():
        try:
            port = int(port_file.read_text().strip())
            browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
            print(f"Đã kết nối vào Chrome đang mở của profile {profile.name} qua CDP port {port}")
            context = browser.contexts[0]
            install_vpn_welcome_guard(context)
            return context, True
        except Exception as e:
            pass
            
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
    # Bỏ tải extension mặc định của Playwright bằng cách đưa vào ignore_args
    ignore_args = ["--disable-extensions"]
    extension_dirs = []
    
    # Tao extension doi ten tab
    try:
        import json
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
    if generate_ip:
        vpn_dir = Path(DATA_DIR) / "extensions" / "1clickvpn"
        if not (vpn_dir / "manifest.json").is_file():
            raise RuntimeError("Sinh IP: chưa cài tiện ích 1ClickVPN cho trình duyệt")
        vpn_key = json.loads((vpn_dir / "manifest.json").read_text(encoding="utf-8-sig")).get("key")
        has_vpn = False
        for extension_dir in extension_dirs:
            try:
                manifest = json.loads((Path(extension_dir) / "manifest.json").read_text(encoding="utf-8-sig"))
                if vpn_key and manifest.get("key") == vpn_key:
                    has_vpn = True
                    break
            except (OSError, ValueError):
                pass
        if not has_vpn:
            extension_dirs.append(str(vpn_dir.resolve()))

        
    try:
        global_ext_dir = Path(DATA_DIR) / "extensions"
        if global_ext_dir.exists():
            for ext_folder in global_ext_dir.iterdir():
                if ext_folder.is_dir() and str(ext_folder.resolve()) not in extension_dirs:
                    extension_dirs.append(str(ext_folder.resolve()))
    except Exception as e:
        print(f"Global extension load err: {e}")
        
    extension_dirs = list(dict.fromkeys(extension_dirs))
    if extension_dirs:
        joined_extensions = ",".join(extension_dirs)
        args.append(f"--disable-extensions-except={joined_extensions}")
        args.append(f"--load-extension={joined_extensions}")
        
    if is_headless:
        pass
        
    from app.browser_settings import get_algo_proxy
    raw_proxy = get_algo_proxy(profile.name)
    if raw_proxy:
        from app.proxy_forwarder import start_forwarder
        local_server = start_forwarder(raw_proxy)
        algo_proxy = {"server": local_server}
    else:
        algo_proxy = None

    try:
        from app.browser_settings import get_global_args
        args.extend(get_global_args(raw_proxy, engine=engine))
    except Exception as e:
        pass
        
    args.append("--remote-debugging-port=0")
    
    # Xoá file port cũ để tránh đọc nhầm
    try:
        active_port_file = Path(runtime_dir) / "DevToolsActivePort"
        if active_port_file.exists(): active_port_file.unlink()
        cdp_file = Path(runtime_dir) / "cdp_port.txt"
        if cdp_file.exists(): cdp_file.unlink()
    except: pass
        
    if engine == "cloakbrowser":
        from cloakbrowser import launch_persistent_context
        # CloakBrowser tự động xử lý extension_paths và ignore_default_args
        cloak_args = [a for a in args if not a.startswith("--load-extension") and not a.startswith("--disable-extensions")]
        cloak_kwargs = {
            "user_data_dir": runtime_dir,
            "headless": False,
            "args": cloak_args,
            "accept_downloads": True,
            "downloads_path": str(Path.home() / "Downloads"),
            "proxy": algo_proxy
        }
        
        if extension_dirs:
            cloak_kwargs["extension_paths"] = extension_dirs
            
        context = launch_persistent_context(**cloak_kwargs)
    else:
        context = p.chromium.launch_persistent_context(
            runtime_dir,
            headless=False,
            proxy=algo_proxy,
            **browser_launch_options(),
            ignore_default_args=ignore_args,
            args=args,
            accept_downloads=True,
            downloads_path=str(Path.home() / "Downloads"),
        )
        
    try:
        import json
        cfg = json.loads((Path(__file__).parent.parent.parent / 'data' / 'config.json').read_text())
        if cfg.get('block_media'):
            def block_media_route(route, request):
                if request.resource_type in ['image', 'media', 'font'] and request.method == 'GET':
                    route.abort()
                else:
                    route.fallback()
            context.route('**/*', block_media_route)
    except: pass

    install_vpn_welcome_guard(context)

    # Chrome tự xử lý download 100% native - Không chặn, không xử lý bằng Playwright để tránh crash/lỗi .crdownload

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


    return context, False

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
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Form đã sẵn sàng (bỏ qua bước tải ảnh)."}
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
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang tải ảnh 1 (Start frame)..."}
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
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": f"Cảnh báo tải ảnh 1: {e}"}

    # ✅ Ảnh 1 đã upload thành công → Giờ mới bật Spoof Canvas an toàn
    if img1_ok:
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Ảnh 1 OK! Đang kích hoạt Spoof Canvas..."}
        _activate_canvas_spoof(context, ext_path)
        page.wait_for_timeout(500)

    # Upload ảnh 2 - End frame (optional)
    if img2_path and Path(img2_path).exists():
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang tải ảnh 2 (End frame)..."}
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

def _prepare_video_network(context, task_id, profile_id, generate_ip):
    if not generate_ip:
        video_tasks[task_id].update(
            vpn_enabled=False,
            message="Sinh IP đang tắt: mở Chrome bằng kết nối hiện tại.",
        )
        print(f"Task {task_id}: Sinh IP OFF - skip 1ClickVPN", flush=True)
        return
    from app.services.vpn_ip import connect_unique_vpn_ip
    video_tasks[task_id].update(
        status="running", vpn_enabled=True,
        message="Đang mở tiện ích 1ClickVPN, chọn quốc gia và kết nối IP..."
    )
    print(f"Task {task_id}: Sinh IP ON - open 1ClickVPN and select IP", flush=True)
    vpn_info = connect_unique_vpn_ip(context, profile_id)
    video_tasks[task_id].update(
        vpn_ip=vpn_info["ip"], vpn_country=vpn_info["country"],
        message=f"Đã kết nối VPN: {vpn_info['country']} — IP {vpn_info['ip']}",
    )


def _existing_generation_status(context):
    """Return an already-running generation label found in the opened profile."""
    for page in list(getattr(context, "pages", [])):
        if page.is_closed():
            continue
        try:
            text = page.locator("body").inner_text(timeout=2500)
        except Exception:
            continue
        for label in ("Generating", "Processing"):
            if any(line.strip() == label for line in text.splitlines()):
                return label
    return None


def run_video_automation(task_id, prompt, media_paths, profile_id, save_path, is_headless=False, enable_ext=False, enable_ext_btn2=False, tg_enabled=False, tg_token="", tg_chat_id="", gen_mode="motion_transfer", engine="chrome", generate_ip=False):
    """Background thread: mở higgsfield.ai, đăng nhập Microsoft, upload ảnh, nhập prompt và tạo video."""
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
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": "Profile not found"}
        return

    if enable_ext:
        ext_path = str((Path(BASE_DIR) / "data" / "extensions" / "fingerprint_spoofer").absolute())
    else:
        ext_path = None
    global GLOBAL_MAX_RETRIES

    video_tasks.setdefault(task_id, {}).update(status="running", message="Đang mở trình duyệt...")
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
        if engine == "cloakbrowser":
            p = None
            context, connected_via_cdp = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=enable_ext_btn2, is_headless=is_headless, engine=engine, generate_ip=generate_ip)
        else:
            with pw_lock:
                p = sync_playwright().start()
            context, connected_via_cdp = _open_browser_with_fp(p, profile, ext_path, attempt=1, enable_ext_btn2=enable_ext_btn2, is_headless=is_headless, engine=engine, generate_ip=generate_ip)

        existing_status = _existing_generation_status(context)
        if existing_status:
            video_tasks[task_id].update(
                status="done",
                existing_generation=True,
                message=f"Đã thấy video đang làm từ trước (trạng thái {existing_status}); đã đóng Chrome, không đổi IP.",
            )
            print(f"Task {task_id}: found existing {existing_status}; close Chrome without VPN", flush=True)
            return
        
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
        # video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang giả lập máy tính hoàn toàn mới (Clear Cookies)..."}
        # ... đoạn code xóa cookie đã bị vô hiệu hóa ...

        # Thêm script tự động đóng popup liên tục
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

        # ── BƯỚC 1: Mở higgsfield.ai/chat ──────────────────────────────────
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang mở higgsfield.ai/ai/video..."}
        page.goto("https://higgsfield.ai/ai/video?model=genjutsu", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        
        # Xử lý trang lỗi "This page is temporarily unavailable"
        try:
            if page.locator("text='This page is temporarily unavailable'").is_visible(timeout=3000):
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "higgsfield bị lỗi tạm thời, đang ấn Refresh..."}
                page.locator("button:has-text('Refresh')").click(timeout=3000)
                page.wait_for_timeout(5000)
        except:
            pass

        def check_popups(pg):
            try:
                pg.evaluate("""() => {
                    // Xóa popup Confirm Age
                    const btns = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                    const confirmBtn = btns.reverse().find(el => el.innerText && (
                        el.innerText.trim() === 'Confirm' || 
                        el.innerText.trim() === 'Xác nhận' ||
                        el.innerText.trim() === 'OK' ||
                        el.innerText.trim() === 'Ok'
                    ));
                    if (confirmBtn) {
                        confirmBtn.click();
                    }
                    
                    // Xóa popup Upgrade Ads
                    const adsCloseBtn = document.querySelector('button.fixed.z-40.rounded-full');
                    if (adsCloseBtn) {
                        adsCloseBtn.click();
                    }
                }""")
            except:
                pass

        # ── BƯỚC 2: Kiểm tra đã login chưa (Dựa vào sự tồn tại của nút Log In) ──
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Kiểm tra trạng thái đăng nhập..."}
        already_logged_in = False
        try:
            # Đợi cho trang load xong và các phần tử ổn định
            try:
                page.wait_for_load_state("load", timeout=10000) # Dùng load thay vì networkidle cho lẹ
            except:
                pass
            
            # ── BƯỚC 2: Kiểm tra đã login chưa (Chờ giao diện load xong chữ 'Use free gens' hoặc nút 'Log In') ──
            is_logged_in = False
            try:
                import re
                # Vòng lặp chờ thông minh (tối đa 15 giây) để React load xong dữ liệu
                for _ in range(30):
                    # 0. Quét xem có Modal Login mở sẵn không
                    try:
                        has_welcome = page.evaluate("""() => {
                            const html = document.body.innerText.toLowerCase();
                            return html.includes('welcome to higgsfield') || html.includes('continue with microsoft') || html.includes('log in to unlock more features');
                        }""")
                        if has_welcome:
                            print("--- Đã thấy bảng Login/Welcome -> Chưa login!")
                            is_logged_in = False
                            break
                    except: pass
                    
                    # 1. Quét tìm chữ "Use free gens" (dấu hiệu chắc chắn đã login)
                    try:
                        # Dùng JS cho chắc vì text có thể nằm rải rác
                        has_free_gens = page.evaluate("() => document.body.innerText.toLowerCase().includes('use free gens')")
                        if has_free_gens:
                            is_logged_in = True
                            print("--- Đã thấy 'Use free gens' -> Đã login!")
                            break
                    except: pass
                    
                    # 2. Quét tìm nút Avatar đã đăng nhập
                    try:
                        avatar_loc = page.locator('button[aria-label="Account menu"], button[aria-haspopup="menu"]').filter(has_not_text=re.compile(r"^(Đăng nhập|Log In|Sign In)$", re.IGNORECASE))
                        if avatar_loc.count() > 0 and avatar_loc.first.is_visible():
                            is_logged_in = True
                            print("--- Đã thấy nút Account menu (Avatar) -> Đã login!")
                            break
                    except: pass

                    # 3. Quét tìm nút Log In (nếu thấy nút này nghĩa là chắc chắn CHƯA login)
                    try:
                        login_btn = page.locator("button, a").filter(has_text=re.compile(r"^(Đăng nhập|Log In|Login|Sign In)$", re.IGNORECASE))
                        if login_btn.count() > 0 and login_btn.first.is_visible():
                            print("--- Đã thấy nút Log In -> Chưa login!")
                            break # Thoát vòng lặp, is_logged_in vẫn là False
                    except: pass
                    
                    page.wait_for_timeout(500)
                    
            except Exception as inner_e:
                print(f"Lỗi soi trạng thái login: {inner_e}")
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
                is_modal_open = page.evaluate("""() => {
                    const html = document.body.innerText.toLowerCase();
                    return html.includes('log in to unlock more features') || html.includes('welcome to higgsfield') || html.includes('continue with microsoft');
                }""")
            except:
                pass
            
            if not is_modal_open:
                # ── BƯỚC 3: Ấn "Đăng nhập" / "Log In" ───────────────────────
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang mở bảng Đăng nhập..."}
                
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

            # ── BƯỚC 4: Ấn "Continue with Microsoft" / "Tiếp tục bằng Microsoft" ──
            try:
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang dò tọa độ nút Microsoft để click thật..."}
                
                # Chờ 3s cho popup có thời gian bung ra hoàn chỉnh
                page.wait_for_timeout(3000)
                
                # Dùng JS lấy tọa độ (x, y, width, height) của nút thay vì click ảo bằng JS (vì JS click ảo bị web bỏ qua)
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
                            
                            # Kiểm tra xem bảng popup đã biến mất chưa (chứng tỏ click ăn, mở popup Microsoft)
                            page.wait_for_timeout(3000)
                            check_still_there = page.evaluate(js_get_rect)
                            if not check_still_there.get("found"):
                                print(f"--- [BƯỚC 4] Đã CLICK THẬT thành công nút Microsoft ở lần thử {i+1}!")
                                success_click = True
                                break
                            else:
                                print(f"--- [BƯỚC 4] Lần {i+1}: Đã ấn chuột vật lý nhưng popup chưa tắt, thử lại...")
                        else:
                            print(f"--- [BƯỚC 4] Lần {i+1}: Chưa thấy nút Microsoft. Có thể do click Log In hụt, đang thử click lại Log In...")
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
                        err_str = str(js_err)
                        if "Execution context was destroyed" in err_str:
                            print(f"--- [BƯỚC 4] Bắt được tín hiệu chuyển trang (Execution context destroyed). Coi như click Microsoft thành công!")
                            success_click = True
                            break
                        print(f"--- [BƯỚC 4] Lỗi JS lần {i+1}: {err_str}")
                    
                    # Ngoài ra, nếu URL đã nhảy sang trang login Microsoft thì cũng coi như thành công
                    if "login.microsoftonline" in page.url or "higgsfield.ai/ai/video" in page.url:
                        print("--- [BƯỚC 4] Đã phát hiện chuyển hướng thành công qua URL!")
                        success_click = True
                        break
                    
                    page.wait_for_timeout(2000)
                
                if not success_click:
                    # CHẶN CHẠY MÙ QUÁNG: Báo lỗi và dừng tiến trình
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": "Lỗi: Quá thời gian chờ nút Continue with Microsoft."}
                    print("====== [LỖI] KHÔNG THỂ ẤN NÚT MICROSOFT, DỪNG TIẾN TRÌNH TRÁNH CHẠY MÙ QUÁNG ======")
                    return
                
                # Đã click thành công, chờ Microsoft Auth xử lý
                page.wait_for_timeout(6000)
            except Exception as e:
                print(f"\n====== LỖI BƯỚC 4 ======\n{str(e)}\n========================\n")
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": f"Lỗi ở bước đăng nhập Microsoft: {str(e)}"}
                return # Ngăn chạy tiếp xuống các bước tạo video

            # ── BƯỚC 5 & 6: Xử lý Xác nhận tuổi (nếu có) và Chờ đăng nhập thành công ──
            video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang chờ đăng nhập hoàn tất..."}
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
                            video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "limit", "message": f"Tài khoản đã bị Limit: {limit_msg}"}
                            print(f"====== [LIMIT] TÀI KHOẢN BỊ GIỚI HẠN: {limit_msg} ======")
                            return
                    except: pass
                    
                    # 1. Quét xem có dialog xác nhận tuổi không, nếu có thì click
                    check_popups(page)
                    
                    # 1.1 Xử lý Login Microsoft nếu nó bắt nhập lại email/mật khẩu hoặc hiện bảng báo/yes
                    try:
                        # Điền form email nếu có
                        email_input = page.locator('input[type="email"], input[name="loginfmt"], input[id="i0116"]')
                        if email_input.count() > 0 and email_input.first.is_visible():
                            p_obj = manager.get_profile(profile_id)
                            if p_obj:
                                ms_acc_file = Path(p_obj.user_data_dir) / "ms_account.txt"
                                if ms_acc_file.exists():
                                    parts = ms_acc_file.read_text(encoding="utf-8").strip().split("|")
                                    if len(parts) >= 2:
                                        print("Đang điền lại email Microsoft vì phiên bị đăng xuất...")
                                        email_input.first.fill(parts[0].strip())
                                        page.wait_for_timeout(1000)
                                        next_btn = page.locator('#idSIButton9, input[type="submit"]')
                                        if next_btn.count() > 0 and next_btn.first.is_visible():
                                            next_btn.first.click()
                                        else:
                                            page.keyboard.press("Enter")
                                        page.wait_for_timeout(3000)
                                        
                                        pwd_input = page.locator('input[type="password"], input[name="passwd"], input[id="i0118"]')
                                        if pwd_input.count() > 0 and pwd_input.first.is_visible():
                                            pwd_input.first.fill(parts[1].strip())
                                            page.wait_for_timeout(1000)
                                            next_btn = page.locator('#idSIButton9, input[type="submit"]')
                                            if next_btn.count() > 0 and next_btn.first.is_visible():
                                                next_btn.first.click()
                                            else:
                                                page.keyboard.press("Enter")
                                            page.wait_for_timeout(4000)
                                            
                        # Click "Có" / "Yes" / "Chấp nhận" / "Looks good" nếu nó hiện ra
                        yes_btn = page.locator('input#idSIButton9, button#idSIButton9, button#acceptButton, input#acceptButton, input[value*="Có"], input[value*="Yes"], input[value*="Chấp nhận"], input[value*="Accept"], input[value*="Trông rất được"], input[value*="Looks good"]')
                        if yes_btn.count() > 0 and yes_btn.first.is_visible():
                            yes_btn.first.click(force=True)
                            print("Clicked Yes / Accept / Stay signed in")
                            page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"Lỗi khi điền lại thông tin MS login: {e}")
                    
                    # 1.2 Xử lý Cloudflare Turnstile.
                    # CAPTCHA verification is intentionally manual.  Clicking
                    # its hidden iframe/input programmatically is unreliable
                    # and attempts to bypass the anti-bot challenge.
                    try:
                        cf_checkbox = page.locator(
                            'input[type="checkbox"][aria-label*="human" i], '
                            'input[type="checkbox"][aria-label*="người" i]'
                        )
                        cf_frame = page.locator(
                            'iframe[src*="challenges.cloudflare.com"], '
                            'iframe[src*="turnstile"], iframe[title*="Cloudflare"]'
                        )
                        if cf_checkbox.count() > 0 or cf_frame.count() > 0:
                            page.bring_to_front()
                            print("Turnstile detected; waiting for manual verification")
                    except Exception:
                        pass
                    
                    # 1.3 Xử lý Quiz
                    cur_url = page.url
                    if "higgsfield.ai/quiz" in cur_url:
                        if not hasattr(page, 'quiz_clicked_options'):
                            page.quiz_clicked_options = set()
                        try:
                            error_toast = page.locator('text="Couldn\'t save your answer"')
                            if error_toast.count() > 0 and error_toast.first.is_visible():
                                page.reload()
                                page.wait_for_timeout(3000)
                        except: pass
                        
                        quiz_options = [
                            "Marketing Studio", "Cinema Studio", "MCP & CLI", "Shorts studio", "Supercomputer", "Canvas",
                            "For personal use", "Video generations", "Viral content", "Beginner", "I'm new to this",
                            "Video", "Visual editing", 
                            "Instagram", "TikTok", "YouTube", "Prompting is hard",
                            "Realistic AI avatars"
                        ]
                        
                        try:
                            page.evaluate("""() => {
                                const allEls = document.querySelectorAll('div, span, h3, p');
                                const targetTexts = [
                                    'Marketing Studio', 'Cinema Studio', 'MCP & CLI', 'Shorts studio', 'Canvas', 'Supercomputer',
                                    'For personal use', 'Viral content', 'Beginner', 'Intermediate', 'Advanced', 'Expert',
                                    'Video', 'Visual editing', 'Instagram', 'TikTok', 'YouTube', 
                                    'I\\'m new to this', 'Prompting is hard', 'Realistic AI avatars', 'Video generations'
                                ];
                                for(let el of allEls) {
                                    const t = (el.innerText || '').trim();
                                    if(targetTexts.includes(t)) {
                                        const clickable = el.closest('button, [role="button"]') || el.closest('div[class*="border"]') || el;
                                        clickable.click();
                                    }
                                }
                            }""")
                            page.wait_for_timeout(1000)
                        except: pass

                        for q_text in quiz_options:
                            if q_text in page.quiz_clicked_options: continue
                            try:
                                locs = page.get_by_text(q_text)
                                if locs.count() > 0 and locs.last.is_visible():
                                    box = locs.last.bounding_box()
                                    if box:
                                        page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                                        page.quiz_clicked_options.add(q_text)
                                        page.wait_for_timeout(500)
                                        cont_btn = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Choose an option"), button:has-text("Submit")').first
                                        if cont_btn.count() > 0 and not cont_btn.first.is_disabled(): break
                            except: pass
                            
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
                                page.wait_for_timeout(1000)
                        except: pass

                    # 1.35. Xử lý popup "Chúng tôi đang cập nhật các điều khoản" (account.live.com/tou/accrue)
                    try:
                        if "account.live.com/tou" in page.url or "tou/accrue" in page.url:
                            tiep_theo_btn = page.locator('button[data-testid="primaryButton"], input[type="submit"][value="Tiếp theo"], input[type="submit"][value="Next"], button:has-text("Tiếp theo"), button:has-text("Next")')
                            if tiep_theo_btn.count() > 0 and tiep_theo_btn.first.is_visible():
                                tiep_theo_btn.first.click()
                                print("Clicked 'Tiếp theo' on Microsoft ToS update page!")
                                page.wait_for_timeout(2000)
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
                    except: pass

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
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "✅ Đăng nhập thành công! Đang chuẩn bị tạo video..."}
                else:
                    if "quiz" in page.url:
                        raise Exception("Trình duyệt kẹt ở Quiz! Vui lòng hoàn thành Quiz bằng tay và thử lại.")
                    raise Exception("Không tìm thấy menu Settings, đăng nhập có thể đã thất bại.")
                    
            except Exception as e:
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": f"Đăng nhập thất bại: {e}"}
                try: context.close()
                except: pass
                return
        else:
            video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "✅ Đã đăng nhập sẵn! Đang chuẩn bị tạo video..."}

        page.wait_for_timeout(1500)

        # ĐỀ PHÒNG WEB TỰ VĂNG (LOGOUT)
        if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Microsoft'))"):
            raise Exception("Tài khoản higgsfield bị văng (Logout) giữa chừng. Vui lòng tắt và CHẠY LẠI profile này!")


        # ĐỀ PHÒNG WEB TỰ VĂNG (LOGOUT)
        if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Microsoft'))"):
            raise Exception("higgsfield_logout")

        # Đóng popup quảng cáo "Plans with up to..." nếu có
        try:
            promo_closed = page.evaluate("""() => {
                // Chỉ tìm và click nút X nếu có chữ "Plans with up to" trên màn hình
                if (!document.body.innerText.includes('Plans with up to')) {
                    return false;
                }
                
                const btns = document.querySelectorAll('button, [role="button"]');
                for (const btn of btns) {
                    const svg = btn.querySelector('svg');
                    if (!svg) continue;
                    const paths = svg.querySelectorAll('path');
                    for (const p of paths) {
                        const d = p.getAttribute('d') || '';
                        if (d.includes('7.75') && d.includes('16.25')) {
                            btn.click();
                            return true;
                        }
                    }
                }
                const overlay = document.querySelector('[data-testid="modal-close"], button[aria-label*="close"], button[aria-label*="Close"]');
                if (overlay && overlay.offsetParent !== null) { overlay.click(); return true; }
                return false;
            }""")
            if promo_closed:
                print("Đã tắt popup quảng cáo Higgsfield!")
                page.wait_for_timeout(500)
        except: pass

        images_uploaded = False
        videos_uploaded = False
        
        for master_attempt in range(3):
            try:
                # ── BƯỚC 8: Upload ảnh & Video theo giao diện MỚI ─────────────────────────────
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
                    # Xử lý modal "Media upload agreement" nếu hiện ra (Non-blocking)
                    try:
                        agree_btn = pg.locator('button:has-text("I agree, continue")')
                        if agree_btn.count() > 0 and agree_btn.first.is_visible():
                            agree_btn.first.click(timeout=1000, force=True)
                            pg.wait_for_timeout(1000)
                            print("  -> Đã click nút 'I agree, continue' (bằng Playwright Locator)")
                            return True
                        
                        clicked = pg.evaluate("""() => {
                            const btns = Array.from(document.querySelectorAll('button'));
                            const btn = btns.find(b => b.innerText && b.innerText.includes('I agree, continue'));
                            if (btn && window.getComputedStyle(btn).display !== 'none') { btn.click(); return true; }
                            return false;
                        }""")
                        if clicked:
                            pg.wait_for_timeout(1000)
                            print("  -> Đã click nút 'I agree, continue' (bằng JS fallback)")
                            return True
                    except Exception as e:
                        print(f"  -> Lỗi khi check modal I agree: {e}")
                    return False

                def upload_and_select(pg, btn_aria_label, file_paths):
                    print(f"--- B?t d?u upload cho {btn_aria_label}, s? lu?ng file: {len(file_paths)}")
                    if not file_paths: return
                    try:
                        # 1. Click vào khu vực Add media (Ảnh hoặc Video)
                        try:
                            keyword = "extract motion" if "video" in btn_aria_label.lower() or "edit" in btn_aria_label.lower() else "Add your characters"
                            
                            # Xây dựng các locator riêng lẻ để ghép lại bằng .or_()
                            loc1 = pg.locator(f'[aria-label*="{keyword}" i]')
                            loc2 = pg.locator(f'[aria-label="{btn_aria_label}" i]')
                            loc3 = pg.locator(f'text="{keyword}"')
                            loc4 = pg.locator(f'text="{btn_aria_label}"')
                            
                            btn = loc1.or_(loc2).or_(loc3).or_(loc4)
                            try:
                                btn.first.wait_for(state="attached", timeout=4000)
                            except:
                                print(f"  -> Chưa tìm thấy nút '{btn_aria_label}', thử đợi thêm 5s...")
                                pg.wait_for_timeout(5000)
                                try:
                                    btn.first.wait_for(state="attached", timeout=2000)
                                except:
                                    if "pricing" in pg.url or "genjutsu" not in pg.url:
                                        print(f"  -> Đang ở nhầm trang ({pg.url}), quay lại trang tạo video...")
                                        pg.goto("https://higgsfield.ai/ai/video?model=genjutsu", timeout=30000)
                                    else:
                                        print("  -> Vẫn không thấy, tiến hành F5 tải lại trang...")
                                        pg.reload(timeout=30000)
                                    pg.wait_for_load_state("domcontentloaded")
                                    pg.wait_for_timeout(5000)
                                    btn.first.wait_for(state="attached", timeout=5000)
                            btn_to_click = btn.first
                        except Exception as e:
                            print(f"  -> Lỗi khi tìm nút upload (đã thử F5): {e}")
                            return
                        
                        # Thử click với expect_file_chooser xem nó có mở trực tiếp không (giao diện mới)
                        try:
                            with pg.expect_file_chooser(timeout=5000) as fc_info:
                                btn_to_click.click(timeout=5000, force=True)
                            fc_info.value.set_files(file_paths)
                            pg.wait_for_timeout(1000)
                            handle_media_upload_modal(pg)
                            print("  -> Tải file thành công trực tiếp từ nút ban đầu!")
                        except:
                            # Nếu timeout, tức là nó chỉ mở Modal (giao diện cũ) hoặc modal agreement
                            print("  -> Nút ban đầu không mở trực tiếp chọn file. Có thể đã mở Modal, tìm nút 'Upload media' bên trong...")
                            handle_media_upload_modal(pg)
                            pg.wait_for_timeout(1000)
                            
                            upload_btn = pg.locator('button[aria-label="Upload media"], button:has-text("Upload media")').last
                            try:
                                upload_btn.wait_for(state="visible", timeout=2000)
                            except:
                                # Fallback UI mới: nút '+' trong grid (không có text)
                                grid_add_btn = pg.locator('div[style*="grid-template-columns"] button').first
                                try:
                                    grid_add_btn.wait_for(state="visible", timeout=2000)
                                    print("  -> Thấy nút '+' trong grid, dùng nút này để upload...")
                                    upload_btn = grid_add_btn
                                except: pass
                            
                            try:
                                with pg.expect_file_chooser(timeout=3000) as fc_info:
                                    upload_btn.click(timeout=5000, force=True)
                                fc_info.value.set_files(file_paths)
                                pg.wait_for_timeout(1000)
                                handle_media_upload_modal(pg)
                            except:
                                print("  -> Intercept file chooser failed (lần 2). Handling modal...")
                                handle_media_upload_modal(pg)
                                with pg.expect_file_chooser(timeout=8000) as fc_info:
                                    upload_btn.click(timeout=5000, force=True)
                                fc_info.value.set_files(file_paths)
                                pg.wait_for_timeout(1000)
                                handle_media_upload_modal(pg)
                    
                        # CỰC KỲ QUAN TRỌNG: Với Video, popup "Edit reference" hiện ra ngay lúc tải lên để bắt Confirm trước!
                        if "video" in btn_aria_label.lower():
                            print("  -> Tải Video: Đang chờ popup Edit reference và nút Confirm xuất hiện...")
                            pg.wait_for_timeout(2000) # Đợi animation của popup
                            try:
                                confirm_btn = pg.locator('button:has-text("Confirm"):visible').last
                                # Thử đợi tối đa 8 giây
                                try:
                                    confirm_btn.wait_for(state="visible", timeout=8000)
                                except:
                                    pass
                            
                                if confirm_btn.is_visible():
                                    print("  -> Thấy nút Confirm của Edit reference, tiến hành bấm...")
                                    confirm_btn.click(timeout=3000, force=True)
                                    pg.wait_for_timeout(2000) # Đợi popup đóng
                                else:
                                    print("  -> Vẫn chưa thấy nút Confirm bằng Locator, thử dùng JS để click Confirm...")
                                    pg.evaluate("""() => {
                                        const btns = Array.from(document.querySelectorAll('button'));
                                        const confirmBtn = btns.find(b => b.innerText && b.innerText.includes('Confirm'));
                                        if (confirmBtn) confirmBtn.click();
                                    }""")
                                    pg.wait_for_timeout(2000)
                            except Exception as inner_e:
                                print(f"  -> Lỗi trong quá trình tìm nút Confirm: {inner_e}")
                        
                        # 3. Chờ quá trình upload xong (Mất chữ Uploading...)
                        try:
                            uploading_indicator = pg.locator('text="Uploading..."').first
                            # Đợi chữ Uploading... xuất hiện trước (đề phòng mạng nhanh/chậm)
                            try:
                                uploading_indicator.wait_for(state="visible", timeout=4000)
                                print("  -> Đang tải file lên (Uploading...), vui lòng chờ...")
                            except:
                                if "video" in btn_aria_label.lower():
                                    print("  -> CẢNH BÁO: Không thấy chữ Uploading hiện ra sau khi Confirm! Có thể click Confirm trượt hoặc lỗi.")
                                pass
                    
                            # Đợi nó biến mất (Tối đa 2 phút)
                            uploading_indicator.wait_for(state="hidden", timeout=120000)
                            print("  -> Đã tải xong (Mất chữ Uploading...)")
                        except Exception as wait_e: 
                            print(f"  -> Lỗi trong lúc chờ Uploading: {wait_e}")
                            pass
                
                        pg.wait_for_timeout(3000) # Đợi thêm tí cho list update mượt mà
                        
                        # Xử lý popup Media upload agreement có thể hiện ra sau khi upload xong
                        handle_media_upload_modal(pg)
                
                        # Kiểm tra lỗi Failed to upload media
                        if pg.locator('text="Failed to upload media"').is_visible(timeout=1000):
                            print("  -> CẢNH BÁO: Bị lỗi 'Failed to upload media'!")
                            raise Exception("ReloadRequired")
                
                        # Xử lý popup Media upload agreement lần nữa cho chắc
                        handle_media_upload_modal(pg)
                        
                        # 4. Chọn các file vừa upload (Click như người thật)
                        print(f"  -> Đang chọn {len(file_paths)} file vừa upload...")
                
                        # Cố gắng đợi thư viện load xong
                        pg.wait_for_timeout(2000)
                
                        # Tìm thẻ video/ảnh vừa tải lên
                        items = pg.locator('div[data-assets-picker-selectable-card="true"]')
                        if items.count() == 0:
                            # Thử locator khác nếu UI thay đổi
                            items = pg.locator('button:has(img), div[role="button"]:has(img), div[role="button"]:has(video), img[alt="Asset"]').first
                    
                        count = items.count()
                        print(f"  -> Tìm thấy {count} phần tử có thể chọn trong thư viện.")
                
                        # Click chọn N file đầu tiên tương ứng số file vừa up
                        if count > 0:
                            for i in range(min(len(file_paths), count)):
                                try:
                                    # 1. Thử dùng Playwright click siêu tốc
                                    try:
                                        items.nth(i).click(timeout=500, force=True)
                                    except: pass
                            
                                    # 2. Thử dùng JS click (không chờ đợi Playwright)
                                    try:
                                        pg.evaluate(f"""() => {{
                                            const els = document.querySelectorAll('div[data-assets-picker-selectable-card="true"]');
                                            if (els[{i}]) els[{i}].click();
                                            else {{
                                                const altEls = document.querySelectorAll('button:has(img), div[role="button"]:has(img), div[role="button"]:has(video), img[alt="Asset"]');
                                                if (altEls[{i}]) altEls[{i}].click();
                                            }}
                                        }}""")
                                    except: pass
                            
                                    # 3. Rê chuột và click vật lý siêu tốc
                                    try:
                                        box = items.nth(i).bounding_box(timeout=500)
                                        if box:
                                            pg.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                                            pg.mouse.down()
                                            pg.wait_for_timeout(50)
                                            pg.mouse.up()
                                    except: pass
                                
                                    print(f"  -> Đã click chọn file thứ {i+1} (Bằng cả JS và Physical)")
                                    pg.wait_for_timeout(300)
                                except Exception as click_err: 
                                    print(f"  -> Lỗi khi click chọn file: {click_err}")
                        else:
                            print("  -> Không tìm thấy phần tử bằng Locator, dùng JS fallback để click file vừa upload...")
                            try:
                                pg.evaluate("""() => {
                                    // Lấy tất cả các button/div có khả năng là thẻ media
                                    const els = Array.from(document.querySelectorAll('button, div[role="button"], div[tabindex="0"], div.cursor-pointer'));
                                    for (let el of els) {
                                        const text = (el.innerText || '').trim();
                                        if (text.includes('Upload media') || text.includes('Sort by')) continue; // Bỏ qua nút upload
                                        // Nếu thẻ có chứa thẻ img, video hoặc hình nền
                                        if (el.querySelector('img') || el.querySelector('video') || el.style.backgroundImage || window.getComputedStyle(el).backgroundImage !== 'none') {
                                            // Chắc chắn nó là thẻ media, tiến hành click
                                            el.click();
                                            return;
                                        }
                                    }
                                }""")
                                pg.wait_for_timeout(2000)
                            except Exception as e:
                                print(f"  -> JS fallback click failed: {e}")
                    
                        # Xử lý popup Media upload agreement có thể hiện ra sau khi click chọn file
                        handle_media_upload_modal(pg)
                        
                        # 4.5. Nếu có nút Select / Apply / Add ở dưới cùng để xác nhận chọn file, thì bấm nó
                        try:
                            select_btn = pg.locator('button:has-text("Select"):visible, button:has-text("Apply"):visible, button:has-text("Add"):visible').first
                            if select_btn.is_visible(timeout=1500):
                                print("  -> Thấy nút Select/Apply/Add sau khi chọn file, tiến hành bấm...")
                                select_btn.click(timeout=2000, force=True)
                                pg.wait_for_timeout(1000)
                        except: pass
                        
                        # 5. Tắt modal upload bằng nút X (nếu có, thường dành cho tải ảnh)
                        try:
                            close_btn = pg.locator('button[aria-label="Close"], button svg.lucide-x').first
                            if close_btn.is_visible(timeout=2000):
                                print("  -> Đóng bảng upload media (bằng nút X)...")
                                close_btn.click()
                                pg.wait_for_timeout(1000)
                        except: pass
                        
                        # Xử lý popup Media upload agreement lần cuối trước khi sang bước sau
                        handle_media_upload_modal(pg)
                
                    except Exception as e:
                        print(f"Lỗi upload {btn_aria_label}: {e}")
                        raise e

                # 1. Chuyển sang Tab đúng dựa trên gen_mode
                try:
                    if gen_mode == "objects_swap":
                        tab = page.locator('button[role="tab"]:has-text("Objects swap")').first
                    else:
                        tab = page.locator('button[role="tab"]:has-text("Motion transfer")').first
                        
                    if tab.is_visible(timeout=2000):
                        tab.click(timeout=3000)
                        page.wait_for_timeout(1000)
                except: pass
                
                # 2. Upload Ảnh (Có cơ chế Retry riêng)
                if images_to_upload and not images_uploaded:
                    for attempt in range(3):
                        try:
                            print(f"=== BẮT ĐẦU UPLOAD ẢNH ({len(images_to_upload)} file) (Lần {attempt+1}) ===")
                            video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": f"Đang tải {len(images_to_upload)} ảnh lên..."}
                            # Web tự hiển thị ảnh mới nhất lên đầu (đảo ngược thứ tự)
                            # -> Đảo ngược list trước khi upload để kết quả cuối đúng thứ tự gốc (1,2,3)
                            upload_and_select(page, "Add reference images", list(reversed(images_to_upload)))
                    
                            # Bấm ra ngoài (để đóng popup nếu có, giúp hiện nút tải video)
                            try:
                                page.mouse.click(10, 10)
                                page.wait_for_timeout(1000)
                            except: pass
                            images_uploaded = True
                            break # Thành công thì thoát loop ảnh
                        except Exception as e:
                            if "ReloadRequired" in str(e):
                                # Raise lên master_attempt để reload và làm lại cả ảnh + video từ đầu
                                print("  -> Lỗi upload ảnh (ReloadRequired), chuyển lên master loop để retry toàn bộ...")
                                raise e
                            raise e

                # 3. Upload Video (Có cơ chế Retry riêng)
                if videos_to_upload and not videos_uploaded:
                    for attempt in range(3):
                        try:
                            if gen_mode == "objects_swap":
                                video_btn_label = "Add a reference video to edit"
                            else:
                                video_btn_label = "Add a reference video to extract motion"
                        
                            print(f"=== BẮT ĐẦU UPLOAD VIDEO ({len(videos_to_upload)} file) (Lần {attempt+1}) ===")
                            video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": f"Đang tải {len(videos_to_upload)} video lên..."}
                            upload_and_select(page, video_btn_label, videos_to_upload)
                            videos_uploaded = True
                            break # Thành công thì thoát loop video
                        except Exception as e:
                            if "ReloadRequired" in str(e):
                                # Raise lên master_attempt để reload và làm lại cả ảnh + video từ đầu
                                # (Không retry nội bộ vì sau reload ảnh bị mất, video vẫn fail)
                                print("  -> Lỗi upload video (ReloadRequired), chuyển lên master loop để retry toàn bộ...")
                                raise e
                            raise e

                # ĐỀ PHÒNG WEB TỰ VĂNG (LOGOUT)
                if "from_logout=1" in page.url or page.evaluate("() => Array.from(document.querySelectorAll('button')).some(b => b.innerText && b.innerText.includes('Continue with Microsoft'))"):
                    raise Exception("Tài khoản higgsfield bị văng (Logout) giữa chừng. Vui lòng tắt và CHẠY LẠI profile này!")
            
                check_popups(page)
                # ── BƯỚC 9: Bật công tắc Prompt và điền ──────────────
                if prompt:
                    print(f"=== ĐIỀN PROMPT: {prompt[:30]}... ===")
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang nhập prompt..."}
                    try:
                        # Bật công tắc "Prompt"
                        prompt_toggle = page.locator('span[aria-label="Toggle prompt"]')
                        if prompt_toggle.is_visible(timeout=3000):
                            if prompt_toggle.get_attribute("aria-checked") == "false":
                                print("  -> Bật công tắc Prompt")
                                prompt_toggle.click(timeout=3000, force=True)
                                page.wait_for_timeout(1000)
                
                        # Điền prompt
                        prompt_input = page.locator('div[aria-label="Prompt"][contenteditable="true"]').last
                        if prompt_input.is_visible(timeout=3000):
                            print("  -> Thấy ô điền Prompt, tiến hành nhập text bằng cách Paste...")
                            prompt_input.click(timeout=3000, force=True)
                            page.wait_for_timeout(500)
                    
                            # Xóa text cũ nếu có
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Backspace")
                            page.wait_for_timeout(200)
                    
                            # Paste bằng clipboard event thẳng vào thẻ (cách an toàn nhất cho Lexical Editor)
                            clean_prompt = prompt.replace("`", "'").replace("\\", "\\\\")
                            page.evaluate(f"""(el) => {{
                                const dt = new DataTransfer();
                                dt.setData('text/plain', `{clean_prompt}`);
                                const event = new ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true, cancelable: true }});
                                el.dispatchEvent(event);
                            }}""", prompt_input.element_handle())
                            page.wait_for_timeout(500)
                    
                            # Nếu paste event không ăn, gõ thêm dấu cách để kích hoạt
                            prompt_input.type(" ")
                            print("  -> Đã Paste Prompt thành công!")
                        else:
                            print("  -> CẢNH BÁO: Không tìm thấy ô nhập Prompt!")
                    except Exception as e:
                        print(f"Lỗi nhập prompt: {e}")

                # Lấy ID của video cũ (trước khi tạo) để tránh nhận diện nhầm
                last_asset_id = page.evaluate("""() => {
                    const firstItem = document.querySelector('#assets-grid > div:first-child');
                    return firstItem ? firstItem.getAttribute('data-asset-id') : "none";
                }""")

                # ── BƯỚC 10: Đổi IP, Kiểm tra Prompt, bật Use free gens và nhấn Generate ──────────────
                print("=== ĐỔI IP, BẬT FREE GENS VÀ NHẤN GENERATE ===")
                
                # Chuyển việc sinh IP sang bước này (sau khi đã upload xong, chuẩn bị Gen)
                if generate_ip:
                    print("  -> Bắt đầu đổi IP trước khi Generate...")
                    _prepare_video_network(context, task_id, profile_id, generate_ip)
                    print("  -> Đổi IP thành công, tải lại trang để nhận IP mới...")
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đã kết nối IP mới, đang tải lại trang..."}
                    page.reload(timeout=30000)
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(5000)
                
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang bật Free gens và nhấn Generate..."}
        
                generate_success = False
                for gen_attempt in range(3):
                    try:
                        # 1. Kiểm tra xem ô Prompt còn text không, nếu mất thì điền lại
                        if prompt:
                            prompt_input = page.locator('div[aria-label="Prompt"][contenteditable="true"]').last
                            if prompt_input.is_visible(timeout=2000):
                                current_text = prompt_input.text_content()
                                if not current_text or len(current_text.strip()) < 2:
                                    print(f"  -> Prompt bị mất (Lần thử {gen_attempt+1}), tiến hành dán lại...")
                                    prompt_input.click(timeout=3000, force=True)
                                    page.wait_for_timeout(200)
                                    page.keyboard.press("Control+A")
                                    page.keyboard.press("Backspace")
                                    page.wait_for_timeout(200)
                                    clean_prompt = prompt.replace("`", "'").replace("\\", "\\\\")
                                    page.evaluate(f"""(el) => {{
                                        const dt = new DataTransfer();
                                        dt.setData('text/plain', `{clean_prompt}`);
                                        const event = new ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true, cancelable: true }});
                                        el.dispatchEvent(event);
                                    }}""", prompt_input.element_handle())
                                    page.wait_for_timeout(500)
                                    prompt_input.type(" ")
                
                        # 2. Bật công tắc Use free gens
                        print(f"  -> Đang tìm công tắc Use free gens (Lần thử {gen_attempt+1})...")
                        free_gens = page.locator('button[aria-label="Use free gens"]')
                        try:
                            free_gens.wait_for(state="visible", timeout=10000)
                            if free_gens.get_attribute("aria-checked") == "false":
                                print(f"  -> Trạng thái đang tắt, tiến hành Bật công tắc Use free gens...")
                                free_gens.click(timeout=3000, force=True)
                                page.wait_for_timeout(1000)
                            else:
                                print(f"  -> Công tắc Use free gens đã được bật sẵn!")
                        except:
                            print(f"  -> Không tìm thấy công tắc Use free gens (có thể tài khoản đã hết free gens hoặc web load chậm).")
                            
                
                        # 3. Nhấn nút Generate như người thật
                        page.wait_for_timeout(1000) # Đợi giao diện ổn định
                        generate_btn = page.locator('button[type="submit"]:has-text("Generate")').last
                        if generate_btn.is_visible(timeout=3000):
                            print(f"  -> Đã thấy nút Generate, tiến hành click (Lần thử {gen_attempt+1})...")
                            try:
                                generate_btn.scroll_into_view_if_needed()
                                page.wait_for_timeout(500)
                                # Click bằng Playwright (có scroll & kiểm tra)
                                generate_btn.click(timeout=3000, force=True)
                            except:
                                print("  -> Click thường bị lỗi, thử click bằng JavaScript...")
                                try:
                                    page.evaluate("(btn) => btn.click()", generate_btn.element_handle())
                                except:
                                    pass
                            page.wait_for_timeout(2000)
                    
                        # 4. Kiểm tra lỗi "Add one source video" sau khi nhấn Generate
                        if page.locator('text="Add one source video"').is_visible(timeout=2000) or \
                           page.locator('text="source video"').is_visible(timeout=1000):
                            print("  -> LỖI TẠO VIDEO: Web báo thiếu 'Add one source video'!")
                            raise Exception("ReloadRequired")
                            
                        if page.locator('text="Something went wrong"').is_visible(timeout=1000) or \
                           page.locator('text="please try again"').is_visible(timeout=1000) or \
                           page.locator('text="Failed to fetch"').is_visible(timeout=1000) or \
                           page.locator('text="Video duration must be between"').is_visible(timeout=1000):
                            print("  -> LỖI TẠO VIDEO: Web báo lỗi (Failed to fetch / Something went wrong / Video duration...)!")
                            # Ném Exception để master loop reload và check history
                            raise Exception("ReloadAndCheck")
                    
                        # 5. Kiểm tra xem có thấy "Processing" không
                        try:
                            print(f"  -> Đang chờ Processing/Generating (lần {gen_attempt+1})...")
                            confirm_generation(page)
                            print("  -> Đã thấy Processing/Generating, video đang được tạo!")
                            generate_success = True
                            break # Thoát vòng lặp retry Generate
                        except Exception as status_error:
                            raise RuntimeError("History: Không thấy Processing/Generating sau khi cập nhật; kiểm tra tác vụ trước khi tạo lại.") from status_error
                    
                    except Exception as e:
                        if "History:" in str(e): raise e
                        if "ReloadRequired" in str(e) or "ReloadAndCheck" in str(e): raise e
                        print(f"Lỗi nhấn Generate (Lần thử {gen_attempt+1}): {e}")
                
                if not generate_success:
                    raise RuntimeError("No Processing/Generating after History refresh; check the submitted job before retrying.")

                break # Thoát vòng lặp master_attempt nếu mọi thứ thành công
            except Exception as e:
                if "ReloadRequired" in str(e) or "ReloadAndCheck" in str(e):
                    print(f"--- Lỗi Upload/Generate, tải lại trang và làm lại từ đầu (Lần {master_attempt+1}/3) ---")
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Bị lỗi web, đang tải lại trang để thử lại..."}
                    page.reload()
                    page.wait_for_load_state('domcontentloaded')
                    page.wait_for_timeout(5000)
                    
                    if "ReloadAndCheck" in str(e):
                        try:
                            print("  -> Kiểm tra xem video có đang được tạo không sau khi tải lại trang...")
                            confirm_generation(page)
                            print("  -> Tuy có thông báo lỗi trước đó, nhưng video ĐÃ ĐƯỢC TẠO VÀ ĐANG PROCESSING!")
                            break # Thành công! Thoát master loop!
                        except:
                            print("  -> Không thấy Processing/Generating, sẽ làm lại từ đầu (bật free và tạo lại)...")
                            pass
                            
                    if master_attempt == 2:
                        raise Exception("Đã thử tải lại trang 3 lần nhưng vẫn thất bại!")
                    continue
                raise e

        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "✅ Đã gửi yêu cầu! Đang chờ higgsfield.ai tạo video..."}

        # ── BƯỚC 11: Đợi video xuất hiện (tối đa 30 phút) ───────────────
        video_url = None
        video_urls = []
        
        import random
        # Random thời gian reload lần tiếp theo (từ 4 đến 7 phút -> 240 đến 420 giây)
        next_reload_target = random.randint(240, 420)
        was_generating = False
        generation_recovery_reload_used = False
        processing_wait_time = 0
        
        for i in range(1800):
            page.wait_for_timeout(1000)
            
            # Kiểm tra thời gian để tải lại trang định kỳ
            if i > 0 and i >= next_reload_target:
                print(f"--- Task {task_id}: Đã chờ {i}s, cập nhật Motion Library → History...")
                video_tasks[task_id]["message"] = "🔄 Đang chuyển Motion Library → History để cập nhật tiến trình..."
                try:
                    refresh_video_history(page)
                    page.wait_for_timeout(5000)
                except Exception as ex:
                    print(f"Lỗi cập nhật History định kỳ: {ex}")
                # Đặt lại mục tiêu reload tiếp theo (thêm 240-420s tính từ i hiện tại)
                next_reload_target = i + random.randint(240, 420)
            
            # Cập nhật log chat
            sync_chat(page)
            
            # CHÚ Ý: Đề phòng web tự văng acc giữa chừng (như lúc đang chờ video)
            if "from_logout=1" in page.url:
                raise Exception("higgsfield_logout")
                
            check_popups(page)
                
            if video_tasks.get(task_id, {}).get("force_stop"):
                print(f"--- Task {task_id} bị force_stop. Thoát vòng lặp chờ video.")
                break
                
            if video_tasks.get(task_id, {}).get("cancel_and_gen_requested"):
                print(f"--- Task {task_id} nhận lệnh Cancel + Gen. Thực thi thao tác...")
                generate_ip_before_cancel = bool(
                    video_tasks[task_id].get("generate_ip_before_cancel")
                )
                video_tasks[task_id]["cancel_and_gen_requested"] = False
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "Đang thao tác Cancel & Gen lại..."}
                
                try:
                    if generate_ip_before_cancel:
                        video_tasks[task_id]["message"] = "Đang sinh IP mới trước khi Cancel + Gen..."
                        from app.services.vpn_ip import connect_unique_vpn_ip
                        vpn_info = connect_unique_vpn_ip(context, profile_id)
                        print(f"Cancel + Gen sinh IP thành công: {vpn_info['ip']} ({vpn_info['country']})")

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
                        page.reload(timeout=30000)
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
                        try:
                            confirm_generation(page)
                            has_processing = True
                        except Exception:
                            has_processing = False

                        if has_processing:
                            print(f"--- Task {task_id} (Cancel+Gen): ✅ Đã thấy thẻ Processing xuất hiện, quá trình tạo bắt đầu thành công!")
                            break
                        else:
                            print(f"--- Task {task_id} (Cancel+Gen): ❌ Chưa thấy thẻ Processing, thử lại quá trình tải trang và ấn Generate...")
                            
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": "✅ Đã Cancel và Generate lại! Đang chờ..."}
                except Exception as ex:
                    print(f"Lỗi khi thực thi Cancel + Gen: {ex}")
                    video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "running", "message": f"⚠️ Lỗi Cancel + Gen: {str(ex)}"}
                
                # Reset i (bộ đếm thời gian) về 0 để chờ thêm 10 phút nữa
                i = 0
                was_generating = False
                processing_wait_time = 0
                continue
            
            try:
                # Quét xem có popup Log In bất ngờ hiện lên không
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
                        if (b.dataset.clicked) return; // Tránh spam click làm crash browser
                        try { 
                            b.dispatchEvent(new MouseEvent('mouseover', {bubbles: true})); 
                            b.click(); // Phải CLICK thì xgplayer mới bơm link vào thẻ <video>
                            b.dataset.clicked = "true";
                        } catch(e){}
                    });
                }""")
                page.wait_for_timeout(1000) # Chờ 1 giây để nó nạp link sau khi click
            except:
                pass

            try:
                eval_res = page.evaluate(f"""() => {{
                    const result = {{ urls: [], status: '' }};
                    // CHỈ lấy video đầu tiên trong danh sách assets-grid (thẻ div chứa video vừa gen xong)
                    const firstItem = document.querySelector('#assets-grid > div:first-child');
                    
                    if (firstItem && firstItem.getAttribute('data-asset-id') !== '{last_asset_id}') {{
                        result.status = firstItem.getAttribute('data-job-status') || '';
                        // Kiểm tra trạng thái completed và đảm bảo không lấy nhầm video cũ
                        if (result.status === 'completed') {{
                            const video = firstItem.querySelector('video');
                            if (video) {{
                                if (video.src && (video.src.startsWith('http') || video.src.startsWith('blob'))) {{
                                    result.urls.push(video.src);
                                }} else {{
                                    const s = video.querySelector('source');
                                    if (s && s.src && (s.src.startsWith('http') || s.src.startsWith('blob'))) {{
                                        result.urls.push(s.src);
                                    }}
                                }}
                            }}
                        }}
                    }}
                    
                    if (result.status !== 'completed') {{
                        const spans = Array.from(document.querySelectorAll('span, div'));
                        if (spans.some(el => el.innerText && el.innerText.trim() === 'Generating')) {{
                            result.status = 'generating';
                        }}
                    }}
                    return result;
                }}""")
                new_url = eval_res.get('urls', [])
                current_job_status = eval_res.get('status', '')
                if new_url and len(new_url) > 0:
                    video_urls = new_url
                    video_url = new_url[0]
                    break
                if was_generating and current_job_status != 'generating' and not generation_recovery_reload_used:
                    generation_recovery_reload_used = True
                    video_tasks[task_id]["message"] = "🔄 Generating biến mất, đang tải lại trang để lấy video..."
                    print(f"--- Task {task_id}: Generating biến mất khi chưa có video; reload để khôi phục kết quả...")
                    page.reload(timeout=30000)
                    page.wait_for_load_state('domcontentloaded')
                    page.wait_for_timeout(5000)
                    continue
                if current_job_status == 'generating':
                    was_generating = True
            except:
                current_job_status = ''
                pass
                
            if current_job_status != 'generating' and not was_generating:
                processing_wait_time += 1
            else:
                processing_wait_time = 0

            processing_timeout = int(video_tasks.get(task_id, {}).get("params", {}).get("processing_timeout", 120))
            if processing_wait_time >= processing_timeout:
                print(f"--- Task {task_id}: Đợi Processing quá {processing_timeout}s mà chưa Generating, tự động Cancel+Gen!")
                video_tasks[task_id]["cancel_and_gen_requested"] = True
                processing_wait_time = 0

            mins = i // 60
            secs = i % 60
            
            base_msg = f"Đang chờ higgsfield.ai tạo video... {mins:02d}:{secs:02d}"
            if video_tasks[task_id].get("message", "").startswith("✅ Đã Cancel") or "Cancel & Gen" in video_tasks[task_id].get("message", ""):
                base_msg = f"✅ Đã Cancel & Gen! Đang chờ video... {mins:02d}:{secs:02d}"
                
            if current_job_status == 'generating':
                video_tasks[task_id]["message"] = f'<span style="color: #c084fc; font-weight: bold;">{base_msg} ( sắp ra rồi nhé )</span>'
            else:
                video_tasks[task_id]["message"] = base_msg

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
                
                # Cập nhật thẻ profile thành "đã ra video"
                try:
                    p_obj = manager.get_profile(profile_id)
                    if p_obj:
                        p_obj.notes = "đã ra video"
                        manager._save()
                except Exception as ex:
                    print(f"Lỗi cập nhật thẻ profile: {ex}")
                
                page.wait_for_timeout(3000)
            except Exception as e:
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": f"Tạo thành công nhưng tải video thất bại: {e}"}
        else:
            if video_tasks.get(task_id, {}).get("force_stop"):
                video_tasks[task_id]["message"] = "Đã hủy tiến trình!"
                # Không set status = done ở đây, để UI tiếp tục cập nhật tiến trình xóa acc
            else:
                video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": "Timeout 10 phút: Video không xuất hiện trên higgsfield.ai."}

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

        try:
            if not connected_via_cdp:
                context.close()
        except: pass

    except Exception as e:
        # Bắt buộc đóng trình duyệt ngay lập tức nếu có lỗi hoặc văng để retry có thể lấy FP mới
        try:
            if not connected_via_cdp:
                context.close()
        except: pass
    
        if "higgsfield_logout" in str(e):
            print(f"--- Bị văng! Báo cho frontend tự động thử lại task {task_id}...")
            video_tasks[task_id] = {**video_tasks.get(task_id, {}), 
                "status": "higgsfield_logout", 
                "message": "Bị văng khỏi tài khoản, đang tự động thử lại bằng vân tay (Fingerprint) Chrome hoàn toàn mới..."
            }
            return
        video_tasks[task_id] = {**video_tasks.get(task_id, {}), "status": "error", "message": f"Lỗi hệ thống: {e}"}

    finally:
        # Tự động xóa ảnh upload sau khi task xong để tiết kiệm dung lượng
        # Nếu đang báo frontend retry thì KHÔNG xóa ảnh
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

