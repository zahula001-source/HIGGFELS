import os
import sys
import urllib.request
import zipfile
import tempfile
import shutil
from pathlib import Path

EXTENSIONS = [
    "fjoaledfpmneenckfbpdfhkmimnjocfa",
    "cjmmdfeeeeefpgcnkfdakgpcdjbanpin",
    "fhhhgkkoemddgkeooalbffcmcknlombc",
    "bihmplhobchoageeokmgbdihknkjbknd",
]

DATA_DIR = Path(r"d:\CODE\higgsfield-VIDEOAI\data\extensions")
DATA_DIR.mkdir(parents=True, exist_ok=True)

for ext_id in EXTENSIONS:
    ext_dir = DATA_DIR / ext_id
    if ext_dir.exists():
        print(f"Extension {ext_id} already exists. Skipping.")
        continue
    
    url = f"https://clients2.google.com/service/update2/crx?response=redirect&prodversion=100.0.0.0&acceptformat=crx2,crx3&x=id%3D{ext_id}%26uc"
    print(f"Downloading {ext_id}...")
    
    try:
        tmp_crx = tempfile.mktemp(suffix=".crx")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        with urllib.request.urlopen(req) as response, open(tmp_crx, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
            
        print(f"Extracting {ext_id}...")
        with zipfile.ZipFile(tmp_crx, 'r') as zip_ref:
            zip_ref.extractall(ext_dir)
            
        os.remove(tmp_crx)
        print(f"Successfully installed {ext_id}")
    except Exception as e:
        print(f"Failed to install {ext_id}: {e}")
