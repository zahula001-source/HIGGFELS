import asyncio
import threading
import time
import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Dict
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Body, Request, Form
from fastapi.responses import FileResponse, JSONResponse

from app.core.state import pw_lock, video_tasks, video_tasks_chat, check_video_task_ids, MAX_RETRIES, save_video_tasks_cache
from app.core.config import BASE_DIR, STATIC_DIR, DATA_DIR, PROFILES_FILE
from app.models import ProfileCreate, LaunchRequest
from app.manager import manager
from app.browser import launch_profile_with_fallback, close_profile, is_running, list_running
from app.browser_settings import browser_launch_options

router = APIRouter()

@router.get("/api/running")
def get_running():
    return list_running()

@router.get("/api/health")
def health():
    return {"status": "ok", "profiles": len(manager.list_profiles()), "running": len(list_running())}

@router.get("/api/profiles/free")
def get_free_profile():
    now_ts = time.time()
    running_pids = set(list_running().keys())
    for tid, task in list(video_tasks.items()):
        if isinstance(task, dict) and task.get("status") in ["running", "pending"]:
            pid = task.get("params", {}).get("profile_id")
            created_ts = task.get("created_at_ts", 0)
            if pid and (now_ts - created_ts > 15) and (pid not in running_pids or not is_running(pid)):
                task["status"] = "error"
                task["message"] = "Đã dừng (Chrome không còn mở)"
                save_video_tasks_cache()
            elif not pid and (now_ts - created_ts > 15):
                task["status"] = "error"
                task["message"] = "Đã dừng"
                save_video_tasks_cache()

    used_profiles = set()
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            pid = task.get("params", {}).get("profile_id")
            if pid and (pid in running_pids or is_running(pid)):
                used_profiles.add(pid)
    used_profiles.update(running_pids)
    
    all_profiles = manager.list_profiles()
    free_profiles = [p.id for p in all_profiles if p.id not in used_profiles]
    return {"free_profiles": free_profiles}

@router.get("/api/select-folder")
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

@router.post("/api/config")
async def update_config(req: Request):
    try:
        import json
        config_path = DATA_DIR / "config.json"
        data = await req.json()
        # Readers in browser workers must never see a partly written config.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DATA_DIR, suffix=".tmp", delete=False) as output:
                temp_path = Path(output.name)
                json.dump(data, output, indent=4)
            os.replace(temp_path, config_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/api/config")
def get_config():
    try:
        import json
        config_path = DATA_DIR / "config.json"
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
        return {}
    except:
        return {}

@router.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers={"Cache-Control": "no-store"})
    return {"message": "Antidetect Tool API running. Go to /docs for API docs"}

@router.get("/api/tasks/{task_id}/chat")
def get_task_chat(task_id: str):
    return video_tasks_chat.get(task_id, {"messages": [], "queue": []})

@router.post("/api/tasks/{task_id}/chat")
def send_task_chat(task_id: str, payload: dict = Body(...)):
    if task_id in video_tasks_chat:
        video_tasks_chat[task_id]["queue"].append(payload.get("message", ""))
    return {"ok": True}


@router.get("/api/hma/status")
def get_hma_status():
    from app.services.hma_vpn import is_hma_available
    return {"available": is_hma_available()}


@router.post("/api/hma/rotate")
async def rotate_hma_endpoint():
    from app.services.hma_vpn import rotate_hma_random_country
    try:
        result = await asyncio.to_thread(rotate_hma_random_country)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


