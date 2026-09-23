"""Tự cài tiện ích Chrome (extension .crx / thư mục đã giải nén).

- Nhận đường dẫn file `.crx`/`.zip` hoặc thư mục chứa `manifest.json`.
- Mỗi profile có thư mục extensions riêng (không lẫn giữa các profile).
- Có thể cài cho MỘT profile hoặc ÁP CHO TOÀN BỘ profile.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
def _extract(path: Path, dest_dir: Path) -> Path:
    """Giải nén file .crx/.zip vào một thư mục con trong dest_dir."""
    dest_dir = dest_dir / path.stem
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cloakext_"))
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        # Tìm thư mục chứa manifest.json (crx đôi khi bọc một thư mục con).
        src = _find_manifest_root(tmp)
        shutil.move(str(src), str(dest_dir))
        return dest_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_manifest_root(base: Path) -> Path:
    if (base / "manifest.json").exists():
        return base
    for child in base.iterdir():
        if child.is_dir() and (child / "manifest.json").exists():
            return child
    raise ValueError(f"Không tìm thấy manifest.json trong {base.name}")


def resolve_extension_paths(raw: str, profile_dir: Path, install: bool = True) -> list[str]:
    """Trả về danh sách đường dẫn thư mục extension hợp lệ cho một profile.

    Nếu một mục là file .crx/.zip thì tự giải nén vào profile_dir/extensions.
    Nếu là thư mục hợp lệ (có manifest.json) thì dùng trực tiếp.
    """
    out: list[str] = []
    ext_dir = profile_dir / "extensions"
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item:
            continue
            
        low = item.lower()
        ext_id = None
        if "chromewebstore.google.com" in low or "/webstore/" in low:
            import re
            m = re.search(r"/detail/([a-z0-9_]{1,})/([a-zA-Z0-9]{32})", low)
            if m:
                ext_id = m.group(2)
        elif len(item) == 32 and item.isalnum():
            ext_id = item

        if ext_id and ("http" in low or "chromewebstore" in low or len(item) == 32):
            if install:
                try:
                    crx_url = f"https://clients2.google.com/service/update2/crx?response=redirect&prodversion=125.0.0.0&acceptformat=crx2,crx3&x=id%3D{ext_id}%26installsource%3Dondemand%26uc"
                    import tempfile
                    from urllib.request import urlopen, Request
                    req = Request(crx_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urlopen(req, timeout=15) as resp:
                        body = resp.read()
                    if len(body) > 50:
                        tmp_crx = Path(tempfile.mktemp(suffix=".crx"))
                        tmp_crx.write_bytes(body)
                        out.append(str(_extract(tmp_crx, ext_dir)))
                        try:
                            tmp_crx.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                out.append(item)
            continue

        try:
            p = Path(item)
            if p.is_file() and p.suffix.lower() in (".crx", ".zip"):
                if install:
                    try:
                        out.append(str(_extract(p, ext_dir)))
                    except Exception:
                        continue
                else:
                    out.append(item)
            elif p.is_dir():
                if (p / "manifest.json").exists():
                    out.append(str(p))
            elif Path(item + ".crx").is_file():
                if install:
                    try:
                        out.append(str(_extract(Path(item + ".crx"), ext_dir)))
                    except Exception:
                        continue
        except Exception:
            pass
    return out
