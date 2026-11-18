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

from app.core.state import pw_lock, video_tasks, video_tasks_chat, check_video_task_ids, MAX_RETRIES, save_video_tasks_cache
from app.core.config import BASE_DIR, STATIC_DIR, DATA_DIR, PROFILES_FILE
from app.models import ProfileCreate, LaunchRequest, CheckVideoReq, CancelGenReq
from app.manager import manager
from app.browser import launch_profile_with_fallback, close_profile, is_running, list_running
from app.browser_settings import browser_launch_options

router = APIRouter()

class DeleteAccountDirectReq(BaseModel):
    profile_id: str

from app.services.video_gen import run_video_automation
from app.services.video_check import run_check_video_automation
from app.services.account import run_delete_account_automation

import uuid

@router.post("/api/video/create")
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
    # Tự động nạp cấu hình Telegram lưu trên máy nếu form chưa truyền
    try:
        from app.services.telegram import get_telegram_config
        _saved_tg = get_telegram_config()
        if str(telegram_enabled).lower() != "true" and _saved_tg.get("enabled"):
            telegram_enabled = "true"
        if not telegram_token and _saved_tg.get("bot_token"):
            telegram_token = _saved_tg.get("bot_token")
        if not telegram_chat_id and _saved_tg.get("chat_id"):
            telegram_chat_id = _saved_tg.get("chat_id")
    except Exception as _tge:
        pass
    gen_mode = form.get("gen_mode", "motion_transfer")
    browser_engine = form.get("browser_engine", "chrome")
    generate_ip = str(form.get("generate_ip", "true")).strip().lower() == "true"
    generate_hma = str(form.get("generate_hma", "false")).strip().lower() == "true"
    hma_region = str(form.get("hma_region", "europe")).strip().lower()
    if hma_region not in ("europe", "asia", "all"):
        hma_region = "europe"
    processing_timeout = int(form.get("processing_timeout", 120))
    higgs_model = str(form.get("higgs_model", "vip")).strip().lower()

    # Dọn dẹp các task cũ đã chết nhưng còn lưu status running/pending
    now_ts = time.time()
    running_pids = set(list_running().keys())
    for tid, task in list(video_tasks.items()):
        if isinstance(task, dict) and task.get("status") in ["running", "pending"]:
            pid = task.get("params", {}).get("profile_id")
            created_ts = task.get("created_at_ts", 0)
            # Nếu task tạo > 15s mà Chrome không chạy -> task đã chết
            if pid and (now_ts - created_ts > 15) and (pid not in running_pids or not is_running(pid)):
                task["status"] = "error"
                task["message"] = "Đã dừng (Chrome không còn mở)"
                save_video_tasks_cache()
            elif not pid and (now_ts - created_ts > 15):
                task["status"] = "error"
                task["message"] = "Đã dừng"
                save_video_tasks_cache()

    # Lấy danh sách các profile thực sự đang bận
    used_profiles = set()
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            pid = task.get("params", {}).get("profile_id")
            if pid and (pid in running_pids or is_running(pid)):
                used_profiles.add(pid)
    used_profiles.update(running_pids)

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
    task_id = uuid.uuid4().hex[:10]
    
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

    from datetime import datetime
    now_task_time = datetime.now().strftime("%H:%M:%S %d/%m")
    video_tasks[task_id] = {
        "status": "pending", 
        "message": "Đang chuẩn bị...",
        "created_at": now_task_time,
        "created_at_ts": time.time(),
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
            "gen_mode": gen_mode,
            "browser_engine": browser_engine,
            "generate_ip": generate_ip,
            "generate_hma": generate_hma,
            "hma_region": hma_region,
            "media_paths": saved_paths,
            "processing_timeout": processing_timeout,
            "higgs_model": higgs_model,
        }
    }
    save_video_tasks_cache()
    
    # Cập nhật trạng thái profile sang Đang tạo video kèm giờ phút
    if profile_id:
        try:
            from datetime import datetime
            now_str = datetime.now().strftime("%H:%M %d/%m")
            gen_note = f"Đang tạo video ({now_str})"
            if hasattr(manager, "update_notes"):
                manager.update_notes(profile_id, gen_note)
            p_obj = manager.get_profile(profile_id)
            if p_obj:
                p_obj.notes = gen_note
                manager._save()
        except Exception as e:
            print(f"Lỗi cập nhật profile note khi bắt đầu gen: {e}")

    t = threading.Thread(
        target=run_video_automation,
        args=(task_id, prompt, saved_paths, profile_id, save_path, headless_bool, (enable_ext.lower() == "true"), (enable_ext_btn2.lower() == "true"), (telegram_enabled.lower() == "true"), telegram_token, telegram_chat_id, gen_mode, browser_engine, generate_ip),
        kwargs={"generate_hma": generate_hma, "hma_region": hma_region, "higgs_model": higgs_model},
        daemon=True,
    )
    t.start()
    
    return {"ok": True, "task_id": task_id, "profile_id": profile_id}


