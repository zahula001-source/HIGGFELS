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

