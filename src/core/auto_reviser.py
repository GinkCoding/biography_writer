"""
自动修订引擎 - 根据审核意见自动修订内容
"""
import re
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass
class RevisionTask:
    """修订任务"""
    chapter: int
    issue_type: str
    description: str
    suggestion: str
    priority: int  # 1-5, 1最高


class AutoReviser:
    """自动修订器"""
    
    def __init__(self, llm_client, project_dir: Path):
        self.llm = llm_client
        self.project_dir = Path(project_dir)
        self.chapters_dir = self.project_dir / "chapters"
        self.material = self._load_material()
    
    def _load_material(self) -> str:
        """加载采访素材"""
        material_file = self.project_dir.parent.parent / "interviews" / "采访 mock.txt"
        if material_file.exists():
            return material_file.read_text(encoding='utf-8')
        return ""
    
    async def revise_by_final_review(self, review_report: str) -> Dict:
        """根据终审报告自动修订"""
        from .validators import ReviewReportParser
        
        parser = ReviewReportParser()
        parsed = parser.parse(review_report)
        
        results = {
            "total_issues": 0,
            "fixed_issues": 0,
            "failed_issues": 0,
            "details": []
        }
        
        # 合并所有问题
        all_issues = []
        all_issues.extend([(i, "serious") for i in parsed.get("serious_issues", [])])
        all_issues.extend([(i, "major") for i in parsed.get("major_issues", [])])
        
        results["total_issues"] = len(all_issues)
        
        # 按章节分组
        chapter_issues: Dict[int, List[Dict]] = {}
        for issue, severity in all_issues:
            chapter = issue.get("chapter")
            if chapter:
                if chapter not in chapter_issues:
                    chapter_issues[chapter] = []
                chapter_issues[chapter].append({**issue, "severity": severity})
        
        # 逐章修订
        for chapter, issues in sorted(chapter_issues.items()):
            print(f"[AutoReviser] 修订第{chapter}章，{len(issues)}个问题")
            
            success = await self._revise_chapter(chapter, issues)
            if success:
                results["fixed_issues"] += len(issues)
            else:
                results["failed_issues"] += len(issues)
            
            results["details"].append({
                "chapter": chapter,
                "issues_count": len(issues),
                "success": success
            })
        
        return results
    
    async def _revise_chapter(self, chapter: int, issues: List[Dict]) -> bool:
        """修订单个章节"""
        chapter_file = self.chapters_dir / f"chapter_{chapter:02d}.md"
        if not chapter_file.exists():
            print(f"[AutoReviser] 第{chapter}章文件不存在")
            return False
        
        original_content = chapter_file.read_text(encoding='utf-8')
        
        # 构建修订提示词
        issues_text = "\n".join([
            f"{i+1}. 【{issue['severity']}】{issue['description']}"
            for i, issue in enumerate(issues)
        ])
        
        prompt = f"""你是一位资深传记编辑。请根据以下终审意见修订章节内容。

【原始采访素材】（供参考，确保符合事实）
{self.material[:8000]}

【当前章节内容】
{original_content}

【需要修复的问题】
{issues_text}

【修订要求】
1. 彻底删除所有AI元数据（如"这是一篇经过深度修订..."）
2. 补充遗漏的关键素材（如1976年事件、弟弟角色等）
3. 修正人物设定与素材一致
4. 保持文学性和叙事流畅
5. **只输出正文，不要添加任何修改说明或元数据**

【输出格式】
以"# 第X章"开头，直接输出修订后的完整正文。"""
        
        try:
            revised = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=8000
            )
            
            # 清理可能的元数据
            revised = self._clean_output(revised)
            
            # 验证修订结果
            if len(revised) < len(original_content) * 0.5:
                print(f"[AutoReviser] 第{chapter}章修订后内容过短，可能出错")
                return False
            
            # 保存修订结果
            chapter_file.write_text(revised, encoding='utf-8')
            
            # 备份原文件
            backup_file = self.chapters_dir / f"chapter_{chapter:02d}.md.bak"
            backup_file.write_text(original_content, encoding='utf-8')
            
            print(f"[AutoReviser] 第{chapter}章修订完成")
            return True
            
        except Exception as e:
            print(f"[AutoReviser] 第{chapter}章修订失败: {e}")
            return False
    
    def _clean_output(self, content: str) -> str:
        """清理输出"""
        # 删除常见的元数据前缀
        patterns = [
            r'^【修订说明】[\s\S]*?\n\n',
            r'^修改说明[\s\S]*?\n\n',
            r'^以下是修订后的[\s\S]*?\n\n',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content.strip()
    
    async def fix_metadata(self, chapters: Optional[List[int]] = None):
        """批量修复元数据问题"""
        if chapters is None:
            # 处理所有章节
            chapter_files = sorted(self.chapters_dir.glob("chapter_*.md"))
            chapters = [int(f.stem.split("_")[1]) for f in chapter_files]
        
        fixed_count = 0
        
        for chapter in chapters:
            chapter_file = self.chapters_dir / f"chapter_{chapter:02d}.md"
            if not chapter_file.exists():
                continue
            
            content = chapter_file.read_text(encoding='utf-8')
            original_len = len(content)
            
            # 使用ContentValidator清理
            from .validators import ContentValidator
            validator = ContentValidator()
            cleaned = validator.clean_metadata(content)
            
            if len(cleaned) < original_len:
                chapter_file.write_text(cleaned, encoding='utf-8')
                fixed_count += 1
                print(f"[AutoReviser] 第{chapter}章元数据已清理")
        
        return fixed_count


class ContentCleaner:
    """内容清理器 - 各种清理工具"""
    
    # 清理规则
    CLEANING_RULES = [
        {
            "name": "ai_metadata",
            "pattern": r'^这是一篇?经过深度(修订|修正)[\s\S]*?\*\*\*\s*\n',
            "description": "AI修订说明"
        },
        {
            "name": "revision_note",
            "pattern": r'\n+\*\*\*\s*\n+【本章修改说明】[\s\S]*$',
            "description": "章节修改说明"
        },
        {
            "name": "thinking_block",
            "pattern": r'<thinkings>[\s\S]*?</thinkings>',
            "description": "思考过程块"
        },
        {
            "name": "json_wrapper",
            "pattern": r'^```json\s*\n([\s\S]*?)\n```\s*$',
            "description": "JSON包装",
            "extract_group": 1
        }
    ]
    
    @classmethod
    def clean(cls, content: str, rules: Optional[List[str]] = None) -> str:
        """清理内容"""
        cleaned = content
        applied_rules = []
        
        for rule in cls.CLEANING_RULES:
            if rules and rule["name"] not in rules:
                continue
            
            original = cleaned
            if "extract_group" in rule:
                # 提取模式
                match = re.search(rule["pattern"], cleaned, re.MULTILINE)
                if match:
                    cleaned = match.group(rule["extract_group"])
                    applied_rules.append(rule["name"])
            else:
                # 删除模式
                cleaned = re.sub(rule["pattern"], '', cleaned, flags=re.MULTILINE)
                if len(cleaned) < len(original):
                    applied_rules.append(rule["name"])
        
        # 通用清理
        cleaned = cleaned.strip()
        
        return cleaned
    
    @classmethod
    def is_clean(cls, content: str) -> tuple[bool, List[str]]:
        """检查内容是否干净"""
        issues = []
        
        for rule in cls.CLEANING_RULES:
            if re.search(rule["pattern"], content, re.MULTILINE):
                issues.append(rule["description"])
        
        # 检查其他问题
        if len(content) < 500:
            issues.append("内容过短")
        
        if not re.search(r'^#+\s*', content, re.MULTILINE):
            issues.append("缺少标题")
        
        return len(issues) == 0, issues


class FinalDocumentBuilder:
    """最终文档构建器"""
    
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.chapters_dir = self.project_dir / "chapters"
        self.final_dir = self.project_dir / "final"
    
    def build(self, include_toc: bool = True, include_stats: bool = True) -> Path:
        """构建最终文档"""
        self.final_dir.mkdir(exist_ok=True)
        
        # 读取大纲
        outline = self._load_outline()
        
        # 收集章节
        chapters = sorted(self.chapters_dir.glob("chapter_*.md"))
        
        # 构建内容
        parts = []
        
        # 1. 书名
        title = outline.get("title", "传记")
        parts.append(f"# {title}\n")
        parts.append("\n*基于真实采访撰写的传记*\n")
        parts.append("\n---\n")
        
        # 2. 目录
        if include_toc:
            parts.append("\n## 目录\n")
            for ch in outline.get("chapters", []):
                order = ch.get("order", 0)
                title = ch.get("title", f"第{order}章")
                period = ch.get("time_period", "")
                parts.append(f"\n第{order}章：{title}  （{period}）")
            parts.append("\n\n---\n\n")
        
        # 3. 正文
        total_chars = 0
        for chapter_file in chapters:
            content = chapter_file.read_text(encoding='utf-8')
            
            # 清理
            from .validators import ContentValidator
            validator = ContentValidator()
            content = validator.clean_metadata(content)
            
            parts.append(content)
            parts.append("\n\n---\n\n")
            total_chars += len(content)
        
        # 4. 统计
        if include_stats:
            parts.append("\n## 附录：生成统计\n")
            parts.append(f"\n- 总章节数：{len(chapters)}章")
            parts.append(f"\n- 总字数：约{total_chars:,}字")
            parts.append(f"\n- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        # 保存
        final_content = ''.join(parts)
        final_path = self.final_dir / f"{title}_最终版.md"
        final_path.write_text(final_content, encoding='utf-8')
        
        return final_path
    
    def _load_outline(self) -> Dict:
        """加载大纲"""
        outline_file = self.project_dir / "outline.json"
        if outline_file.exists():
            import json
            with open(outline_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"title": "传记", "chapters": []}


from datetime import datetime
