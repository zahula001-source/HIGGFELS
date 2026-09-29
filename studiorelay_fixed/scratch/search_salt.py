with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Let's find salt or secret patterns in popup.js
import re
print("Matches for SECRET / SALT / KEY in popup.js strings:")
for m in re.finditer(r'[a-zA-Z0-9_\-]{10,50}', text):
    s = m.group(0)
    if any(k in s.lower() for k in ['salt', 'secret', 'ctb', 'license', 'key']):
        print(s)
