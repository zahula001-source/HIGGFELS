@app.post("/api/video/create")
async def create_video(request: Request):
    try:
        form = await request.form()
    except Exception as e:
        return JSONResponse(status_code=400, content={"message": f"Lß╗ùi xß╗¡ l├╜ file upload: {e}", "detail": str(e)})

    prompt = form.get("prompt")
    if not prompt:
        return JSONResponse(status_code=400, content={"message": "Thiß║┐u prompt!"})

    profile_id = form.get("profile_id", "")
    images = form.getlist("images") if "images" in form else []
    
    upload_video = form.get("upload_video")
    if isinstance(upload_video, str): upload_video = None
    
    video_duration = form.get("video_duration", "")
    video_ratio = form.get("video_ratio", "")
    save_path = form.get("save_path", "")
    is_headless = form.get("is_headless", "false")
    enable_ext = form.get("enable_ext", "false")
    enable_ext_btn2 = form.get("enable_ext_btn2", "false")
    telegram_enabled = form.get("telegram_enabled", "false")
    telegram_token = form.get("telegram_token", "")
    telegram_chat_id = form.get("telegram_chat_id", "")

    # Lß║Ñy danh s├ích c├íc profile ─æang bß║¡n
    used_profiles = set()
    for task in video_tasks.values():
        if task.get("status") in ["running", "pending"]:
            used_profiles.add(task.get("params", {}).get("profile_id"))
    for p in list_running():
        used_profiles.add(p["id"])

    if not profile_id:
        # Tß╗▒ ─æß╗Öng g├ín profile rß║únh
        all_profiles = manager.list_profiles()
        free_profiles = [p for p in all_profiles if p.id not in used_profiles]
        if not free_profiles:
            return JSONResponse(status_code=400, content={"message": "Kh├┤ng c├▓n Profile n├áo trß╗æng. Vui l├▓ng tß║ío th├¬m Profile hoß║╖c chß╗¥!"})
        profile_id = free_profiles[0].id
    else:
        # Kiß╗âm tra xem profile ─æ╞░ß╗úc chß╗ìn c├│ ─æang bß║¡n kh├┤ng
        if profile_id in used_profiles:
            return JSONResponse(status_code=400, content={"message": "Profile n├áy ─æang bß║¡n (─æang mß╗ƒ hoß║╖c ─æang tß║ío video kh├íc). Vui l├▓ng chß╗ìn profile kh├íc!"})

    headless_bool = (is_headless.lower() == "true")
    task_id = uuid_module.uuid4().hex[:10]
    
    # Save uploaded images
    upload_dir = Path(BASE_DIR) / "data" / "uploads"
    upload_dir.mkdir(exist_ok=True)
    
    img1_path = ""
    img2_path = ""
    saved_paths = []
    
    if images:
        for idx, img in enumerate(images):
            if img and img.filename:
                ext = Path(img.filename).suffix
                if not ext: ext = ".png"
                path = str(upload_dir / f"{task_id}_img{idx}{ext}")
                with open(path, "wb") as f:
                    f.write(await img.read())
                saved_paths.append(path)
                
    if upload_video and upload_video.filename:
        ext = Path(upload_video.filename).suffix
        if not ext: ext = ".mp4"
        path = str(upload_dir / f"{task_id}_vid{ext}")
        with open(path, "wb") as f:
            f.write(await upload_video.read())
        saved_paths.append(path)
        
    img1_path = saved_paths[0] if len(saved_paths) > 0 else ""
    img2_path = saved_paths[1] if len(saved_paths) > 1 else ""

    video_tasks[task_id] = {
        "status": "pending", 
        "message": "─Éang chuß║⌐n bß╗ï...",
        "params": {
            "prompt": prompt,
            "img1_path": img1_path,
            "img2_path": img2_path,
            "profile_id": profile_id,
            "save_path": save_path,
            "is_headless": headless_bool,
            "enable_ext": (enable_ext.lower() == "true"),
            "enable_ext_btn2": (enable_ext_btn2.lower() == "true"),
            "tg_enabled": (telegram_enabled.lower() == "true"),
            "tg_token": telegram_token,
            "tg_chat_id": telegram_chat_id
        }
    }
    
    t = threading.Thread(target=run_video_automation, args=(task_id, prompt, saved_paths, profile_id, save_path, headless_bool, (enable_ext.lower() == "true"), (enable_ext_btn2.lower() == "true"), (telegram_enabled.lower() == "true"), telegram_token, telegram_chat_id), daemon=True)
    t.start()
    
    return {"ok": True, "task_id": task_id, "profile_id": profile_id}

