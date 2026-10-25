import json
import tempfile
import threading
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.manager import ProfileManager
from app.models import Profile

class FreeGenTagPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_pm_")
        self.data_dir = Path(self.temp_dir.name)
        self.profiles_file = self.data_dir / "profiles.json"
        
        # Tạo sẵn 1 profile mẫu
        sample_profile = {
            "id": "test-p1",
            "name": "User 1",
            "os": "windows",
            "browser": "chromium",
            "proxy": None,
            "notes": "",
            "fingerprint": {"screen": "1920x1080"},
            "user_data_dir": str(self.data_dir / "profile_test-p1"),
            "created_at": "2026-10-25T00:00:00",
            "status": "idle"
        }
        self.profiles_file.write_text(json.dumps([sample_profile]), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_update_notes_persists_to_disk_and_memory(self):
        with patch("app.manager.PROFILES_FILE", self.profiles_file), \
             patch("app.manager.DATA_DIR", self.data_dir), \
             patch("app.manager.BROWSERS_DIR", self.data_dir / "browsers"):
            pm = ProfileManager()
            
            # Cập nhật tag Free Gen
            ok = pm.update_notes("test-p1", "free gen 1 720p")
            self.assertTrue(ok)
            
            # Kiểm tra trong bộ nhớ
            p = pm.get_profile("test-p1")
            self.assertIsNotNone(p)
            self.assertEqual(p.notes, "free gen 1 720p")
            
            # Kiểm tra trực tiếp trên đĩa (file profiles.json)
            disk_data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
            self.assertEqual(disk_data[0]["notes"], "free gen 1 720p")

    def test_update_notes_not_overwritten_by_concurrent_list_profiles(self):
        with patch("app.manager.PROFILES_FILE", self.profiles_file), \
             patch("app.manager.DATA_DIR", self.data_dir), \
             patch("app.manager.BROWSERS_DIR", self.data_dir / "browsers"):
            pm = ProfileManager()
            
            # Giả lập tình huống: Frontend gọi list_profiles() liên tục
            # trong khi background thread thực hiện check Free Gen và update_notes
            stop_event = threading.Event()
            
            def poll_list():
                while not stop_event.is_set():
                    pm.list_profiles()
            
            t = threading.Thread(target=poll_list, daemon=True)
            t.start()
            
            try:
                # Thực hiện cập nhật tag nhiều lần
                for i in range(10):
                    pm.update_notes("test-p1", f"free gen {i} 720p")
                    p = pm.get_profile("test-p1")
                    self.assertEqual(p.notes, f"free gen {i} 720p")
            finally:
                stop_event.set()
                t.join(timeout=2)
            
            # Sau khi dừng, kiểm tra lại đĩa
            disk_data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
            self.assertEqual(disk_data[0]["notes"], "free gen 9 720p")

    def test_check_free_gen_full_flow_updates_notes_and_saves(self):
        import importlib
        import app.api.profiles as profiles_api
        
        with patch("app.manager.PROFILES_FILE", self.profiles_file), \
             patch("app.manager.DATA_DIR", self.data_dir), \
             patch("app.manager.BROWSERS_DIR", self.data_dir / "browsers"):
            pm = ProfileManager()
            
            with patch.object(profiles_api, "manager", pm):
                # Mock page và các hàm phụ trợ
                mock_page = Mock()
                mock_page.url = "https://higgsfield.ai/ai/video?model=genjutsu"
                
                with patch.object(profiles_api, "read_free_gens", return_value={"count": 1, "disabled": False}), \
                     patch.object(profiles_api, "read_quality", return_value="720p"):
                    
                    res = profiles_api.check_free_gen_full_flow(mock_page, "test-p1")
                    self.assertTrue(res)
                    
                    # Kiểm tra notes đã được lưu vào profile trên đĩa
                    disk_data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
                    self.assertEqual(disk_data[0]["notes"], "free gen 1 720p")
                    
                    # Kiểm tra get_profile cũng ra đúng
                    p = pm.get_profile("test-p1")
                    self.assertEqual(p.notes, "free gen 1 720p")

if __name__ == "__main__":
    unittest.main()
