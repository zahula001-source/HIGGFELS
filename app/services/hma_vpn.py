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


def _run_hma_process_once(timeout: int = 90) -> dict[str, str]:
    """Thực thi 1 lần đổi IP qua HMA script hma_app_switcher.py (randomcountry)."""
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

    # Trích xuất quốc gia ngẫu nhiên đã chọn
    country = ""
    c_match = re.search(r"Quoc gia ngau nhien:\s*([^\r\n]+)", full_log)
    if c_match:
        country = c_match.group(1).strip()

    if proc.returncode != 0:
        if "Khong tim thay cua so app HMA" in full_log:
            raise RuntimeError("Khong tim thay cua so app HMA VPN. Hay MO app HMA VPN len truoc!")
        raise RuntimeError(f"HMA VPN doi IP that bai (ma thoat {proc.returncode}): {full_log[:200]}")

    if "Khong tim thay quoc gia nao khop" in full_log:
        raise RuntimeError(f"HMA khong tim thay quoc gia phu hop: {full_log[:200]}")

    if not new_ip:
        current_match = re.search(r"IP hien tai:\s*([\d\.]+)", full_log)
        curr_ip = current_match.group(1).strip() if current_match else ""
        if "doi xac nhan tren app hoac thu lai" in full_log or not curr_ip:
            raise RuntimeError(f"HMA VPN chua nhan duoc IP moi (IP hien tai: {curr_ip or 'chua xac dinh'})")
        new_ip = curr_ip

    return {
        "status": "ok",
        "ip": new_ip,
        "country": country,
        "output": full_log,
    }


def rotate_hma_random_country(timeout: int = 90, max_attempts: int = 2) -> dict[str, str]:
    """Kích hoạt đổi sang một quốc gia ngẫu nhiên trên app HMA VPN (Logic nút 6).
    Nếu đổi lần 1 không được thì tự động thử lại phát nữa (tối đa max_attempts lần).
    """
    if not HMA_SCRIPT_PATH.is_file():
        raise FileNotFoundError(f"Khong tim thay script HMA tai: {HMA_SCRIPT_PATH}")

    import time as _t
    attempts = max(1, max_attempts or 1)
    last_error: Exception | None = None

    with _hma_lock:
        for attempt in range(1, attempts + 1):
            if attempt == 1:
                print(f"  [HMA] Kich hoat doi quoc gia ngau nhien qua HMA VPN (Lan {attempt}/{attempts})...", flush=True)
            else:
                print(f"  [HMA] Thu lai doi quoc gia ngau nhien qua HMA VPN (Lan {attempt}/{attempts})...", flush=True)

            try:
                result = _run_hma_process_once(timeout=timeout)
                new_ip = result.get("ip", "")
                country = result.get("country", "")
                print(f"  [HMA] Doi IP thanh cong qua HMA (Lan {attempt}): IP {new_ip or 'da doi'} ({country or 'ngau nhien'})", flush=True)
                return result
            except subprocess.TimeoutExpired:
                last_error = RuntimeError(f"HMA VPN doi IP qua thoi gian ({timeout}s)")
                print(f"  [HMA] Lan {attempt} that bai do timeout ({timeout}s).", flush=True)
            except Exception as e:
                last_error = e
                print(f"  [HMA] Lan {attempt} that bai: {e}", flush=True)

            if attempt < attempts:
                print(f"  [HMA] Doi HMA VPN lan {attempt} khong duoc -> Cho 2s va THU LAI LAN {attempt + 1}...", flush=True)
                _t.sleep(2)

        print(f"  [HMA] Da thu {attempts} lan doi HMA VPN nhung deu that bai: {last_error}", flush=True)
        if last_error:
            raise last_error
        raise RuntimeError(f"Doi HMA VPN that bai sau {attempts} lan thu")
