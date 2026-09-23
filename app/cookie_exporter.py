import os
import json
import base64
import sqlite3
import shutil
from pathlib import Path
try:
    import win32crypt
    from Crypto.Cipher import AES
except ImportError:
    pass

def get_encryption_key(local_state_path):
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.loads(f.read())
    
    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    # Remove DPAPI prefix
    encrypted_key = encrypted_key[5:]
    
    # Decrypt key using Windows DPAPI
    decrypted_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    return decrypted_key

def decrypt_data(data, key):
    try:
        if data.startswith(b'v10') or data.startswith(b'v11'):
            iv = data[3:15]
            ciphertext = data[15:-16]
            tag = data[-16:]
            cipher = AES.new(key, AES.MODE_GCM, iv)
            dec = cipher.decrypt_and_verify(ciphertext, tag)
            try:
                return dec.decode('utf-8')
            except UnicodeDecodeError:
                # Chromium 130+ App-Bound Encryption prepends 32 bytes of binary data
                return dec[32:].decode('utf-8', errors='ignore')
        elif data:
            return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1].decode('utf-8')
        return ""
    except Exception as e:
        return f"ERROR_DECRYPT:{type(e).__name__}:{e}"

def export_all_cookies(profiles, target_dir=None):
    """Xuất cookies của tất cả các profile ra 2 file: 1 file chứa cookies, 1 file chứa tên.
    Trả về: (số lượng profile thành công, [đường_dẫn_file1, đường_dẫn_file2])"""
    
    cookie_lines = []
    profile_names = []
    
    count = 0
    for p in profiles:
        # Check if p is a Pydantic model or dict
        dir_val = getattr(p, "user_data_dir", None)
        if not dir_val and isinstance(p, dict):
            dir_val = p.get("user_data_dir")
        if not dir_val:
            dir_val = getattr(p, "dir", "")
        dir_path = Path(dir_val)
        local_state_path = dir_path / "Local State"
        cookie_db_path = dir_path / "Default" / "Network" / "Cookies"
        
        # Nếu thư mục/file chưa tồn tại (chưa từng mở) -> bỏ qua
        if not local_state_path.exists() or not cookie_db_path.exists():
            continue
            
        try:
            key = get_encryption_key(local_state_path)
            
            # Copy file DB ra để tránh bị lock nếu trình duyệt đang mở
            temp_db = dir_path / "temp_cookie_export.db"
            shutil.copy2(cookie_db_path, temp_db)
            
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT host_key, path, is_secure, expires_utc, name, value, encrypted_value FROM cookies WHERE host_key LIKE '%dola.com%'")
            
            cookie_strs = []
            netscape_cookies = []
            
            for host_key, path, is_secure, expires_utc, name, value, encrypted_value in cursor.fetchall():
                decrypted_val = value
                if encrypted_value:
                    decrypted = decrypt_data(encrypted_value, key)
                    if decrypted:
                        decrypted_val = decrypted
                
                if decrypted_val is None:
                    decrypted_val = ""
                decrypted_val = str(decrypted_val).replace("\r", "").replace("\n", "").replace("\t", "%09")
                
                # Format cũ
                cookie_strs.append(f"{name}={decrypted_val}")
                
                # Format Netscape
                domain = host_key
                include_sub = "TRUE" if domain.startswith(".") else "FALSE"
                secure = "TRUE" if is_secure else "FALSE"
                # Convert Chrome Webkit timestamp to Unix epoch
                unix_ts = 0
                if expires_utc > 0:
                    unix_ts = max(0, int((expires_utc / 1000000) - 11644473600))
                
                netscape_cookies.append(f"{domain}\t{include_sub}\t{path}\t{secure}\t{unix_ts}\t{name}\t{decrypted_val}")
                
            conn.close()
            os.remove(temp_db)
            
            # Gom chung lại thành 1 dòng cho profile này
            if cookie_strs:
                full_cookie = "; ".join(cookie_strs)
                cookie_lines.append((p.name, full_cookie, netscape_cookies))
                profile_names.append(p.name)
                count += 1
                
        except Exception as e:
            continue
            
    if not count:
        raise Exception("Không tìm thấy cookies hợp lệ nào (có thể các profile chưa từng mở lên hoặc chưa đăng nhập).")
        
    if target_dir:
        cwd = Path(target_dir)
    else:
        cwd = Path(os.getcwd())
        
    cookie_file = cwd / "cookies_list.txt"
    name_file = cwd / "profiles_list.txt"
    netscape_dir = cwd / "Netscape_Cookies"
    netscape_dir.mkdir(exist_ok=True)
    
    all_cookie_strs = []
    
    ns_content = [
        "# Netscape HTTP Cookie File",
        "# https://curl.haxx.se/rfc/cookie_spec.html",
        "# This is a generated file! Do not edit.",
        ""
    ]
    
    for name, c_str, netscape_lines in cookie_lines:
        all_cookie_strs.append(c_str)
        if netscape_lines:
            # Ghi file riêng lẻ cho từng profile để test
            safe_name = "".join(c.strip() for c in name if c.isalnum() or c in " _-")
            single_ns_file = netscape_dir / f"{safe_name}_GETcookies.txt"
            with open(single_ns_file, "w", encoding="utf-8") as f:
                single_content = [
                    "# Netscape HTTP Cookie File",
                    "# https://curl.haxx.se/rfc/cookie_spec.html",
                    "# This is a generated file! Do not edit.",
                    ""
                ] + netscape_lines
                f.write("\n".join(single_content))
                
            ns_content.extend(netscape_lines)
            
    # Lưu ra 1 file duy nhất cho tất cả các profile (Dạng Netscape)
    ns_file = netscape_dir / "ALL_PROFILES_GETcookies_dola.txt"
    with open(ns_file, "w", encoding="utf-8") as f:
        f.write("\n".join(ns_content))
    
    with open(cookie_file, "w", encoding="utf-8") as f:
        # Cách nhau bằng 1 dòng trắng như yêu cầu
        f.write("\n\n".join(all_cookie_strs))
        
    with open(name_file, "w", encoding="utf-8") as f:
        # Tên profile ngăn cách nhau bằng dấu phẩy
        f.write(",".join(profile_names))
        
    return count, [str(cookie_file), str(name_file), str(netscape_dir)]
