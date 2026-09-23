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

router = APIRouter()

@router.get("/api/running")
def get_running():
    return list_running()

@router.get("/api/health")
def health():
    return {"status": "ok", "profiles": len(manager.list_profiles()), "running": len(list_running())}

@router.get("/api/profiles/free")
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

@router.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Antidetect Tool API running. Go to /docs for API docs"}

@router.get("/api/tasks/{task_id}/chat")
def get_task_chat(task_id: str):
    return video_tasks_chat.get(task_id, {"messages": [], "queue": []})

@router.post("/api/tasks/{task_id}/chat")
def send_task_chat(task_id: str, payload: dict = Body(...)):
    if task_id in video_tasks_chat:
        video_tasks_chat[task_id]["queue"].append(payload.get("message", ""))
    return {"ok": True}

