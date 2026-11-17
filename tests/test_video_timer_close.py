import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import browser
from app.core.state import video_tasks


class VideoTimerCloseTests(unittest.TestCase):
    def test_scheduled_close_does_not_mark_video_task_force_stopped(self):
        task = {"status": "running", "params": {"profile_id": "timer-profile"}}
        video_tasks["timer-task"] = task
        try:
            with patch.object(browser, "profile_lock", return_value=nullcontext()), \
                    patch.object(browser, "running_lock", nullcontext()), \
                    patch.object(browser, "running_browsers", {}), \
                    patch.object(browser, "kill_profile_processes"), \
                    patch("app.services.vpn_ip.release_vpn_ip"):
                result = browser.close_profile("timer-profile", stop_video_tasks=False)

            self.assertEqual(result["status"], "closed")
            self.assertEqual(task["status"], "running")
            self.assertNotIn("force_stop", task)
        finally:
            video_tasks.pop("timer-task", None)


if __name__ == "__main__":
    unittest.main()
