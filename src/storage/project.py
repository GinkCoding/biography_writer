"""存储层 - 项目管理"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict, field


@dataclass
class Project:
    """项目状态"""
    project_id: str
    name: str
    material_path: str
    current_phase: str = "init"  # init/outline/chapters/review/final
    current_chapter: int = 0
    total_chapters: int = 25
    created_at: str = ""
    updated_at: str = ""
    completed_chapters: list = field(default_factory=list)


class ProjectStorage:
    """项目存储管理"""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.base_dir = Path(__file__).parent.parent.parent / "output" / project_id
        self.state_file = self.base_dir / "state.json"
        
    def ensure_dirs(self):
        """确保目录存在"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "chapters").mkdir(exist_ok=True)
        (self.base_dir / "chapter_notes").mkdir(exist_ok=True)
        (self.base_dir / "final").mkdir(exist_ok=True)
    
    def save_project(self, project: Project):
        """保存项目状态"""
        self.ensure_dirs()
        project.updated_at = datetime.now().isoformat()
        
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(project), f, ensure_ascii=False, indent=2)
    
    def load_project(self) -> Optional[Project]:
        """加载项目状态"""
        if not self.state_file.exists():
            return None
        
        with open(self.state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return Project(**data)
    
    def save_chapter(self, chapter_order: int, content: str):
        """保存章节内容"""
        self.ensure_dirs()
        chapter_file = self.base_dir / "chapters" / f"chapter_{chapter_order:02d}.md"
        with open(chapter_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def save_review(self, chapter_order: int, review: dict):
        """保存审核记录"""
        import json
        from datetime import datetime
        
        self.ensure_dirs()
        reviews_dir = self.base_dir / "reviews"
        reviews_dir.mkdir(exist_ok=True)
        
        review_file = reviews_dir / f"review_{chapter_order:02d}.json"
        review["timestamp"] = datetime.now().isoformat()
        
        with open(review_file, 'w', encoding='utf-8') as f:
            json.dump(review, f, ensure_ascii=False, indent=2)
    
    def load_review(self, chapter_order: int) -> Optional[dict]:
        """加载审核记录"""
        review_file = self.base_dir / "reviews" / f"review_{chapter_order:02d}.json"
        if not review_file.exists():
            return None
        with open(review_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_chapter(self, chapter_order: int) -> Optional[str]:
        """加载章节内容"""
        chapter_file = self.base_dir / "chapters" / f"chapter_{chapter_order:02d}.md"
        if not chapter_file.exists():
            return None
        with open(chapter_file, 'r', encoding='utf-8') as f:
            return f.read()
    
    def save_chapter_summary(self, chapter_order: int, summary: str):
        """保存章节结构化摘要"""
        self.ensure_dirs()
        summaries_dir = self.base_dir / "summaries"
        summaries_dir.mkdir(exist_ok=True)
        
        summary_file = summaries_dir / f"summary_{chapter_order:02d}.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary)
    
    def load_chapter_summary(self, chapter_order: int) -> Optional[str]:
        """加载章节结构化摘要"""
        summary_file = self.base_dir / "summaries" / f"summary_{chapter_order:02d}.txt"
        if not summary_file.exists():
            return None
        with open(summary_file, 'r', encoding='utf-8') as f:
            return f.read()
