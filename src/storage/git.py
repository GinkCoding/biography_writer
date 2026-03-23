"""Git版本控制"""
import subprocess
from pathlib import Path
from datetime import datetime


class GitManager:
    """Git版本控制管理"""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
    
    def init(self):
        """初始化仓库"""
        if not (self.repo_path / ".git").exists():
            subprocess.run(["git", "init"], cwd=self.repo_path, check=True)
    
    def commit(self, message: str):
        """提交"""
        subprocess.run(["git", "add", "."], cwd=self.repo_path, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.repo_path, check=True)
    
    def tag(self, name: str):
        """创建标签"""
        subprocess.run(["git", "tag", name], cwd=self.repo_path, check=True)
