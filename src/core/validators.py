"""
严格的输入验证和内容验证模块
"""
import re
import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationError:
    """验证错误"""
    field: str
    message: str
    severity: str  # error, warning


class OutlineValidator:
    """大纲验证器"""
    
    REQUIRED_FIELDS = ["title", "chapters", "total_chapters"]
    CHAPTER_REQUIRED_FIELDS = ["order", "title", "time_period", "key_events"]
    
    def validate(self, outline: Dict) -> Tuple[bool, List[ValidationError]]:
        """验证大纲完整性"""
        errors = []
        
        # 1. 检查必要字段
        for field in self.REQUIRED_FIELDS:
            if field not in outline:
                errors.append(ValidationError(
                    field=field,
                    message=f"缺少必要字段: {field}",
                    severity="error"
                ))
        
        if errors:
            return False, errors
        
        # 2. 检查章节列表
        chapters = outline.get("chapters", [])
        if not chapters:
            errors.append(ValidationError(
                field="chapters",
                message="章节列表为空",
                severity="error"
            ))
            return False, errors
        
        # 3. 检查每个章节
        for i, chapter in enumerate(chapters):
            chapter_errors = self._validate_chapter(chapter, i + 1)
            errors.extend(chapter_errors)
        
        # 4. 检查章节顺序
        orders = [ch.get("order") for ch in chapters]
        if orders != sorted(orders):
            errors.append(ValidationError(
                field="chapters",
                message="章节顺序不正确",
                severity="error"
            ))
        
        # 5. 检查时间线连续性
        time_errors = self._validate_timeline(chapters)
        errors.extend(time_errors)
        
        return len([e for e in errors if e.severity == "error"]) == 0, errors
    
    def _validate_chapter(self, chapter: Dict, expected_order: int) -> List[ValidationError]:
        """验证单个章节"""
        errors = []
        
        # 检查必要字段
        for field in self.CHAPTER_REQUIRED_FIELDS:
            if field not in chapter:
                errors.append(ValidationError(
                    field=f"chapter.{field}",
                    message=f"第{expected_order}章缺少字段: {field}",
                    severity="error"
                ))
        
        # 检查order连续性
        if chapter.get("order") != expected_order:
            errors.append(ValidationError(
                field="chapter.order",
                message=f"章节顺序错误: 期望{expected_order}, 实际{chapter.get('order')}",
                severity="error"
            ))
        
        # 检查时间格式
        time_period = chapter.get("time_period", "")
        if not self._is_valid_time_period(time_period):
            errors.append(ValidationError(
                field="chapter.time_period",
                message=f"第{expected_order}章时间格式不正确: {time_period}",
                severity="warning"
            ))
        
        return errors
    
    def _validate_timeline(self, chapters: List[Dict]) -> List[ValidationError]:
        """验证时间线连续性"""
        errors = []
        
        for i in range(len(chapters) - 1):
            current_end = self._extract_year(chapters[i].get("time_period", ""), end=True)
            next_start = self._extract_year(chapters[i + 1].get("time_period", ""), end=False)
            
            if current_end and next_start:
                if next_start < current_end:
                    errors.append(ValidationError(
                        field="timeline",
                        message=f"时间线倒退: 第{i+1}章结束于{current_end}年, 第{i+2}章开始于{next_start}年",
                        severity="error"
                    ))
        
        return errors
    
    def _is_valid_time_period(self, time_period: str) -> bool:
        """验证时间格式"""
        # 支持格式: 1965-1970, 1965年-1970年, 约1965-约1970
        pattern = r'^(约?\d{4}年?\s*[-–—]\s*约?\d{4}年?)$'
        return bool(re.match(pattern, time_period.strip()))
    
    def _extract_year(self, time_period: str, end: bool = False) -> Optional[int]:
        """从时间段提取年份"""
        years = re.findall(r'\d{4}', time_period)
        if years:
            if end and len(years) >= 2:
                return int(years[1])
            elif not end:
                return int(years[0])
        return None


