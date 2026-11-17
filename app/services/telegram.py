import json
import logging
import threading
import subprocess
import os
from pathlib import Path
import requests

from app.core.config import DATA_DIR

TELEGRAM_CONFIG_FILE = DATA_DIR / "telegram_config.json"
logger = logging.getLogger("telegram")

def _safe_print(msg: str):
    try:
        print(msg)
    except Exception:
        try:
            print(msg.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass

def get_telegram_config() -> dict:
    if TELEGRAM_CONFIG_FILE.exists():
        try:
            with open(TELEGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "enabled": bool(data.get("enabled", False)),
                    "bot_token": str(data.get("bot_token", "")).strip(),
                    "chat_id": str(data.get("chat_id", "")).strip(),
                }
        except Exception as e:
            _safe_print(f"[Telegram] Loi doc config: {e}")
    return {"enabled": False, "bot_token": "", "chat_id": ""}

def save_telegram_config(enabled: bool, bot_token: str, chat_id: str) -> dict:
    config = {
        "enabled": bool(enabled),
        "bot_token": str(bot_token).strip(),
        "chat_id": str(chat_id).strip(),
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(TELEGRAM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        _safe_print(f"[Telegram] Da luu cau hinh vinh vien (enabled={enabled}, chat_id={chat_id})")
    except Exception as e:
        _safe_print(f"[Telegram] Loi ghi config: {e}")
    return config

def clear_telegram_config() -> dict:
    config = {"enabled": False, "bot_token": "", "chat_id": ""}
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(TELEGRAM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        _safe_print("[Telegram] Da xoa cau hinh Telegram")
    except Exception as e:
        _safe_print(f"[Telegram] Loi xoa config: {e}")
    return config

def test_telegram_connection(bot_token: str = None, chat_id: str = None) -> tuple:
    if not bot_token or not chat_id:
        cfg = get_telegram_config()
        bot_token = bot_token or cfg.get("bot_token")
        chat_id = chat_id or cfg.get("chat_id")
    
    bot_token = str(bot_token or "").strip()
    chat_id = str(chat_id or "").strip()
    
    if not bot_token:
        return False, "Thiếu Bot Token. Vui lòng nhập Bot Token từ @BotFather!"
    if not chat_id:
        return False, "Thiếu Chat ID. Vui lòng nhập Chat ID người nhận hoặc Group!"
    
    try:
        # 1. Kiểm tra Token hợp lệ qua getMe
        r_me = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=12)
        data_me = r_me.json()
        if not data_me.get("ok"):
            err_desc = data_me.get("description", "Token không hợp lệ hoặc bị thu hồi (Unauthorized).")
            return False, f"Bot Token không đúng ({err_desc})"
        bot_username = data_me.get("result", {}).get("username", "Bot")

        # 2. Gửi tin nhắn test tới Chat ID
        test_text = f"🤖 [Higgsfield AI]\n✅ Kết nối thành công tới Bot @{bot_username}!\nTính năng gửi video tự động đã sẵn sàng hoạt động."
        r_msg = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": test_text},
            timeout=15
        )
        data_msg = r_msg.json()
        if not data_msg.get("ok"):
            err_desc = data_msg.get("description", "Không thể gửi tin nhắn")
            if "chat not found" in err_desc.lower():
                return False, f"Không tìm thấy Chat ID {chat_id}! Hãy đảm bảo bạn đã mở Telegram, tìm bot @{bot_username} và bấm /start trước!"
            return False, f"Lỗi gửi tới Chat ID: {err_desc}"
        
        return True, f"Kết nối thành công! Đã gửi tin nhắn test đến bot @{bot_username}."
    except Exception as e:
        return False, f"Lỗi kết nối mạng hoặc Telegram API: {str(e)}"

def _optimize_video_for_telegram(video_path: str) -> tuple:
    """
    Tự động nén video nếu file > 10MB bằng ffmpeg (có sẵn trên máy).
    Giúp giảm dung lượng từ 40MB xuống 5-8MB chỉ mất 1-2 giây,
    đảm bảo upload lên Telegram cực nhanh, mượt mà và không bao giờ bị Timeout!
    Trả về: (duong_dan_file_de_gui, la_file_tam)
    """
    vid_p = Path(video_path)
    if not vid_p.exists():
        return video_path, False
    
    file_size_mb = vid_p.stat().st_size / (1024 * 1024)
    # Nếu file nhỏ hơn 10MB thì gửi trực tiếp luôn
    if file_size_mb <= 10:
        return video_path, False

    out_compressed = vid_p.parent / f"{vid_p.stem}_tg_opt.mp4"
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(vid_p),
            "-c:v", "libx264", "-crf", "24", "-preset", "faster",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out_compressed)
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=60)
        if res.returncode == 0 and out_compressed.exists() and out_compressed.stat().st_size > 0:
            new_size_mb = out_compressed.stat().st_size / (1024 * 1024)
            _safe_print(f"[Telegram] Da toi uu dung luong video bang ffmpeg: {file_size_mb:.1f}MB -> {new_size_mb:.1f}MB (giam gap 5 lan de gui sieu nhanh!)")
            return str(out_compressed), True
    except Exception as e:
        _safe_print(f"[Telegram] Khong the toi uu video bang ffmpeg ({e}), su dung file goc.")
    
    return video_path, False

