with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('btn-activate-license')

# Find the start of the function enclosing this license block
start_idx = text.rfind('async function', 0, idx)
end_idx = text.find('const _0x519c5b=', idx)

print("Start index:", start_idx)
print("End index:", end_idx)
print("Snippet to replace length:", end_idx - start_idx)
print(text[start_idx:start_idx+200])
print("...")
print(text[end_idx-200:end_idx])
