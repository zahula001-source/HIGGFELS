import os
import shutil
import glob
from pathlib import Path

def clean_chrome_profiles(browsers_dir="data/browsers"):
    base_path = Path(browsers_dir)
    if not base_path.exists():
        print(f"Không tìm thấy thư mục {browsers_dir}")
        return

    # Các thư mục rác an toàn để xóa (không làm mất trạng thái đăng nhập)
    cache_folders = [
        "Default/Cache",
        "Default/Code Cache",
        "Default/GPUCache",
        "Default/Service Worker/CacheStorage",
        "Default/Service Worker/ScriptCache",
        "GrShaderCache",
        "ShaderCache",
        "Crashpad",
        "pnacl"
    ]

    total_freed = 0

    print("Bắt đầu dọn dẹp rác (Cache) của các profile...")
    for profile_dir in base_path.glob("profile_*"):
        freed_in_profile = 0
        for cache_path in cache_folders:
            target = profile_dir / cache_path
            if target.exists() and target.is_dir():
                try:
                    # Tính dung lượng
                    size = sum(f.stat().st_size for f in target.glob('**/*') if f.is_file())
                    shutil.rmtree(target)
                    freed_in_profile += size
                except Exception as e:
                    print(f"Không thể xóa {target}: {e}")
        
        if freed_in_profile > 0:
            total_freed += freed_in_profile
            print(f"Đã dọn dẹp {profile_dir.name} - Giải phóng: {freed_in_profile / (1024*1024):.2f} MB")

    print("=" * 40)
    print(f"TỔNG DUNG LƯỢNG GIẢI PHÓNG: {total_freed / (1024*1024*1024):.2f} GB")
    print("=" * 40)

if __name__ == "__main__":
    clean_chrome_profiles()
