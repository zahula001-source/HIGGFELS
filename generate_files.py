import json
import os
from pathlib import Path

base_dir = Path(r"d:\CODE\higgsfield-VIDEOAI")
with open(base_dir / "refactor_dump.json", "r", encoding="utf-8") as f:
    data = json.load(f)

functions = data["functions"]
routes = data["routes"]
classes = data["classes"]

common_imports = """import asyncio
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
"""

# 1. API: Profiles
profiles_routes = [
    "get_profiles", "create_profile", "delete_profile", "duplicate_profile",
    "launch_profile_endpoint", "toggle_auto_random_fp_endpoint", "close_profile_endpoint",
    "update_profile_name_endpoint", "random_fingerprint", "import_cookies",
    "export_cookies_endpoint", "get_logs", "auto_signup_endpoint", "set_ms_account",
    "set_max_retries"
]
profiles_code = common_imports + "\nrouter = APIRouter()\n\n"
for r in profiles_routes:
    if r in routes:
        profiles_code += routes[r].replace("@app.", "@router.") + "\n\n"

(base_dir / "app/api/profiles.py").write_text(profiles_code, encoding="utf-8")


# 2. API: Video
video_routes = [
    "api_check_video", "api_stop_all_check_video", "api_delete_account_direct",
    "create_video", "retry_video", "stop_video", "video_status", "download_video",
    "get_debug_screenshot"
]
video_code = common_imports + "\nrouter = APIRouter()\n\n"
# Also add the DeleteAccountDirectReq class
if "DeleteAccountDirectReq" in classes:
    video_code += classes["DeleteAccountDirectReq"] + "\n\n"

# In video routes, we need to import the service functions
video_code += "from app.services.video_gen import run_video_automation\n"
video_code += "from app.services.video_check import run_check_video_automation\n"
video_code += "from app.services.account import run_delete_account_automation\n\n"

for r in video_routes:
    if r in routes:
        video_code += routes[r].replace("@app.", "@router.") + "\n\n"

(base_dir / "app/api/video.py").write_text(video_code, encoding="utf-8")


# 3. API: System
system_routes = [
    "get_running", "health", "get_free_profile", "select_folder", "index",
    "get_task_chat", "send_task_chat"
]
system_code = common_imports + "\nrouter = APIRouter()\n\n"
for r in system_routes:
    if r in routes:
        system_code += routes[r].replace("@app.", "@router.") + "\n\n"
(base_dir / "app/api/system.py").write_text(system_code, encoding="utf-8")


# 4. Services: Video Gen
video_gen_funcs = [
    "_open_browser_with_fp", "_activate_canvas_spoof", "_handle_auto_login",
    "_fill_form", "_get_generating_status", "_is_rate_limited",
    "_get_new_video_url", "_send_video_to_telegram", "run_video_automation"
]
video_gen_code = common_imports + "\n"
for f in video_gen_funcs:
    if f in functions:
        video_gen_code += functions[f] + "\n\n"
(base_dir / "app/services/video_gen.py").write_text(video_gen_code, encoding="utf-8")


# 5. Services: Video Check
video_check_funcs = ["run_check_video_automation"]
video_check_code = common_imports + "\n"
for f in video_check_funcs:
    if f in functions:
        video_check_code += functions[f] + "\n\n"
(base_dir / "app/services/video_check.py").write_text(video_check_code, encoding="utf-8")


# 6. Services: Account
account_funcs = ["run_delete_account_automation"]
account_code = common_imports + "\n"
for f in account_funcs:
    if f in functions:
        account_code += functions[f] + "\n\n"
(base_dir / "app/services/account.py").write_text(account_code, encoding="utf-8")


# 7. Utils: File Watcher
watcher_funcs = ["_watch_downloads_folder"]
watcher_code = common_imports + "\n"
for f in watcher_funcs:
    if f in functions:
        watcher_code += functions[f] + "\n\n"
(base_dir / "app/utils/file_watcher.py").write_text(watcher_code, encoding="utf-8")

print("Generated all files in app/")
