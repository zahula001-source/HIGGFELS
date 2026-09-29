import sys

with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

keywords = ['btn-activate-license', 'display-machine-id', 'CTB-', 'Invalid VIP Key']
for kw in keywords:
    idx = text.find(kw)
    print(f"=== Keyword: {kw} (Index: {idx}) ===")
    if idx != -1:
        print(text[max(0, idx-100):idx+300])
        print("\n")
