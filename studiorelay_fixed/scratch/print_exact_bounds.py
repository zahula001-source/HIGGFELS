with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('btn-activate-license')
start_idx = text.rfind('async function', 0, idx)
end_idx = text.find('const _0x519c5b=', idx)

print("EXACT BEFORE BOUND:")
print(text[start_idx-100:start_idx+100])
print("\nEXACT AFTER BOUND:")
print(text[end_idx-100:end_idx+100])
