#!/usr/bin/env python3
"""
修复导出代码中的标注清理问题
"""
import re

def clean_text(text):
    """
    清理文本中的标注和元数据
    
    移除：
    - 采访素材仅能确认：...
    - 其余细节尚无直接证据
    - （来源：素材 X）
    - 其他标注性文字
    """
    if not text:
        return ""
    
    # 移除采访素材标注
    text = re.sub(r'采访素材 [^\n]*', '', text)
    
    # 移除来源标注
    text = re.sub(r'（来源：素材\d+）', '', text)
    text = re.sub(r'\(来源：素材\d+\)', '', text)
    
    # 移除证据不足标注
    text = re.sub(r'，其余细节尚无直接证据 [。.]?', '', text)
    text = re.sub(r'其余细节尚无直接证据', '', text)
    text = re.sub(r'采访素材仅能确认 [^\n]*', '', text)
    
    # 移除待核实标注
    text = re.sub(r'\[待核实\]', '', text)
    text = re.sub(r'待核实', '', text)
    
    # 移除事实核查标注
    text = re.sub(r'事实核查：[^\n]*', '', text)
    
    # 移除多余空格
    text = re.sub(r'  +', ' ', text)
    
    # 移除空行（连续多个换行）
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    
    return text.strip()


def fix_book_finalizer():
    """修复 book_finalizer.py 文件"""
    
    file_path = 'src/generator/book_finalizer.py'
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已经添加了 clean_text 函数
    if 'def clean_text(text):' in content:
        print("✓ clean_text 函数已存在")
    else:
        # 在文件开头添加 clean_text 函数
        import_section_end = content.find('class ChapterVersion:')
        if import_section_end == -1:
            print("错误：找不到 Class 定义位置")
            return False
        
        clean_text_func = '''
def clean_text(text):
    """
    清理文本中的标注和元数据
    
    移除：
    - 采访素材仅能确认：...
    - 其余细节尚无直接证据
    - （来源：素材 X）
    - 其他标注性文字
    """
    if not text:
        return ""
    
    import re
    # 移除采访素材标注
    text = re.sub(r'采访素材 [^\\n]*', '', text)
    
    # 移除来源标注
    text = re.sub(r'（来源：素材\\d+）', '', text)
    text = re.sub(r'\\(来源：素材\\d+\\)', '', text)
    
    # 移除证据不足标注
    text = re.sub(r'，其余细节尚无直接证据 [。.]?', '', text)
    text = re.sub(r'其余细节尚无直接证据', '', text)
    text = re.sub(r'采访素材仅能确认 [^\\n]*', '', text)
    
    # 移除待核实标注
    text = re.sub(r'\\[待核实\\]', '', text)
    text = re.sub(r'待核实', '', text)
    
    # 移除事实核查标注
    text = re.sub(r'事实核查：[^\\n]*', '', text)
    
    # 移除多余空格
    text = re.sub(r'  +', ' ', text)
    
    # 移除空行（连续多个换行）
    text = re.sub(r'\\n\\s*\\n\\s*\\n', '\\n\\n', text)
    
    return text.strip()


'''
        content = content[:import_section_end] + clean_text_func + content[import_section_end:]
        print("✓ 添加了 clean_text 函数")
    
    # 修复 export_to_txt 方法
    if 'def export_to_txt(self, book: BiographyBook)' in content:
        # 找到 export_to_txt 方法
        txt_start = content.find('def export_to_txt(self, book: BiographyBook)')
        txt_end = content.find('def export_to_markdown', txt_start)
        
        txt_method = content[txt_start:txt_end]
        
        # 检查是否已经清理
        if 'clean_text(' not in txt_method:
            # 在内容添加时调用 clean_text
            old_line = 'lines.append(section.content)'
            new_line = 'lines.append(clean_text(section.content))'
            content = content.replace(old_line, new_line)
            print("✓ 修复了 export_to_txt 方法")
    
    # 修复 export_to_markdown 方法
    if 'def export_to_markdown(self, book: BiographyBook)' in content:
        md_start = content.find('def export_to_markdown(self, book: BiographyBook)')
        md_end = content.find('def export_to_json', md_start)
        
        md_method = content[md_start:md_end]
        
        # 检查是否已经清理
        if 'clean_text(' not in md_method:
            old_line = 'lines.append(section.content)'
            new_line = 'lines.append(clean_text(section.content))'
            # 只替换 markdown 方法中的
            if md_method.count('lines.append(section.content)') > 0:
                # 找到第二个出现的位置（在 markdown 方法中）
                first_occurrence = content.find('lines.append(section.content)')
                second_occurrence = content.find('lines.append(section.content)', first_occurrence + 1)
                if second_occurrence > md_start:
                    content = content[:second_occurrence] + content[second_occurrence:].replace(
                        'lines.append(section.content)', 
                        'lines.append(clean_text(section.content))', 
                        1
                    )
                    print("✓ 修复了 export_to_markdown 方法")
    
    # 保存修改
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✓ 已保存修复到 {file_path}")
    return True


if __name__ == '__main__':
    fix_book_finalizer()
