from pathlib import Path
import os

BASE_DIR = Path(__file__).parent.parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
PROFILES_FILE = DATA_DIR / "profiles.json"
