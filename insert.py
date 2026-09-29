import re

with open('original_main.py', 'r', encoding='utf-16') as f:
    text = f.read()

match = re.search(r'(@app\.post\("/api/video/create"\).*?)(?=@app\.)', text, re.DOTALL)
if match:
    func_code = match.group(1).replace('@app.post', '@router.post').replace('uuid_module', 'uuid')
    
    with open('app/api/video.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    if '@router.post("/api/video/create")' not in content:
        import_stmt = 'import uuid\n\n'
        content = content.replace('@router.post("/api/video/check")', import_stmt + func_code + '\n@router.post("/api/video/check")')
        with open('app/api/video.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('Inserted create_video successfully')
else:
    print('Not found')