class ContentValidator:
    """内容验证器"""
    
    # AI元数据标记
    METADATA_PATTERNS = [
        r'^这是一篇经过深度修订[\s\S]*?\*\*\*\s*\n',
        r'^这是一篇经过深度修正[\s\S]*?\*\*\*\s*\n',
        r'^这是一份经过深度修正[\s\S]*?\*\*\*\s*\n',
        r'【本章修改说明】[\s\S]*$',
        r'\n+\*\*\*\s*\n+【本章修改说明】[\s\S]*$',
    ]
    
    # AI占位符
    PLACEHOLDER_PATTERNS = [
        r'此处待补充',
        r'待完善',
        r'待后续补充',
        r'请补充',
        r'\(此处省略\)',
        r'\.\.\.\.\.\.',
    ]
    
    def validate(self, content: str) -> Tuple[bool, List[ValidationError]]:
        """验证内容质量"""
        errors = []
        
        # 1. 检查元数据
        metadata_errors = self._check_metadata(content)
        errors.extend(metadata_errors)
        
        # 2. 检查占位符
        placeholder_errors = self._check_placeholders(content)
        errors.extend(placeholder_errors)
        
        # 3. 检查字数
        if len(content) < 1000:
            errors.append(ValidationError(
                field="length",
                message=f"内容过短: {len(content)}字",
                severity="error"
            ))
        
        # 4. 检查章节标题
        if not re.search(r'^#+\s*第[一二三四五六七八九十\d]+章', content, re.MULTILINE):
            errors.append(ValidationError(
                field="title",
                message="缺少章节标题",
                severity="error"
            ))
        
        return len([e for e in errors if e.severity == "error"]) == 0, errors
    
    def _check_metadata(self, content: str) -> List[ValidationError]:
        """检查元数据"""
        errors = []
        
        for pattern in self.METADATA_PATTERNS:
            if re.search(pattern, content, re.MULTILINE):
                errors.append(ValidationError(
                    field="metadata",
                    message="检测到AI修订说明元数据",
                    severity="error"
                ))
                break
        
        return errors
    
    def _check_placeholders(self, content: str) -> List[ValidationError]:
        """检查占位符"""
        errors = []
        
        for pattern in self.PLACEHOLDER_PATTERNS:
            if re.search(pattern, content):
                errors.append(ValidationError(
                    field="placeholder",
                    message=f"检测到占位符: {pattern}",
                    severity="error"
                ))
        
        return errors
    
    def clean_metadata(self, content: str) -> str:
        """清理元数据"""
        cleaned = content
        
        for pattern in self.METADATA_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE)
        
        return cleaned.strip()