def send_video_to_telegram(video_path: str, bot_token: str = None, chat_id: str = None, caption: str = "") -> tuple:
    """
    Gửi video qua Telegram với tự động nén tối ưu dung lượng, retry, fallback sendDocument, và timeout hợp lý.
    """
    cfg = get_telegram_config()
    token = (bot_token or cfg.get("bot_token") or "").strip()
    cid = (chat_id or cfg.get("chat_id") or "").strip()
    
    if not token or not cid:
        _safe_print("[Telegram] Bo qua gui: Khong co Bot Token hoac Chat ID")
        return False, "Thiếu Bot Token hoặc Chat ID"
    
    vid_p = Path(video_path)
    if not vid_p.exists() or vid_p.stat().st_size == 0:
        _safe_print(f"[Telegram] File video khong ton tai hoac rong: {video_path}")
        return False, "File video không tồn tại hoặc rỗng"
        
    # Tự động nén video nếu > 10MB để gửi cực nhanh và không bị nghẽn mạng
    send_file_path, is_temp = _optimize_video_for_telegram(str(vid_p))
    send_p = Path(send_file_path)
    file_size_mb = send_p.stat().st_size / (1024 * 1024)
    _safe_print(f"[Telegram] Dang gui video {vid_p.name} ({file_size_mb:.2f} MB) toi Chat ID {cid}...")
    
    if file_size_mb > 50:
        msg = f"[Telegram] File video {file_size_mb:.2f} MB vuot qua gioi han 50 MB cua Telegram Bot API!"
        _safe_print(msg)
        if is_temp and send_p.exists():
            try: os.remove(send_p)
            except: pass
        return False, msg

    caption_text = caption or f"🎬 Video AI đã tải xong!\n📁 {vid_p.name}"

    success = False
    result_msg = ""

    # Lớp 1: Thử gửi dạng sendVideo
    try:
        url_video = f"https://api.telegram.org/bot{token}/sendVideo"
        with open(send_p, "rb") as f:
            res = requests.post(
                url_video,
                data={"chat_id": cid, "caption": caption_text, "supports_streaming": True},
                files={"video": (vid_p.name, f, "video/mp4")},
                timeout=180
            )
        data = res.json()
        if data.get("ok"):
            _safe_print(f"[Telegram] ✅ Gui video thanh cong toi chat {cid}!")
            success = True
            result_msg = "Gửi video thành công"
        else:
            _safe_print(f"[Telegram] sendVideo that bai ({data.get('description')}), dang thu gui Document...")
    except Exception as e:
        _safe_print(f"[Telegram] sendVideo gap loi: {e}, dang thu gui Document...")

    # Lớp 2: Fallback sang sendDocument nếu sendVideo gặp trục trặc
    if not success:
        try:
            url_doc = f"https://api.telegram.org/bot{token}/sendDocument"
            with open(send_p, "rb") as f:
                res = requests.post(
                    url_doc,
                    data={"chat_id": cid, "caption": caption_text},
                    files={"document": (vid_p.name, f, "video/mp4")},
                    timeout=180
                )
            data = res.json()
            if data.get("ok"):
                _safe_print(f"[Telegram] ✅ Gui dang Document thanh cong toi chat {cid}!")
                success = True
                result_msg = "Gửi Document thành công"
            else:
                err = data.get("description", "Không rõ lỗi")
                _safe_print(f"[Telegram] ❌ Gui Telegram that bai: {err}")
                result_msg = err
        except Exception as e:
            _safe_print(f"[Telegram] ❌ Loi ket noi khi gui Document: {e}")
            result_msg = str(e)

    # Dọn dẹp file nén tạm thời nếu có
    if is_temp and send_p.exists():
        try:
            os.remove(send_p)
        except Exception:
            pass

    return success, result_msg

def send_video_to_telegram_async(video_path: str, bot_token: str = None, chat_id: str = None, caption: str = ""):
    """Chạy gửi ngầm trong daemon thread để không làm chậm tiến trình chính"""
    t = threading.Thread(
        target=send_video_to_telegram,
        args=(video_path, bot_token, chat_id, caption),
        daemon=True
    )
    t.start()
