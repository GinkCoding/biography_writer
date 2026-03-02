#!/usr/bin/env python3
"""修复engine.py的缩进问题"""

with open('src/engine.py', 'r') as f:
    content = f.read()

# 查找generate_book方法并修复
lines = content.split('\n')

# 需要修复的区域：第215行到第301行（0-indexed: 214-300）
# 这些行需要添加额外缩进（4个空格）

fixed_lines = []
for i, line in enumerate(lines):
    # 第215-301行（索引214-300）需要添加缩进，但保留空白行
    if 214 <= i <= 300:
        if line.strip():  # 非空行
            fixed_lines.append('    ' + line)
        else:
            fixed_lines.append(line)
    else:
        fixed_lines.append(line)

with open('src/engine.py', 'w') as f:
    f.write('\n'.join(fixed_lines))

print("engine.py缩进已修复")