@router.post("/api/video/check")
def api_check_video(req: CheckVideoReq):
    import uuid
    import threading
    task_id = str(uuid.uuid4())
    video_tasks[task_id] = {
        "status": "pending",
        "message": "Chuẩn bị kiểm tra video...",
        "created_at_ts": time.time(),
        "params": {"profile_id": req.profile_id, "check_task": True, "higgs_model": getattr(req, "higgs_model", "vip")},
    }
    check_video_task_ids.add(task_id)
    def _run_and_cleanup(*args):
        try:
            run_check_video_automation(
                *args,
                cancel_first=req.cancel_first,
                engine=req.engine,
                generate_ip=req.generate_ip,
                higgs_model=getattr(req, "higgs_model", "vip"),
            )
        finally:
            check_video_task_ids.discard(task_id)
    t = threading.Thread(target=_run_and_cleanup, args=(task_id, req.profile_id, req.is_headless), daemon=True)
    t.start()
    return {"ok": True, "task_id": task_id}

@router.post("/api/video/cancel_gen/{task_id}")
def api_cancel_gen_task(task_id: str, payload: dict = Body(default=None)):
    task = video_tasks.get(task_id)
    # Nhận cả task tạo video và task Check video đang điều khiển đúng profile.
    # Task Check không có prompt nhưng vẫn giữ Chrome và vòng poll riêng.
    if task and (
        task.get("params", {}).get("prompt")
        or task_id in check_video_task_ids
        or task.get("params", {}).get("check_task")
    ):
        task["cancel_and_gen_requested"] = True
        task["restart_browser_before_cancel"] = True
        task["generate_ip_before_cancel"] = bool((payload or {}).get("generate_ip"))
        return {"ok": True, "message": "Đã gửi lệnh Cancel + Gen cho tiến trình video"}
    return JSONResponse(status_code=400, content={"ok": False, "message": "Task này không phải tiến trình tạo video hợp lệ."})

@router.post("/api/video/cancel_gen_by_profile/{profile_id}")
def api_cancel_gen_by_profile(profile_id: str, payload: dict = Body(default=None)):
    """Fallback khi UI mất task ID nhưng profile vẫn còn task tạo video đang chạy."""
    candidates = []
    for task_id, task in video_tasks.items():
        params = task.get("params", {}) if isinstance(task, dict) else {}
        if (params.get("profile_id") == profile_id
                and (params.get("prompt") or params.get("check_task"))
                and task.get("status") in {"running", "pending"}):
            candidates.append((task_id, task))
    if not candidates:
        return JSONResponse(status_code=404, content={"ok": False, "message": "Không tìm thấy task video đang chạy của profile này."})
    task_id, task = candidates[-1]
    task["cancel_and_gen_requested"] = True
    task["restart_browser_before_cancel"] = True
    task["generate_ip_before_cancel"] = True
    return {"ok": True, "task_id": task_id, "message": "Đã gửi lệnh Cancel + Gen theo profile"}

