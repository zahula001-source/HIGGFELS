def _watch_downloads_folder():
    import time, os
    from pathlib import Path
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_magic_ext(filepath):
        try:
            with open(filepath, 'rb') as f:
                data = f.read(256)
            if not data or len(data) < 8: return ''
            b = data[:16]
            if data[:256].find(b'ftyp') >= 0: return '.mp4'
            if b[:3] == b'\xff\xd8\xff': return '.jpg'
            if b[:8] == b'\x89PNG\r\n\x1a\n': return '.png'
            if b[:4] == b'RIFF' and b[8:12] == b'WEBP': return '.webp'
            if b[:6] in (b'GIF87a', b'GIF89a'): return '.gif'
            if b[:4] == b'\x1aE\xdf\xa3': return '.webm'
        except: pass
        return ''

    while True:
        try:
            time.sleep(2)
            now = time.time()
            for f in downloads_dir.iterdir():
                if not f.is_file(): continue
                ext = f.suffix.lower()
                # Kh├┤ng can thiß╗çp nß║┐u file ─æang down hoß║╖c l├á temp
                if ext == '.crdownload' or ext == '.tmp': continue
                # ─É├ú c├│ ─æu├┤i hß╗úp lß╗ç th├¼ bß╗Å qua
                if ext in ('.mp4','.jpg','.png','.webp','.webm','.gif','.jpeg','.avi','.mov','.mkv'): continue
                # Chß╗ë xß╗¡ l├╜ file tß║ío/sß╗¡a trong 15 ph├║t gß║ºn ─æ├óy
                try:
                    if now - f.stat().st_mtime > 900: continue
                except: continue
                
                real_ext = _get_magic_ext(f)
                if real_ext:
                    new_path = f.with_name(f.stem + real_ext)
                    counter = 1
                    while new_path.exists():
                        new_path = f.with_name(f"{f.stem}_{counter}{real_ext}")
                        counter += 1
                    try:
                        f.rename(new_path)
                        print(f"[Watcher] Tß╗▒ ─æß╗Öng ─æß╗òi t├¬n: {f.name} -> {new_path.name}")
                    except PermissionError:
                        pass # File c├│ thß╗â ─æang ─æ╞░ß╗úc Chrome ghi dß╗ƒ, bß╗Å qua chß╗¥ loop sau
                    except Exception as e:
                        pass
        except Exception as e:
            time.sleep(5)
            
