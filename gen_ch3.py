#!/usr/bin/env python3
import os

output_dir = 'output/过河_陈国伟传'
os.makedirs(output_dir, exist_ok=True)

ch3 = open('gen_ch3_text.txt', 'r', encoding='utf-8').read()

with open(f'{output_dir}/03_第三章_闯深圳与第一桶金_完整版.md', 'w') as f:
    f.write(ch3)

print(f"第三章完成，约 {len(ch3)} 字符")
