import threading

pw_lock = threading.Lock()
video_tasks: dict = {}  # task_id -> status/result / "static"
video_tasks_chat: dict = {}
check_video_task_ids = set()

# Settings
MAX_RETRIES = 10
