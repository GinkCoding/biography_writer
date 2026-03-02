#!/usr/bin/env python3
"""修复engine.py的缩进问题"""

import re

def fix_engine_indent():
    with open('src/engine.py', 'r') as f:
        lines = f.readlines()

    fixed_lines = []
    in_try_block = False
    in_for_loop = False
    base_indent = 8  # try块的缩进级别 (8 spaces)
    for_indent = 12  # for循环内部的缩进级别 (12 spaces)

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 检测try块开始
        if stripped == 'try:':
            in_try_block = True
            fixed_lines.append(line)
            i += 1
            continue

        # 检测try块结束（except/finally）
        if stripped.startswith('except ') or stripped.startswith('finally:'):
            in_try_block = False
            in_for_loop = False
            fixed_lines.append(line)
            i += 1
            continue

        # 检测for循环开始
        if stripped.startswith('for ') and stripped.endswith(':'):
            in_for_loop = True
            fixed_lines.append(line)
            i += 1
            continue

        # 处理空行和注释 - 保持原样
        if not stripped or stripped.startswith('#'):
            fixed_lines.append(line)
            i += 1
            continue

        # 如果在for循环内部（从generate_book方法开始）
        if in_for_loop and in_try_block:
            # 检测for循环结束（看缩进级别）
            current_indent = len(line) - len(line.lstrip())

            # 如果当前行缩进小于等于for的缩进（12），且不是else/except/finally
            if current_indent <= for_indent:
                # 检查是否是控制流语句
                if stripped.startswith(('if ', 'elif ', 'else:', 'def ', 'class ', 'async def')):
                    pass  # 保持原样
                elif stripped.startswith(('return', 'break', 'continue', 'pass')):
                    pass  # 保持原样
                else:
                    # 可能是for循环结束，退回到try块级别
                    in_for_loop = False
                    fixed_lines.append(line)
                    i += 1
                    continue

            # 为for循环内部的代码添加额外缩进
            if current_indent == base_indent:  # 只有一层缩进（try级别）
                # 需要添加到for循环内部
                fixed_line = '    ' + line  # 添加4个空格
                fixed_lines.append(fixed_line)
                i += 1
                continue

        fixed_lines.append(line)
        i += 1

    with open('src/engine.py', 'w') as f:
        f.writelines(fixed_lines)

    print("engine.py缩进已修复")

if __name__ == '__main__':
    fix_engine_indent()
