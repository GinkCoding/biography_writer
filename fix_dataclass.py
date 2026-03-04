#!/usr/bin/env python3
"""修复 book_finalizer.py 中的 dataclass 问题"""

with open('src/generator/book_finalizer.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 移除错误的@dataclass 装饰器（在 clean_text 函数前面）
content = content.replace('@dataclass\n\ndef clean_text(text):', 'def clean_text(text):')

with open('src/generator/book_finalizer.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ 已修复 dataclass 装饰器问题")
