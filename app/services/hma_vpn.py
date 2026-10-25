"""Automate HMA VPN IP rotation using hma_app_switcher.py (Logic nút 6: randomcountry)."""

from __future__ import annotations

import re
import sys
import subprocess
import threading
from pathlib import Path

from app.core.config import BASE_DIR

HMA_SCRIPT_PATH = Path(BASE_DIR) / "HMA XOAY" / "hma_tool" / "hma_app_switcher.py"
_hma_lock = threading.Lock()


def is_hma_available() -> bool:
    """Kiểm tra file script hma_app_switcher.py có tồn tại không."""
    return HMA_SCRIPT_PATH.is_file()


def rotate_hma_random_country(timeout: int = 90) -> dict[str, str]:
    """Kích hoạt đổi sang một quốc gia ngẫu nhiên trên app HMA VPN (Logic nút 6)."""
    if not HMA_SCRIPT_PATH.is_file():
        raise FileNotFoundError(f"Không tìm thấy script HMA tại: {HMA_SCRIPT_PATH}")

    with _hma_lock:
        print("  [HMA] Kích hoạt đổi quốc gia ngẫu nhiên qua HMA VPN (Logic nút 6)...", flush=True)
        try:
            proc = subprocess.run(
                [sys.executable, str(HMA_SCRIPT_PATH), "randomcountry"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            out = proc.stdout or ""
            err = proc.stderr or ""
            full_log = (out + "\n" + err).strip()

            # Trích xuất IP mới nếu có trong output
            new_ip = ""
            ip_match = re.search(r"IP moi:\s*([\d\.]+)", full_log)
            if ip_match:
                new_ip = ip_match.group(1).strip()
            else:
                current_match = re.search(r"IP hien tai:\s*([\d\.]+)", full_log)
                if current_match:
                    new_ip = current_match.group(1).strip()

            # Trích xuất quốc gia ngẫu nhiên đã chọn
            country = ""
            c_match = re.search(r"Quoc gia ngau nhien:\s*([^\r\n]+)", full_log)
            if c_match:
                country = c_match.group(1).strip()

            if proc.returncode != 0:
                if "Khong tim thay cua so app HMA" in full_log:
                    raise RuntimeError("Không tìm thấy cửa sổ app HMA VPN. Hãy MỞ app HMA VPN lên trước!")
                raise RuntimeError(f"HMA VPN đổi IP thất bại: {full_log[:200]}")

            print(f"  [HMA] Đổi IP thành công qua HMA: IP {new_ip or 'đã đổi'} ({country or 'ngẫu nhiên'})", flush=True)
            return {
                "status": "ok",
                "ip": new_ip,
                "country": country,
                "output": full_log,
            }
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"HMA VPN đổi IP quá thời gian ({timeout}s)")
        except Exception as e:
            print(f"  [HMA] Lỗi đổi IP HMA: {e}", flush=True)
            raise
