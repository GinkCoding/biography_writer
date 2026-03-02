"""Git版本控制管理模块

功能:
1. 自动Git初始化 - 项目创建时自动初始化Git仓库
2. 章节提交 - 每章生成后自动提交，创建章节标签
3. 大纲版本控制 - 大纲修改自动提交
4. 回滚功能 - 按章节标签回滚，恢复到指定版本
5. 备份策略 - 自动定期备份，重要节点标记
"""
import subprocess
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class CommitInfo:
    """提交信息"""
    hash: str
    short_hash: str
    message: str
    author: str
    date: datetime
    tags: List[str]


@dataclass
class GitStatus:
    """Git状态"""
    is_repo: bool
    branch: str
    has_changes: bool
    untracked_files: List[str]
    modified_files: List[str]
    staged_files: List[str]
    last_commit: Optional[CommitInfo]
    total_commits: int


class GitManager:
    """Git版本控制管理器"""

    # 默认.gitignore内容
    DEFAULT_GITIGNORE = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
ENV/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Environment variables
.env

# OS
.DS_Store
Thumbs.db

# Project specific
.vector_db/
.cache/
*.log

# Output files (keep structure, ignore large outputs)
output/*.txt
output/*.md
output/*.json
output/*.epub
!output/.gitkeep
"""

    def __init__(self, project_path: Optional[str] = None):
        """
        初始化Git管理器

        Args:
            project_path: 项目路径，如果为None则使用当前工作目录
        """
        self.project_path = Path(project_path) if project_path else Path.cwd()
        self._git_available = self._check_git_available()

    def _check_git_available(self) -> bool:
        """检查Git是否可用"""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Git命令不可用，版本控制功能将被禁用")
            return False

    def _run_git(self, args: List[str], cwd: Optional[Path] = None) -> tuple:
        """
        运行Git命令

        Args:
            args: Git命令参数
            cwd: 工作目录，默认为项目路径

        Returns:
            (returncode, stdout, stderr)
        """
        if not self._git_available:
            return 1, "", "Git不可用"

        working_dir = cwd or self.project_path
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)

    def is_git_repo(self, path: Optional[Path] = None) -> bool:
        """检查指定路径是否为Git仓库"""
        check_path = path or self.project_path
        git_dir = check_path / ".git"
        return git_dir.exists() and git_dir.is_dir()

    def init_repo(self, project_path: Optional[str] = None) -> bool:
        """
        初始化Git仓库

        Args:
            project_path: 项目路径，如果为None则使用初始化时的路径

        Returns:
            是否成功初始化
        """
        target_path = Path(project_path) if project_path else self.project_path

        if not self._git_available:
            logger.warning("Git不可用，跳过仓库初始化")
            return False

        # 检查是否已经是Git仓库
        if self.is_git_repo(target_path):
            logger.info(f"Git仓库已存在: {target_path}")
            return True

        # 初始化仓库
        returncode, stdout, stderr = self._run_git(["init"], cwd=target_path)
        if returncode != 0:
            logger.error(f"Git初始化失败: {stderr}")
            return False

        logger.info(f"Git仓库初始化成功: {target_path}")

        # 创建.gitignore
        self._create_gitignore(target_path)

        # 配置Git用户信息（如果未配置）
        self._ensure_git_config(target_path)

        # 创建初始提交
        self._create_initial_commit(target_path)

        return True

    def _create_gitignore(self, target_path: Path):
        """创建.gitignore文件"""
        gitignore_path = target_path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(self.DEFAULT_GITIGNORE, encoding="utf-8")
            logger.info(f"创建.gitignore: {gitignore_path}")

    def _ensure_git_config(self, target_path: Path):
        """确保Git用户配置存在"""
        # 检查全局配置
        returncode, stdout, _ = self._run_git(["config", "user.name"], cwd=target_path)
        if returncode != 0 or not stdout.strip():
            self._run_git(["config", "user.name", "Biography Writer"], cwd=target_path)

        returncode, stdout, _ = self._run_git(["config", "user.email"], cwd=target_path)
        if returncode != 0 or not stdout.strip():
            self._run_git(["config", "user.email", "writer@biography.local"], cwd=target_path)

    def _create_initial_commit(self, target_path: Path):
        """创建初始提交"""
        # 添加所有文件
        self._run_git(["add", "."], cwd=target_path)

        # 检查是否有文件可提交
        returncode, stdout, _ = self._run_git(
            ["diff", "--cached", "--name-only"],
            cwd=target_path
        )

        if stdout.strip():
            # 创建初始提交
            self._run_git(
                ["commit", "-m", "Initial commit: Project initialization\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"],
                cwd=target_path
            )
            logger.info("创建初始提交")

    def commit_chapter(
        self,
        chapter_num: int,
        chapter_title: str,
        word_count: int,
        message: Optional[str] = None
    ) -> bool:
        """
        提交章节变更

        Args:
            chapter_num: 章节编号
            chapter_title: 章节标题
            word_count: 章节字数
            message: 自定义提交信息

        Returns:
            是否成功提交
        """
        if not self.is_git_repo():
            logger.warning("不是Git仓库，跳过提交")
            return False

        # 添加所有变更
        self._run_git(["add", "."])

        # 生成提交信息
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if message:
            commit_msg = f"Chapter {chapter_num:04d}: {message}\n\nGenerated at: {timestamp}\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        else:
            commit_msg = (
                f"Chapter {chapter_num:04d}: {chapter_title}\n\n"
                f"Word count: {word_count}\n"
                f"Generated at: {timestamp}\n\n"
                f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
            )

        # 提交
        returncode, stdout, stderr = self._run_git(["commit", "-m", commit_msg])
        if returncode != 0:
            # 可能是没有变更需要提交
            if "nothing to commit" in stderr.lower():
                logger.info("没有变更需要提交")
                return True
            logger.error(f"提交失败: {stderr}")
            return False

        logger.info(f"章节 {chapter_num} 提交成功")

        # 创建章节标签
        self.create_tag(
            f"ch{chapter_num:04d}",
            f"Chapter {chapter_num}: {chapter_title}"
        )

        return True

    def commit_outline(
        self,
        message: Optional[str] = None,
        outline_version: Optional[str] = None
    ) -> bool:
        """
        提交大纲变更

        Args:
            message: 自定义提交信息
            outline_version: 大纲版本号

        Returns:
            是否成功提交
        """
        if not self.is_git_repo():
            logger.warning("不是Git仓库，跳过提交")
            return False

        # 添加所有变更
        self._run_git(["add", "."])

        # 生成提交信息
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version_info = f" (v{outline_version})" if outline_version else ""

        if message:
            commit_msg = f"Outline update{version_info}: {message}\n\nUpdated at: {timestamp}\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        else:
            commit_msg = (
                f"Outline update{version_info}\n\n"
                f"Updated at: {timestamp}\n\n"
                f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
            )

        # 提交
        returncode, stdout, stderr = self._run_git(["commit", "-m", commit_msg])
        if returncode != 0:
            if "nothing to commit" in stderr.lower():
                logger.info("没有变更需要提交")
                return True
            logger.error(f"提交失败: {stderr}")
            return False

        logger.info("大纲更新提交成功")
        return True

    def create_tag(self, tag_name: str, message: str) -> bool:
        """
        创建标签

        Args:
            tag_name: 标签名称
            message: 标签说明

        Returns:
            是否成功创建
        """
        if not self.is_git_repo():
            return False

        # 检查标签是否已存在
        returncode, stdout, _ = self._run_git(["tag", "-l", tag_name])
        if stdout.strip() == tag_name:
            # 删除旧标签
            self._run_git(["tag", "-d", tag_name])
            logger.info(f"删除已存在的标签: {tag_name}")

        # 创建新标签
        returncode, stdout, stderr = self._run_git(
            ["tag", "-a", tag_name, "-m", message]
        )
        if returncode != 0:
            logger.error(f"创建标签失败: {stderr}")
            return False

        logger.info(f"创建标签: {tag_name}")
        return True

    def rollback_to_chapter(self, chapter_num: int) -> bool:
        """
        回滚到指定章节

        Args:
            chapter_num: 章节编号

        Returns:
            是否成功回滚
        """
        if not self.is_git_repo():
            logger.error("不是Git仓库，无法回滚")
            return False

        tag_name = f"ch{chapter_num:04d}"

        # 检查标签是否存在
        returncode, stdout, _ = self._run_git(["tag", "-l", tag_name])
        if stdout.strip() != tag_name:
            logger.error(f"标签不存在: {tag_name}")
            return False

        # 回滚到标签位置
        returncode, stdout, stderr = self._run_git(
            ["reset", "--hard", tag_name]
        )
        if returncode != 0:
            logger.error(f"回滚失败: {stderr}")
            return False

        logger.info(f"成功回滚到第{chapter_num}章")
        return True

    def rollback_to_commit(self, commit_hash: str) -> bool:
        """
        回滚到指定提交

        Args:
            commit_hash: 提交哈希

        Returns:
            是否成功回滚
        """
        if not self.is_git_repo():
            logger.error("不是Git仓库，无法回滚")
            return False

        # 验证提交是否存在
        returncode, stdout, _ = self._run_git(
            ["cat-file", "-t", commit_hash]
        )
        if returncode != 0 or stdout.strip() != "commit":
            logger.error(f"提交不存在: {commit_hash}")
            return False

        # 回滚
        returncode, stdout, stderr = self._run_git(
            ["reset", "--hard", commit_hash]
        )
        if returncode != 0:
            logger.error(f"回滚失败: {stderr}")
            return False

        logger.info(f"成功回滚到提交: {commit_hash[:8]}")
        return True

    def get_history(self, max_count: int = 50) -> List[CommitInfo]:
        """
        获取提交历史

        Args:
            max_count: 最大返回数量

        Returns:
            提交信息列表
        """
        if not self.is_git_repo():
            return []

        # 格式化输出: hash|short_hash|message|author|date|tags
        format_str = "%H|%h|%s|%an|%ad|%D"
        returncode, stdout, _ = self._run_git([
            "log",
            f"--max-count={max_count}",
            f"--format={format_str}",
            "--date=iso"
        ])

        if returncode != 0 or not stdout.strip():
            return []

        commits = []
        for line in stdout.strip().split("\n"):
            parts = line.split("|", 5)
            if len(parts) >= 5:
                # 解析标签
                tags = []
                if len(parts) > 5 and parts[5]:
                    # 格式: "HEAD -> main, tag: v1.0, origin/main"
                    refs = parts[5].split(", ")
                    for ref in refs:
                        if "tag:" in ref:
                            tag_name = ref.replace("tag:", "").strip()
                            tags.append(tag_name)

                # 解析日期
                try:
                    date = datetime.fromisoformat(parts[4].replace(" ", "T"))
                except:
                    date = datetime.now()

                commits.append(CommitInfo(
                    hash=parts[0],
                    short_hash=parts[1],
                    message=parts[2],
                    author=parts[3],
                    date=date,
                    tags=tags
                ))

        return commits

    def get_status(self) -> GitStatus:
        """
        获取Git状态

        Returns:
            Git状态信息
        """
        if not self.is_git_repo():
            return GitStatus(
                is_repo=False,
                branch="",
                has_changes=False,
                untracked_files=[],
                modified_files=[],
                staged_files=[],
                last_commit=None,
                total_commits=0
            )

        # 获取分支
        returncode, stdout, _ = self._run_git(["branch", "--show-current"])
        branch = stdout.strip() if returncode == 0 else "unknown"

        # 获取状态
        returncode, stdout, _ = self._run_git(["status", "--porcelain"])

        untracked = []
        modified = []
        staged = []

        if stdout.strip():
            for line in stdout.strip().split("\n"):
                if len(line) >= 2:
                    index_status = line[0]
                    worktree_status = line[1]
                    filename = line[3:].strip()

                    if index_status in "MADRC":
                        staged.append(filename)
                    if worktree_status == "M":
                        modified.append(filename)
                    if index_status == "?":
                        untracked.append(filename)

        # 获取最后一次提交
        commits = self.get_history(1)
        last_commit = commits[0] if commits else None

        # 获取总提交数
        returncode, stdout, _ = self._run_git(["rev-list", "--count", "HEAD"])
        total_commits = int(stdout.strip()) if returncode == 0 else 0

        return GitStatus(
            is_repo=True,
            branch=branch,
            has_changes=bool(untracked or modified or staged),
            untracked_files=untracked,
            modified_files=modified,
            staged_files=staged,
            last_commit=last_commit,
            total_commits=total_commits
        )

    def get_diff(self, commit1: Optional[str] = None, commit2: Optional[str] = None) -> str:
        """
        获取差异对比

        Args:
            commit1: 第一个提交，为None则使用HEAD
            commit2: 第二个提交，为None则使用工作区

        Returns:
            差异文本
        """
        if not self.is_git_repo():
            return ""

        if commit1 and commit2:
            returncode, stdout, _ = self._run_git(
                ["diff", f"{commit1}..{commit2}"]
            )
        elif commit1:
            returncode, stdout, _ = self._run_git(
                ["diff", f"{commit1}..HEAD"]
            )
        else:
            returncode, stdout, _ = self._run_git(["diff"])

        return stdout if returncode == 0 else ""

    def get_chapter_diff(self, chapter_num: int) -> str:
        """
        获取指定章节的版本差异

        Args:
            chapter_num: 章节编号

        Returns:
            差异文本
        """
        if not self.is_git_repo():
            return ""

        tag_name = f"ch{chapter_num:04d}"

        # 检查标签是否存在
        returncode, stdout, _ = self._run_git(["tag", "-l", tag_name])
        if stdout.strip() != tag_name:
            return f"标签不存在: {tag_name}"

        # 获取该标签的父提交
        returncode, stdout, _ = self._run_git(
            ["rev-list", "--parents", "-n", "1", tag_name]
        )
        if returncode != 0 or not stdout.strip():
            return ""

        parts = stdout.strip().split()
        if len(parts) >= 2:
            parent = parts[1]
            returncode, stdout, _ = self._run_git(
                ["diff", f"{parent}..{tag_name}"]
            )
            return stdout if returncode == 0 else ""

        return ""

    def list_tags(self) -> List[Dict[str, str]]:
        """
        列出所有标签

        Returns:
            标签信息列表
        """
        if not self.is_git_repo():
            return []

        returncode, stdout, _ = self._run_git(
            ["tag", "-l", "-n1"]
        )

        tags = []
        if stdout.strip():
            for line in stdout.strip().split("\n"):
                parts = line.split(None, 1)
                if parts:
                    tag_name = parts[0]
                    message = parts[1] if len(parts) > 1 else ""
                    tags.append({
                        "name": tag_name,
                        "message": message
                    })

        return tags

    def create_backup(self, backup_name: Optional[str] = None) -> bool:
        """
        创建备份标签

        Args:
            backup_name: 备份名称，默认为 auto-backup-<timestamp>

        Returns:
            是否成功创建
        """
        if not self.is_git_repo():
            return False

        if backup_name is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_name = f"auto-backup-{timestamp}"

        return self.create_tag(backup_name, f"Automatic backup at {datetime.now().isoformat()}")

    def get_outline_history(self) -> List[CommitInfo]:
        """
        获取大纲相关的提交历史

        Returns:
            提交信息列表
        """
        if not self.is_git_repo():
            return []

        # 搜索包含"outline"的提交
        returncode, stdout, _ = self._run_git([
            "log",
            "--all",
            "--grep=outline",
            "--oneline"
        ])

        commits = []
        if stdout.strip():
            for line in stdout.strip().split("\n"):
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    short_hash = parts[0]
                    message = parts[1]
                    commits.append(CommitInfo(
                        hash="",
                        short_hash=short_hash,
                        message=message,
                        author="",
                        date=datetime.now(),
                        tags=[]
                    ))

        return commits

    def compare_outlines(self, commit1: str, commit2: str) -> Dict[str, Any]:
        """
        对比两个版本的大纲

        Args:
            commit1: 第一个提交
            commit2: 第二个提交

        Returns:
            对比结果
        """
        if not self.is_git_repo():
            return {"error": "不是Git仓库"}

        # 获取大纲文件的差异
        returncode, stdout, _ = self._run_git([
            "diff",
            commit1,
            commit2,
            "--",
            "*outline*.json"
        ])

        return {
            "commit1": commit1,
            "commit2": commit2,
            "diff": stdout if returncode == 0 else "",
            "has_changes": bool(stdout.strip())
        }


# 全局Git管理器实例
git_manager = GitManager()