@router.post("/api/video/check/stop_all")
def api_stop_all_check_video():
    """Dừng tất cả tiến trình check video đang chạy"""
    stopped = []
    for tid in list(check_video_task_ids):
        if tid in video_tasks:
            video_tasks[tid]["force_stop"] = True
            stopped.append(tid)
    return {"ok": True, "stopped": stopped}

@router.post("/api/video/delete_account_direct")
def api_delete_account_direct(req: DeleteAccountDirectReq):
    import uuid
    import threading
    task_id = str(uuid.uuid4())
    video_tasks[task_id] = {"status": "pending", "message": "Chuẩn bị xóa account..."}
    t = threading.Thread(target=run_delete_account_automation, args=(task_id, req.profile_id), daemon=True)
    t.start()
    return {"ok": True, "task_id": task_id}

@router.post("/api/video/retry/{task_id}")
def retry_video(task_id: str):
    task = video_tasks.get(task_id)
    if not task or "params" not in task:
        from fastapi import HTTPException
        raise HTTPException(404, "Task not found")
    
    p = task["params"]
    video_tasks[task_id]["status"] = "pending"
    video_tasks[task_id]["message"] = "Đang thử lại..."
    video_tasks[task_id].pop("force_stop", None)
    media_paths = list(p.get("media_paths", []))
    if not media_paths:
        if p.get("img1_path"): media_paths.append(p["img1_path"])
        if p.get("img2_path"): media_paths.append(p["img2_path"])

    t = threading.Thread(
        target=run_video_automation,
        args=(task_id, p["prompt"], media_paths, p.get("profile_id"), p.get("save_path"), p.get("is_headless", False), p.get("enable_ext", False), p.get("enable_ext_btn2", False), p.get("tg_enabled", False), p.get("tg_token", ""), p.get("tg_chat_id", ""), p.get("gen_mode", "motion_transfer"), p.get("browser_engine", "chrome"), p.get("generate_ip", False)),
        kwargs={"generate_hma": p.get("generate_hma", False), "hma_region": p.get("hma_region", "europe"), "higgs_model": p.get("higgs_model", "vip")},
        daemon=True
    )
    t.start()
    return {"ok": True}

@router.post("/api/video/stop/{task_id}")
def stop_video(task_id: str):
    if task_id in video_tasks:
        video_tasks[task_id]["force_stop"] = True
    return {"ok": True}

@router.get("/api/video/status/{task_id}")
def video_status(task_id: str):
    task = video_tasks.get(task_id)
    if not isinstance(task, dict):
        return {"status": "not_found"}

    # Nếu Chrome biến mất trong khi tác vụ còn pending/running, không để
    # giao diện giữ spinner vô thời hạn ở bất kỳ bước nào (mở trang/upload/check).
    if task.get("status") in ("pending", "running"):
        now_ts = time.time()
        started_at = float(task.get("created_at_ts") or 0)
        browser_opened_at = float(task.get("browser_opened_at_ts") or 0)
        should_probe_browser = bool(browser_opened_at) or (started_at and now_ts - started_at >= 60)
        if should_probe_browser:
            profile_id = (task.get("params") or {}).get("profile_id")
            profile = manager.get_profile(profile_id) if profile_id else None
            runtime_dirs = []
            if profile and profile.user_data_dir:
                runtime_dirs.append(Path(profile.user_data_dir))
            if profile_id:
                runtime_dirs.append(Path(BASE_DIR) / "data" / "browsers" / f"chrome136_{profile_id}")

            cdp_alive = False
            for runtime_dir in runtime_dirs:
                try:
                    port_file = runtime_dir / "cdp_port.txt"
                    if not port_file.exists():
                        port_file = runtime_dir / "DevToolsActivePort"
                    if not port_file.exists():
                        continue
                    port = port_file.read_text(encoding="utf-8").splitlines()[0].strip()
                    if not port.isdigit():
                        continue
                    from urllib.request import urlopen
                    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                        cdp_alive = response.status == 200
                    if cdp_alive:
                        task["browser_last_seen_ts"] = now_ts
                        break
                except Exception:
                    continue

            if not cdp_alive:
                last_seen_at = float(task.get("browser_last_seen_ts") or 0)
                offline_since = last_seen_at or browser_opened_at or started_at
                offline_grace = 15 if (last_seen_at or browser_opened_at) else 60
            else:
                offline_since = 0
                offline_grace = 0

            if not cdp_alive and offline_since and now_ts - offline_since >= offline_grace:
                task["status"] = "error"
                task["message"] = "Chrome tự đóng giữa chừng; tác vụ kết thúc. Bấm Tạo Video để thử lại."
                task["force_stop"] = True
                task["finished_at_ts"] = now_ts
                if profile and str(profile.notes or "").lower().startswith("đang tạo video"):
                    manager.update_notes(profile_id, "")
                save_video_tasks_cache()
    return task

