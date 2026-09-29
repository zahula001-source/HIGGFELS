import re

with open('app/services/video_check.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update the Processing wait logic
processing_target = '''                if status_info == 'processing':
                    # Trạng thái Processing → chờ
                    generating_start_time = None  # Reset nếu quay lại processing
                    generating_countdown_done = False
                    buffer_countdown_done = False
                    if video_tasks[task_id].get("message", "").startswith("✅ Đã Cancel"):
                        video_tasks[task_id]["message"] = "✅ Đã Cancel & Gen! Đang chờ (Processing)..."
                    else:
                        video_tasks[task_id]["message"] = "Đang chờ video tạo xong (Processing)..."
                    
                    # Cập nhật thẻ thành 'free gen'
                    p_obj = manager.get_profile(profile_id)
                    if p_obj and p_obj.notes != "free gen":
                        p_obj.notes = "free gen"
                        manager._save()
                        
                    page.wait_for_timeout(3000)'''

processing_replacement = '''                if status_info == 'processing':
                    if processing_start_time is None:
                        processing_start_time = now
                    elapsed_proc = now - processing_start_time
                    generating_start_time = None
                    generating_countdown_done = False
                    buffer_countdown_done = False
                    
                    if elapsed_proc >= 480:  # 8 minutes
                        print(f"--- Task {task_id}: Đã chờ Processing 8 phút, tải lại trang để kiểm tra...")
                        video_tasks[task_id]["message"] = "⏳ Đã chờ 8 phút, đang tải lại trang..."
                        try:
                            page.reload()
                            page.wait_for_load_state('domcontentloaded')
                            page.wait_for_timeout(5000)
                        except: pass
                        processing_start_time = time.time()
                        continue
                        
                    if video_tasks[task_id].get("message", "").startswith("✅ Đã Cancel"):
                        video_tasks[task_id]["message"] = f"✅ Đã Cancel & Gen! Đang chờ Processing ({int(elapsed_proc)}s)..."
                    else:
                        video_tasks[task_id]["message"] = f"Đang chờ video tạo xong (Processing... {int(elapsed_proc)}s)"
                    
                    p_obj = manager.get_profile(profile_id)
                    if p_obj and p_obj.notes != "free gen":
                        p_obj.notes = "free gen"
                        manager._save()
                        
                    page.wait_for_timeout(3000)'''

content = content.replace(processing_target, processing_replacement)

generating_target = '''                    elif not buffer_countdown_done:
                        # Hết 15 phút, đếm thêm 5 phút bù
                        extra_elapsed = elapsed - 900
                        remaining = max(0, 300 - extra_elapsed)
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        video_tasks[task_id]["message"] = f"⏳ Thêm chút nữa thôi! Bù giờ còn {mins} phút {secs} giây..."
                        if extra_elapsed >= 300:
                            buffer_countdown_done = True
                    else:
                        # Đã qua 20 phút vẫn chưa ra → vẫn chờ
                        video_tasks[task_id]["message"] = "⏳ Đang chờ video... (có thể mất thêm chút thời gian)"'''

generating_replacement = '''                    else:
                        video_tasks[task_id]["message"] = f"⏳ Đang chờ video... (Đã chờ {int(elapsed // 60)} phút)"'''

content = content.replace(generating_target, generating_replacement)

# Add try/except for the while loop
# First, insert 'processing_start_time = None' before while True
content = content.replace('buffer_countdown_done = False  # Đã qua 5 phút bù chưa\\n            \\n            while True:', 'buffer_countdown_done = False\\n            processing_start_time = None\\n            \\n            while True:')

# Wrap body of while True:
lines = content.split('\\n')
for i, line in enumerate(lines):
    if 'while True:' in line and 'processing_start_time = None' in lines[i-2]:
        start_idx = i
        break

# Find end
for i in range(start_idx + 1, len(lines)):
    if 'page.wait_for_timeout(2000)' in lines[i] and 'else:' in lines[i-3]:
        end_idx = i
        break

new_lines = []
for i in range(start_idx + 1, end_idx + 1):
    new_lines.append('    ' + lines[i])

before = lines[:start_idx + 1]
after = lines[end_idx + 1:]

try_except = ['                try:']
except_block = [
    '                except Exception as ex:',
    '                    err_str = str(ex)',
    '                    if "Execution context was destroyed" in err_str:',
    '                        page.wait_for_timeout(3000)',
    '                        continue',
    '                    elif "Target closed" in err_str or "Browser closed" in err_str or "has been closed" in err_str:',
    '                        print(f"--- Task {task_id}: Trình duyệt đã bị đóng, ngưng chờ video.")',
    '                        video_tasks[task_id]["status"] = "error"',
    '                        video_tasks[task_id]["message"] = "🛑 Trình duyệt đã bị đóng, ngưng chờ video!"',
    '                        return',
    '                    else:',
    '                        print(f"--- Task {task_id}: Lỗi khi kiểm tra video: {ex}")',
    '                        page.wait_for_timeout(3000)',
    '                        continue'
]

final_lines = before + try_except + new_lines + except_block + after

with open('app/services/video_check.py', 'w', encoding='utf-8') as f:
    f.write('\\n'.join(final_lines))

