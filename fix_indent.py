with open('app/services/video_check.py', 'r', encoding='utf-8') as f:
    lines = f.read().split('\n')

for i in range(192, 433):  # Lines 193 to 433 (0-indexed 192 to 432)
    line = lines[i]
    if line.strip() != '':
        # It's at least indented by some spaces.
        # Add 4 spaces to the beginning of the line
        lines[i] = '    ' + line

with open('app/services/video_check.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
