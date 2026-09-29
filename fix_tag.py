with open('static/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# Fix 1: Profile card badge - add 'đã ra video' badge
old1 = "p.notes === 'không free' ? `<div style=\"position:absolute;top:0;right:0;background:#f59e0b;color:#fff;font-size:10px;font-weight:bold;padding:4px 12px;border-bottom-left-radius:8px;z-index:10;box-shadow:-2px 2px 4px rgba(0,0,0,0.2);\">không free</div>` : '')"
new1 = "p.notes === 'không free' ? `<div style=\"position:absolute;top:0;right:0;background:#f59e0b;color:#fff;font-size:10px;font-weight:bold;padding:4px 12px;border-bottom-left-radius:8px;z-index:10;box-shadow:-2px 2px 4px rgba(0,0,0,0.2);\">không free</div>` : (p.notes === 'đã ra video' ? `<div style=\"position:absolute;top:0;right:0;background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;font-size:10px;font-weight:bold;padding:4px 12px;border-bottom-left-radius:8px;z-index:10;box-shadow:-2px 2px 8px rgba(124,58,237,0.5);\">✅ đã ra video</div>` : ''))"

if old1 in content:
    content = content.replace(old1, new1)
    print('Fix 1 (badge) OK')
    changes += 1
else:
    print('Fix 1 NOT FOUND - searching...')
    idx = content.find("không free\";")
    if idx < 0:
        idx = content.find("kh\\u00f4ng free")
    print(f"  Index: {idx}")
    if idx > 0:
        print(repr(content[idx-50:idx+200]))

# Fix 2: Profile selector for Auto Tao Video - exclude 'đã ra video'
old2 = 'if (p.notes !== "không free") {'
new2 = 'if (p.notes !== "không free" && p.notes !== "đã ra video") {'
if old2 in content:
    content = content.replace(old2, new2)
    print('Fix 2 (selector) OK')
    changes += 1
else:
    print('Fix 2 NOT FOUND')

# Fix 3: Add color for 'đã ra video' in check-video profile list
old3 = "} else if (notes === 'không free' || notes === 'khong free') {\n              label.style.color = '#eab308'; // Vàng\n              div.style.borderLeft = '3px solid #eab308';"
new3 = "} else if (notes === 'không free' || notes === 'khong free') {\n              label.style.color = '#eab308'; // Vàng\n              div.style.borderLeft = '3px solid #eab308';\n          } else if (notes === 'đã ra video') {\n              label.style.color = '#a78bfa';\n              div.style.borderLeft = '3px solid #7c3aed';"
if old3 in content:
    content = content.replace(old3, new3)
    print('Fix 3 (color) OK')
    changes += 1
else:
    print('Fix 3 NOT FOUND - trying CRLF...')
    old3_crlf = old3.replace('\n', '\r\n')
    new3_crlf = new3.replace('\n', '\r\n')
    if old3_crlf in content:
        content = content.replace(old3_crlf, new3_crlf)
        print('Fix 3 (color CRLF) OK')
        changes += 1
    else:
        idx = content.find("khong free")
        print(f"  khong free at: {idx}")
        if idx > 0:
            print(repr(content[idx-30:idx+200]))

with open('static/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print(f'Done. Applied {changes}/3 fixes.')
