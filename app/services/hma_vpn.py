"""Automate HMA VPN IP rotation using hma_app_switcher.py (Logic nút 6: randomcountry)."""

from __future__ import annotations

import re
import sys
import subprocess
import threading
import ast
import json
import os
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import BASE_DIR, DATA_DIR

HMA_SCRIPT_PATH = Path(BASE_DIR) / "HMA XOAY" / "hma_tool" / "hma_app_switcher.py"
_hma_lock = threading.Lock()
_history_lock = threading.RLock()
HMA_COUNTRY_HISTORY = Path(DATA_DIR) / "hma_country_history.json"


def _country_catalog():
    # Read the switcher's literal lists without importing its Windows UI code.
    tree = ast.parse(HMA_SCRIPT_PATH.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("COUNTRIES", "REGION_COUNTRIES"):
                    values[target.id] = ast.literal_eval(node.value)
    countries = values["COUNTRIES"]
    regions = values["REGION_COUNTRIES"]
    return {"all": countries, **{key: [c for c in countries if c in region] for key, region in regions.items()}}


def _load_history():
    if not HMA_COUNTRY_HISTORY.exists():
        return {}
    data = json.loads(HMA_COUNTRY_HISTORY.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Dữ liệu lịch sử quốc gia HMA không hợp lệ")
    return data


def _save_history(data):
    HMA_COUNTRY_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=HMA_COUNTRY_HISTORY.parent, delete=False) as output:
            temp_path = output.name
            json.dump(data, output, ensure_ascii=False, indent=2)
        os.replace(temp_path, HMA_COUNTRY_HISTORY)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def get_hma_country_history(region="europe"):
    region = str(region or "europe").strip().lower()
    catalog = _country_catalog()
    if region not in catalog:
        raise ValueError("Khu vực HMA không hợp lệ")
    with _history_lock:
        history = _load_history().get(region, {})
        used = history.get("used", {})
        if not isinstance(used, dict):
            raise ValueError("Dữ liệu lịch sử quốc gia HMA không hợp lệ")
        countries = catalog[region]
        return {"region": region, "round": history.get("round", 1),
                "countries": [{"name": name, "used": name in used, "used_at": used.get(name)} for name in countries],
                "used_count": sum(name in used for name in countries), "total": len(countries)}


def is_hma_available() -> bool:
    """Kiểm tra file script hma_app_switcher.py có tồn tại không."""
    return HMA_SCRIPT_PATH.is_file()


def _run_hma_process_once(timeout: int = 90, region: str = "europe", country: str = "") -> dict[str, str]:
    """Thực thi 1 lần đổi IP HMA trong khu vực được chọn."""
    proc = subprocess.run(
        [sys.executable, str(HMA_SCRIPT_PATH), "country", country],
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
    c_match = re.search(r"^Chon:\s*([^\r\n]+)", full_log, re.MULTILINE)
    if c_match:
        country = c_match.group(1).strip()

    if proc.returncode != 0:
        if "Khong tim thay cua so app HMA" in full_log:
            raise RuntimeError("Khong tim thay cua so app HMA VPN. Hay MO app HMA VPN len truoc!")
        raise RuntimeError(f"HMA VPN doi IP that bai (ma thoat {proc.returncode}): {full_log[:200]}")

    if "Khong tim thay quoc gia nao khop" in full_log:
        raise RuntimeError(f"HMA khong tim thay quoc gia phu hop: {full_log[:200]}")

    if not country or country.casefold() != str(c_match.group(1).strip() if c_match else "").casefold():
        raise RuntimeError("HMA chưa xác nhận được quốc gia đã chọn")

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


def rotate_hma_random_country(timeout: int = 90, max_attempts: int = 2, region: str = "europe") -> dict[str, str]:
    """Kích hoạt đổi sang một quốc gia ngẫu nhiên trên app HMA VPN (Logic nút 6).
    Nếu đổi lần 1 không được thì tự động thử lại phát nữa (tối đa max_attempts lần).
    """
    region = str(region or "europe").strip().lower()
    if region not in ("europe", "asia", "all"):
        raise ValueError("Khu vực HMA không hợp lệ: chọn europe, asia hoặc all")
    if not HMA_SCRIPT_PATH.is_file():
        raise FileNotFoundError(f"Khong tim thay script HMA tai: {HMA_SCRIPT_PATH}")

    import time as _t
    attempts = max(1, max_attempts or 1)
    last_error: Exception | None = None

    with _hma_lock:
        for attempt in range(1, attempts + 1):
            if attempt == 1:
                print(f"  [HMA] Chon ngau nhien khu vuc {region} qua HMA VPN (Lan {attempt}/{attempts})...", flush=True)
            else:
                print(f"  [HMA] Thu lai doi quoc gia ngau nhien qua HMA VPN (Lan {attempt}/{attempts})...", flush=True)

            try:
                snapshot = get_hma_country_history(region)
                available = [item["name"] for item in snapshot["countries"] if not item["used"]]
                if not available:
                    raise RuntimeError("Không còn quốc gia khả dụng trong khu vực HMA")
                chosen = random.choice(available)
                print(f"  [HMA] Vong {snapshot['round']}: chon {chosen} ({snapshot['used_count']}/{snapshot['total']} da dung)", flush=True)
                result = _run_hma_process_once(timeout=timeout, region=region, country=chosen)
                with _history_lock:
                    history = _load_history()
                    state = history.setdefault(region, {"round": 1, "used": {}})
                    state.setdefault("used", {})[chosen] = datetime.now(timezone.utc).isoformat()
                    if len(set(state["used"]) & {item["name"] for item in snapshot["countries"]}) >= snapshot["total"]:
                        state["used"] = {}
                        state["round"] = int(state.get("round", 1)) + 1
                    _save_history(history)
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
