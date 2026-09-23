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
from app.models import ProfileCreate, LaunchRequest, CheckVideoReq
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


@router.post("/api/video/check")
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
    video_tasks[task_id].pop("force_stop", None) # Xóa cờ force_stop nếu có    media_paths = p.get("media_paths", [])
    if not media_paths:
        if p.get("img1_path"): media_paths.append(p["img1_path"])
        if p.get("img2_path"): media_paths.append(p["img2_path"])

    t = threading.Thread(target=run_video_automation, args=(task_id, p["prompt"], media_paths, p.get("profile_id"), p.get("save_path"), p.get("is_headless", False), p.get("enable_ext", False), p.get("enable_ext_btn2", False), p.get("tg_enabled", False), p.get("tg_token", ""), p.get("tg_chat_id", "")), daemon=True)
    t.start()
    return {"ok": True}

@router.post("/api/video/stop/{task_id}")
def stop_video(task_id: str):
    if task_id in video_tasks:
        video_tasks[task_id]["force_stop"] = True
    return {"ok": True}

@router.get("/api/video/status/{task_id}")
def video_status(task_id: str):
    return video_tasks.get(task_id, {"status": "not_found"})

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

