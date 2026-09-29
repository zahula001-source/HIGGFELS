with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('btn-activate-license')
print("Snippet around btn-activate-license:")
print(text[max(0, idx-500):idx+500])
