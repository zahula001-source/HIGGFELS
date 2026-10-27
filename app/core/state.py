import threading
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
TASKS_FILE = BASE_DIR / "data" / "video_tasks.json"

pw_lock = threading.Lock()
video_tasks: dict = {}  # task_id -> status/result / "static"
video_tasks_chat: dict = {}
check_video_task_ids = set()

# Settings
MAX_RETRIES = 10

def load_video_tasks_cache():
    global video_tasks
    if TASKS_FILE.exists():
        try:
            data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Khi server vừa bật lên, các task running/pending cũ không thể còn chạy
                for tid, t in data.items():
                    if isinstance(t, dict) and t.get("status") in ["running", "pending"]:
                        t["status"] = "error"
                        t["message"] = "Đã dừng (Server khởi động lại)"
                video_tasks.update(data)
        except Exception as e:
            print("Error loading video_tasks.json:", e)

def save_video_tasks_cache():
    try:
        TASKS_FILE.parent.mkdir(exist_ok=True)
        # Chỉ lưu tối đa 30 task gần nhất để file gọn nhẹ
        items = list(video_tasks.items())[-30:]
        TASKS_FILE.write_text(json.dumps(dict(items), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("Error saving video_tasks.json:", e)

load_video_tasks_cache()