class ReviewReportParser:
    """终审报告解析器（健壮版）"""
    
    def parse(self, report: str) -> Dict:
        """解析终审报告"""
        result = {
            "passed": False,
            "overall_score": 0,
            "serious_issues": [],
            "major_issues": [],
            "minor_issues": [],
            "suggestions": []
        }
        
        if not report or not report.strip():
            return result
        
        # 提取passed状态
        passed_match = re.search(r'passed:\s*(true|false)', report, re.IGNORECASE)
        if passed_match:
            result["passed"] = passed_match.group(1).lower() == "true"
        
        # 提取总体评价
        evaluation_match = re.search(r'总体评价[:：](.+?)(?=\n\n|\n===|$)', report, re.DOTALL)
        if evaluation_match:
            result["evaluation"] = evaluation_match.group(1).strip()
        
        # 提取严重问题（多种格式兼容）
        serious_section = self._extract_section(report, 
            ["严重问题", "严重问题（如有则必须修订）", "严重", "SERIOUS"])
        result["serious_issues"] = self._parse_issues(serious_section)
        
        # 提取主要问题
        major_section = self._extract_section(report,
            ["主要问题", "重大问题", "MAJOR"])
        result["major_issues"] = self._parse_issues(major_section)
        
        # 提取建议
        suggestion_section = self._extract_section(report,
            ["建议优化", "优化建议", "建议", "SUGGESTIONS"])
        result["suggestions"] = self._parse_issues(suggestion_section)
        
        return result
    
    def _extract_section(self, report: str, headers: List[str]) -> str:
        """提取报告章节（支持多种标题格式）"""
        for header in headers:
            # 尝试匹配 ===标题=== 格式
            pattern1 = rf'===+\s*{header}.*?===+(.*?)(?====|$)'
            match = re.search(pattern1, report, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            
            # 尝试匹配 【标题】 格式
            pattern2 = rf'【{header}】\s*\n(.*?)(?=\n【|$)'
            match = re.search(pattern2, report, re.DOTALL)
            if match:
                return match.group(1).strip()
            
            # 尝试匹配 ## 标题 格式
            pattern3 = rf'#+\s*{header}\s*\n(.*?)(?=\n#+|$)'
            match = re.search(pattern3, report, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return ""
    
    def _parse_issues(self, section: str) -> List[Dict]:
        """解析问题列表"""
        issues = []
        
        if not section:
            return issues
        
        # 匹配编号列表 1. xxx 或 1、xxx
        lines = re.findall(r'(?:^|\n)\s*(?:\d+[\.、]\s*)(.+?)(?=\n\s*\d+[\.、]|$)', section, re.DOTALL)
        
        for line in lines:
            line = line.strip()
            if line:
                # 提取章节号
                chapter_match = re.search(r'第(\d+)章', line)
                chapter = int(chapter_match.group(1)) if chapter_match else None
                
                # 提取问题类型
                issue_type = "general"
                if "格式" in line or "元数据" in line:
                    issue_type = "format"
                elif "素材" in line or "遗漏" in line:
                    issue_type = "content_missing"
                elif "人物" in line:
                    issue_type = "character"
                elif "重复" in line:
                    issue_type = "repetition"
                
                issues.append({
                    "description": line,
                    "chapter": chapter,
                    "type": issue_type
                })
        
        return issues


class EventTracker:
    """事件追踪器 - 防止跨章节重复"""
    
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.events: Dict[str, Dict] = {}  # event_key -> {chapter, status, description}
        self._load()
    
    def register_event(self, event_key: str, chapter: int, description: str):
        """注册事件"""
        if event_key in self.events:
            existing = self.events[event_key]
            if existing["chapter"] != chapter:
                print(f"[EventTracker] 警告: 事件'{event_key}'已在第{existing['chapter']}章注册")
                return False
        
        self.events[event_key] = {
            "chapter": chapter,
            "description": description,
            "status": "registered",
            "timestamp": datetime.now().isoformat()
        }
        self._save()
        return True
    
    def mark_event_written(self, event_key: str, chapter: int):
        """标记事件已写入"""
        if event_key in self.events:
            self.events[event_key]["status"] = "written"
            self.events[event_key]["written_in_chapter"] = chapter
            self._save()
    
    def is_event_written(self, event_key: str) -> bool:
        """检查事件是否已写入"""
        return event_key in self.events and self.events[event_key].get("status") == "written"
    
    def get_written_events(self) -> List[str]:
        """获取已写入的事件列表"""
        return [k for k, v in self.events.items() if v.get("status") == "written"]
    
    def _save(self):
        """保存事件追踪"""
        event_file = self.storage_path / "event_registry.json"
        with open(event_file, 'w', encoding='utf-8') as f:
            json.dump(self.events, f, ensure_ascii=False, indent=2)
    
    def _load(self):
        """加载事件追踪"""
        event_file = self.storage_path / "event_registry.json"
        if event_file.exists():
            try:
                with open(event_file, 'r', encoding='utf-8') as f:
                    self.events = json.load(f)
            except Exception:
                self.events = {}


from datetime import datetime
