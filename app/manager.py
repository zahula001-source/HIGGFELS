from . import browser_settings
import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from .models import Profile
from .fingerprint import generate_fingerprint

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_FILE = DATA_DIR / "profiles.json"
BROWSERS_DIR = DATA_DIR / "browsers"

class ProfileManager:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        BROWSERS_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "logs").mkdir(exist_ok=True)
        (DATA_DIR / "extensions").mkdir(exist_ok=True)
        if not PROFILES_FILE.exists():
            PROFILES_FILE.write_text("[]", encoding="utf-8")
        self.profiles: List[Profile] = self._load()
        self._cleanup_orphaned_folders()

    def _cleanup_orphaned_folders(self):
        import shutil
        active_ids = {p.id for p in self.profiles}
        if BROWSERS_DIR.exists():
            for d in BROWSERS_DIR.iterdir():
                if d.is_dir() and d.name.startswith("profile_"):
                    # Extract ID from 'profile_xxx'
                    pid = d.name.replace("profile_", "")
                    if pid not in active_ids:
                        try:
                            shutil.rmtree(d)
                        except:
                            pass

    def _load(self) -> List[Profile]:
        try:
            data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
            return [Profile(**p) for p in data]
        except Exception as e:
            print(f"Load error {e}")
            return []

    def _save(self):
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump([p.model_dump() for p in self.profiles], f, ensure_ascii=False, indent=2)

    def _save_fingerprint_file(self, profile: Profile):
        try:
            fp_file = Path(profile.user_data_dir) / "fingerprint.json"
            fp_file.parent.mkdir(parents=True, exist_ok=True)
            # Fix JSON serializable - dung default=str de tranh loi Fingerprint object
            fp_file.write_text(json.dumps(profile.fingerprint, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            print(f"Save fp file error {e}")

    def list_profiles(self) -> List[Profile]:
        return self.profiles

    def get_profile(self, profile_id: str) -> Profile | None:
        for p in self.profiles:
            if p.id == profile_id:
                return p
        return None

    def create_profile(self, name: str, os: str = "windows", browser: str = "chromium", proxy=None, notes=None, fingerprint_preset=True) -> Profile:
        pid = Profile.generate_id()
        # Tao fingerprint don gian, serializable 100%
        fingerprint = {
            "os": os,
            "screen": random.choice(["1920x1080", "2560x1440", "1366x768", "1536x864", "1440x900", "2560x1600"]),
            "gpu": random.choice([
                "ANGLE (Intel, Intel(R) UHD Graphics 630)",
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660)",
                "ANGLE (AMD, AMD Radeon RX 580)"
            ]),
            "navigator": {
                "hardwareConcurrency": random.choice([4,8,12,16]),
                "deviceMemory": random.choice([4,8,16]),
                "platform": {"windows": "Win32", "macos": "MacIntel", "linux": "Linux x86_64"}.get(os, "Win32"),
                "languages": ["en-US", "en"]
            },
            "random_id": random.randint(100000, 999999),
            "created_at": datetime.now().isoformat(),
            "note": "Chrome moi hoan toan"
        }

        if browser == "camoufox" and fingerprint_preset:
            fingerprint = {"os": os, "preset": True, "random_id": fingerprint["random_id"], "screen": fingerprint["screen"], "gpu": fingerprint["gpu"]}

        user_data_dir = str(BROWSERS_DIR / f"profile_{pid}")
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)

        profile = Profile(
            id=pid,
            name=name,
            os=os,
            browser=browser,
            proxy=proxy,
            notes=notes,
            fingerprint=fingerprint,
            user_data_dir=user_data_dir,
            created_at=datetime.now().isoformat(),
            status="idle"
        )
        self.profiles.append(profile)
        self._save()
        self._save_fingerprint_file(profile)
        return profile

    def toggle_auto_random_fp(self, profile_id: str, state: bool) -> bool:
        p = self.get_profile(profile_id)
        if p:
            p.auto_random_fp = state
            self._save()
            return True
        return False

    def delete_profile(self, profile_id: str) -> bool:
        p = self.get_profile(profile_id)
        if not p:
            return False
        import shutil
        try:
            if os.path.exists(p.user_data_dir):
                shutil.rmtree(p.user_data_dir)
        except:
            pass
        self.profiles = [x for x in self.profiles if x.id != profile_id]
        self._save()
        return True

    def update_last_used(self, profile_id: str):
        p = self.get_profile(profile_id)
        if p:
            p.last_used = datetime.now().isoformat()
            self._save()

    def duplicate_profile(self, profile_id: str) -> Profile | None:
        src = self.get_profile(profile_id)
        if not src:
            return None
        return self.create_profile(
            name=f"{src.name} - copy",
            os=src.os,
            browser=src.browser,
            proxy=src.proxy,
            notes=src.notes
        )

    def randomize_fingerprint(self, profile_id: str) -> Profile | None:
        p = self.get_profile(profile_id)
        if not p:
            return None
        
        new_os = random.choice(["windows", "macos", "linux"]) if random.random() > 0.7 else (p.os if p.os != "random" else "windows")

        new_fp = {
            "os": new_os,
            "screen": random.choice(["1920x1080", "2560x1440", "1366x768", "1536x864", "2560x1600", "1440x900"]),
            "gpu": random.choice([
                "ANGLE (Intel, Intel(R) UHD Graphics 630)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060)",
                "ANGLE (AMD, AMD Radeon RX 580)",
                "ANGLE (Apple, Apple M1, OpenGL 4.1)"
            ]),
            "navigator": {
                "hardwareConcurrency": random.choice([4,8,12,16]),
                "deviceMemory": random.choice([4,8,16]),
                "platform": {"windows": "Win32", "macos": "MacIntel", "linux": "Linux x86_64"}.get(new_os, "Win32"),
                "languages": ["en-US", "en"]
            },
            "randomized_at": datetime.now().isoformat(),
            "random_id": random.randint(100000, 999999),
            "note": "Randomized - may moi hoan toan"
        }
        
        if p.browser == "camoufox":
            new_fp = {"os": new_os, "preset": True, "random_id": new_fp["random_id"], "randomized_at": new_fp["randomized_at"], "screen": new_fp["screen"]}

        p.fingerprint = new_fp
        p.os = new_os
        self._save()
        self._save_fingerprint_file(p)
        return p

    def import_cookies(self, profile_id: str, cookies_data):
        p = self.get_profile(profile_id)
        if not p:
            return None
        
        if isinstance(cookies_data, str):
            try:
                cookies_data = json.loads(cookies_data)
            except:
                return {"error": "Cookie JSON khong hop le"}
        
        if not isinstance(cookies_data, list):
            return {"error": "Cookie phai la array"}
        
        cookie_file = Path(p.user_data_dir) / "imported_cookies.json"
        normalized = []
        for c in cookies_data:
            try:
                domain = c.get("domain", "")
                if "[" in domain and "]" in domain:
                    import re
                    m = re.search(r'\[(.*?)\]', domain)
                    if m:
                        domain = m.group(1)
                item = {
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "domain": domain,
                    "path": c.get("path", "/"),
                }
                if c.get("expires"):
                    try:
                        item["expires"] = int(float(c["expires"]))
                    except:
                        pass
                if "httpOnly" in c:
                    item["httpOnly"] = c["httpOnly"]
                if "secure" in c:
                    item["secure"] = c["secure"]
                if c.get("url"):
                    item["url"] = c["url"]
                if item["name"] and item["value"]:
                    normalized.append(item)
            except:
                continue
        
        cookie_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        backup_file = DATA_DIR / f"cookies_backup_{profile_id}.json"
        backup_file.write_text(json.dumps(cookies_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        
        return {"imported": len(normalized), "total": len(cookies_data), "file": str(cookie_file)}

manager = ProfileManager()
