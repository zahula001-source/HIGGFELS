with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('btn-activate-license')
print("Snippet (wider):")
print(text[max(0, idx-1000):idx+2500])
