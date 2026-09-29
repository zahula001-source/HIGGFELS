"""
Antidetect Unlimited V4 - Hỗ trợ Cookie BitBrowser + Random Fingerprint + Tabs persistence
"""
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import time

from app.core.config import STATIC_DIR
from app.api.profiles import router as profiles_router
from app.api.video import router as video_router
from app.api.system import router as system_router
from app.utils.file_watcher import _watch_downloads_folder

app = FastAPI(title="Antidetect Unlimited - Camoufox Edition V4", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bao gồm các router
app.include_router(profiles_router)
app.include_router(video_router)
app.include_router(system_router)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def read_root():
    return FileResponse(STATIC_DIR / "index.html")

if __name__ == "__main__":
    # KHỞI CHẠY BACKGROUND WATCHER DOWNLOADS ĐỂ TỰ ĐỘNG ĐỔI ĐUÔI FILE LẠ THÀNH .MP4/.JPG
    threading.Thread(target=_watch_downloads_folder, daemon=True).start()

    print("""
=================================================
║   Antidetect Unlimited V4 - Full Featured      ║
║   ✅ Cookie Import (BitBrowser format)         ║
║   ✅ Random Fingerprint (giữ cookie)           ║
║   ✅ Tabs persistence (đóng mở vẫn còn)        ║
║   ♾️ Unlimited Profiles                        ║
=================================================

-> Truy cập giao diện tại: http://localhost:5333
    """)
    uvicorn.run("main:app", host="0.0.0.0", port=5333, reload=False)
