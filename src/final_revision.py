"""
终审修订模块 - 根据终审意见自动修订传记内容
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple


class FinalRevisionEngine:
    """终审修订引擎"""
    
    def __init__(self, project_dir: Path, llm_client):
        self.project_dir = Path(project_dir)
        self.chapters_dir = self.project_dir / "chapters"
        self.final_dir = self.project_dir / "final"
        self.llm = llm_client
        
    def load_review_report(self) -> str:
        """加载终审报告"""
        review_file = self.final_dir / "whole_book_review.txt"
        if review_file.exists():
            return review_file.read_text(encoding='utf-8')
        return ""
    
    def parse_review_issues(self, report: str) -> List[Dict]:
        """解析终审报告中的问题"""
        issues = []
        
        # 提取严重问题
        if "===严重问题" in report:
            serious_section = report.split("===严重问题")[1].split("===")[0]
            for line in serious_section.strip().split('\n'):
                line = line.strip()
                if line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')):
                    # 提取章节编号
                    chapter_match = re.search(r'第(\d+)章', line)
                    chapter_num = int(chapter_match.group(1)) if chapter_match else None
                    
                    issues.append({
                        "type": "serious",
                        "chapter": chapter_num,
                        "description": line,
                        "full_text": line
                    })
        
        return issues
    
    async def revise_chapter(self, chapter_num: int, issues: List[str], material: str) -> str:
        """根据问题修订单章"""
        chapter_file = self.chapters_dir / f"chapter_{chapter_num:02d}.md"
        if not chapter_file.exists():
            return None
        
        original_content = chapter_file.read_text(encoding='utf-8')
        
        prompt = f"""你是一位资深传记编辑。请根据终审意见修订以下章节。

【原始采访素材】
{material[:10000]}

【当前章节内容】
{original_content}

【需要修复的问题】
{chr(10).join(f"{i+1}. {issue}" for i, issue in enumerate(issues))}

【修订要求】
1. 彻底删除所有AI修订说明的元文本（如"这是一篇经过深度修订..."）
2. 补充遗漏的关键素材（如1976年毛主席去世、弟弟角色等）
3. 确保人物设定与素材一致（排行老三，两个姐姐，一个弟弟）
4. 增加时代细节（电子表、折叠伞、蛤蟆镜等）
5. 保持原有文学性和叙事流畅度
6. 不要添加任何元数据或修改说明，只输出正文

【输出格式】
直接输出修订后的章节正文，以# 第X章开头。不要包含任何修改说明。"""
        
        try:
            revised_content = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=8000
            )
            
            # 清理可能的元数据
            revised_content = self._clean_metadata(revised_content)
            
            return revised_content
        except Exception as e:
            print(f"修订第{chapter_num}章失败: {e}")
            return original_content
    
    def _clean_metadata(self, content: str) -> str:
        """清理元数据"""
        # 删除开头的AI说明
        patterns = [
            r'^这是一篇经过深度修订[\s\S]*?\*\*\*\s*\n',
            r'^这是一份经过深度修正[\s\S]*?\*\*\*\s*\n',
            r'\n+\*\*\*\s*\n+【本章修改说明】[\s\S]*$',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content.strip()
    
    async def run_revision(self, max_rounds: int = 3):
        """运行终审修订流程"""
        print("=== 开始终审修订 ===")
        
        # 1. 加载终审报告
        report = self.load_review_report()
        if not report:
            print("未找到终审报告，跳过修订")
            return
        
        # 2. 解析问题
        issues = self.parse_review_issues(report)
        if not issues:
            print("终审报告无严重问题，跳过修订")
            return
        
        print(f"发现 {len(issues)} 个严重问题")
        
        # 3. 按章节分组问题
        chapter_issues: Dict[int, List[str]] = {}
        for issue in issues:
            ch = issue.get("chapter")
            if ch:
                if ch not in chapter_issues:
                    chapter_issues[ch] = []
                chapter_issues[ch].append(issue["description"])
        
        # 4. 加载素材
        material_file = self.project_dir.parent.parent / "interviews" / "采访 mock.txt"
        material = ""
        if material_file.exists():
            material = material_file.read_text(encoding='utf-8')
        
        # 5. 逐章修订
        for chapter_num, issue_list in sorted(chapter_issues.items()):
            print(f"\n修订第{chapter_num}章...")
            print(f"  问题: {', '.join(issue_list[:2])}...")
            
            revised_content = await self.revise_chapter(chapter_num, issue_list, material)
            
            if revised_content:
                # 保存修订后的章节
                chapter_file = self.chapters_dir / f"chapter_{chapter_num:02d}.md"
                chapter_file.write_text(revised_content, encoding='utf-8')
                print(f"  ✅ 修订完成")
        
        # 6. 重新生成最终文档
        self._generate_final_document()
        
        print("\n=== 终审修订完成 ===")
    
    def _generate_final_document(self):
        """生成最终合并文档"""
        print("\n生成最终文档...")
        
        chapters = sorted(self.chapters_dir.glob("chapter_*.md"))
        full_content = []
        
        # 添加书名
        full_content.append("# 陈国伟传\n\n")
        full_content.append("*一部基于真实采访的传记*\n\n")
        full_content.append("---\n\n")
        
        for chapter_file in chapters:
            content = chapter_file.read_text(encoding='utf-8')
            full_content.append(content)
            full_content.append("\n\n---\n\n")
        
        final_file = self.final_dir / "陈国伟传_最终修订版.md"
        final_file.write_text(''.join(full_content), encoding='utf-8')
        
        print(f"✅ 最终文档: {final_file}")


# 便捷函数
async def run_final_revision(project_id: str):
    """运行指定项目的终审修订"""
    from src.llm.client import LLMClient
    
    project_dir = Path("output") / project_id
    llm = LLMClient()
    
    engine = FinalRevisionEngine(project_dir, llm)
    await engine.run_revision()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_final_revision("20260322_223009"))
