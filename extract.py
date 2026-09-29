import sys

with open('original_main_utf8.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_func = False
func_lines = []
for line in lines:
    if '@app.post("/api/video/create")' in line:
        in_func = True
        func_lines.append(line)
        continue
    if in_func:
        if line.startswith('@app.') or (line.startswith('def ') and not line.startswith('def api_create_video') and not line.startswith('def create_video')):
            if not line.startswith('def '):
                break
        func_lines.append(line)

with open('create_video_dump.py', 'w', encoding='utf-8') as f:
    f.writelines(func_lines)
print('Dumped create_video')
