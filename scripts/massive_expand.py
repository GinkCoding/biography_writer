#!/usr/bin/env python3
"""
巨幅扩展所有章节，以达到10万字目标
"""

import os
import re

def count_chinese(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text))

def append_to_chapter(chapter_num, content):
    """追加内容到指定章节"""
    filepath = f"/Users/guoquan/work/Kimi/biography_writer/output/过河_陈国伟传/0{chapter_num}_Chapter_{chapter_num}_detailed.md"
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(content)
    return count_chinese(open(filepath).read())

# 为第一章添加大量内容
add1 = open("/Users/guoquan/work/Kimi/biography_writer/scripts/chapter1_expand.txt").read()
append_to_chapter(1, add1)

add2 = open("/Users/guoquan/work/Kimi/biography_writer/scripts/chapter2_expand.txt").read()
append_to_chapter(2, add2)

add3 = open("/Users/guoquan/work/Kimi/biography_writer/scripts/chapter3_expand.txt").read()
append_to_chapter(3, add3)

add4 = open("/Users/guoquan/work/Kimi/biography_writer/scripts/chapter4_expand.txt").read()
append_to_chapter(4, add4)

add5 = open("/Users/guoquan/work/Kimi/biography_writer/scripts/chapter5_expand.txt").read()
append_to_chapter(5, add5)

print("巨幅扩展完成")
