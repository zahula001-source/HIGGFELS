with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

print('Length:', len(text))
for item in ['display-machine-id', 'btn-activate-license', 'input-license-key', 'CTB-', 'Invalid VIP Key', 'activation-error']:
    print(f"{item}: {item in text}")
