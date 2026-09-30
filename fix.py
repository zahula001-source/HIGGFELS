import os

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = content.replace('.locator("visible=true")', '.first').replace('.first.first', '.first')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed {filepath}")

fix_file('app/api/profiles.py')
fix_file('app/services/video_gen.py')