@router.get("/api/video/download/{task_id}")
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

@router.get("/api/debug/screenshot/{task_id}")
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


@router.get("/api/video/active-tasks")
def get_active_video_tasks():
    """Trả về danh sách các task video đang chạy hoặc vừa hoàn thành gần đây để frontend tự khôi phục sau reload"""
    res = []
    for tid, t in list(video_tasks.items()):
        params = t.get("params", {})
        prof_id = params.get("profile_id", "")
        prof = manager.get_profile(prof_id) if prof_id else None
        res.append({
            "task_id": tid,
            "status": t.get("status", "pending"),
            "message": t.get("message", ""),
            "prompt": params.get("prompt", ""),
            "profile_id": prof_id,
            "profile_name": prof.name if prof else prof_id,
            "higgs_model": params.get("higgs_model", "vip"),
            "gen_mode": params.get("gen_mode", "motion_transfer"),
            "result_urls": t.get("result_urls", []),
            "result_url": t.get("result_url", ""),
            "created_at": t.get("created_at", ""),
            "force_stop": t.get("force_stop", False),
        })
    return res


@router.post("/api/video/clear-stuck-tasks")
def clear_stuck_tasks(payload: dict = Body(default=None)):
    """Giải phóng tất cả các task bị treo hoặc các task không còn Chrome chạy"""
    cleared = []
    running_pids = set(list_running().keys())
    target_prof = (payload or {}).get("profile_id")
    for tid, task in list(video_tasks.items()):
        if isinstance(task, dict) and task.get("status") in ["running", "pending"]:
            pid = task.get("params", {}).get("profile_id")
            if target_prof and pid == target_prof:
                task["status"] = "error"
                task["message"] = "Đã giải phóng bởi người dùng"
                cleared.append(tid)
            elif not pid or pid not in running_pids or not is_running(pid):
                task["status"] = "error"
                task["message"] = "Đã giải phóng tác vụ treo"
                cleared.append(tid)
    save_video_tasks_cache()
    return {"ok": True, "cleared_count": len(cleared)}

class SendToTelegramReq(BaseModel):
    video_url: str = ""
    video_path: str = ""

@router.post("/api/video/send_to_telegram")
def api_send_video_to_telegram_endpoint(req: SendToTelegramReq):
    import urllib.parse
    target_path = req.video_path
    if not target_path and req.video_url:
        parsed = urllib.parse.urlparse(req.video_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "path" in qs:
            target_path = qs["path"][0]
    
    if not target_path or not Path(target_path).exists():
        return JSONResponse(status_code=400, content={"ok": False, "message": "Không tìm thấy file video trên máy!"})
    
    from app.services.telegram import send_video_to_telegram_async, get_telegram_config
    cfg = get_telegram_config()
    if not cfg.get("bot_token") or not cfg.get("chat_id"):
        return JSONResponse(status_code=400, content={"ok": False, "message": "Chưa cấu hình Telegram Bot Token hoặc Chat ID!"})
    
    send_video_to_telegram_async(target_path, cfg.get("bot_token"), cfg.get("chat_id"), caption="🎬 [Higgsfield AI] Gửi thủ công từ giao diện Tool")
    return {"ok": True, "message": "Đang gửi video vào Telegram trong nền!"}
