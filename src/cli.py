#!/usr/bin/env python3
"""命令行入口"""
import os
import sys
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from rich import box

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.engine import BiographyEngine
from src.models import WritingStyle
from src.config import settings
from src.observability.logging_setup import setup_application_logging
from src.observability.runtime_monitor import get_runtime_monitor

app = typer.Typer(help="传记写作工具 - 将采访转化为十万字传记")
console = Console()


def get_available_files() -> list:
    """获取interviews目录下的可用文件"""
    interview_dir = Path(settings.paths.interview_dir)
    if not interview_dir.exists():
        return []
    
    files = []
    for ext in ["*.txt", "*.md"]:
        files.extend(interview_dir.glob(ext))
    
    return sorted(files)


def check_and_setup_config():
    """检查并引导配置"""
    from src.config_manager import ConfigManager

    manager = ConfigManager()

    # 检查是否有.env文件
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        console.print("[yellow]⚠️  首次使用需要进行配置[/yellow]")
        console.print()

        # 询问是否运行配置向导
        if typer.confirm("是否运行配置向导？", default=True):
            from src.setup_wizard import SetupWizard
            wizard = SetupWizard()
            if not wizard.run():
                raise typer.Exit(1)
        else:
            console.print("[yellow]跳过配置，使用默认配置（可能无法正常工作）[/yellow]")


@app.command()
def init(
    file: Optional[str] = typer.Argument(None, help="采访文件路径（相对于interviews目录）"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="传主姓名"),
    style: WritingStyle = typer.Option(WritingStyle.LITERARY, "--style", help="写作风格"),
    words: int = typer.Option(100000, "--words", "-w", help="目标字数"),
    skip_config: bool = typer.Option(False, "--skip-config", help="跳过配置检查"),
):
    """从采访文件初始化传记项目"""

    # 检查配置
    if not skip_config:
        check_and_setup_config()

    # 如果没有指定文件，列出可用文件
    if not file:
        available = get_available_files()
        if not available:
            console.print("[red]interviews目录下没有找到.txt或.md文件[/red]")
            console.print(f"[yellow]请将采访文件放入: {settings.paths.interview_dir}[/yellow]")
            raise typer.Exit(1)

        console.print("[green]可用文件:[/green]")
        for i, f in enumerate(available, 1):
            console.print(f"  {i}. {f.name}")

        selection = typer.prompt("请选择文件编号", type=int)
        if selection < 1 or selection > len(available):
            console.print("[red]无效的选择[/red]")
            raise typer.Exit(1)

        file_path = available[selection - 1]
    else:
        file_path = Path(settings.paths.interview_dir) / file
        if not file_path.exists():
            console.print(f"[red]文件不存在: {file_path}[/red]")
            raise typer.Exit(1)

    # 检查API配置（使用配置管理器）
    try:
        from src.config_manager import ConfigManager
        manager = ConfigManager()
        llm_config = manager.check_llm_config()
        emb_config = manager.check_embedding_config()
        console.print(f"[green]✓ LLM配置: {llm_config[0]}[/green]")
        console.print(f"[green]✓ Embedding配置: {emb_config[0]}[/green]")
    except Exception as e:
        console.print(f"[red]配置检查失败: {e}[/red]")
        raise typer.Exit(1)
    
    async def do_init():
        engine = BiographyEngine()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在初始化项目...", total=None)
            
            def on_progress(msg: str):
                progress.update(task, description=f"[cyan]{msg}[/cyan]")
            
            book_id = await engine.initialize_from_interview(
                interview_file=file_path,
                subject_hint=subject,
                style=style,
                target_words=words,
                progress_callback=on_progress,
            )
            
            progress.update(task, description="[green]初始化完成![/green]")
        
        # 显示项目信息
        console.print()
        console.print(Panel(
            f"[bold green]项目初始化成功[/bold green]\n\n"
            f"[bold]项目ID:[/bold] {book_id}\n"
            f"[bold]传主:[/bold] {engine.outline.subject_name}\n"
            f"[bold]标题:[/bold] {engine.outline.title}\n"
            f"[bold]风格:[/bold] {style.value}\n"
            f"[bold]目标字数:[/bold] {words:,}字\n"
            f"[bold]章节数:[/bold] {engine.outline.total_chapters}章",
            title="传记项目",
            box=box.ROUNDED
        ))
        
        # 显示大纲预览
        console.print("\n[bold]章节大纲预览:[/bold]")
        table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        table.add_column("章节", style="cyan", width=6)
        table.add_column("标题", style="green")
        table.add_column("字数", justify="right", style="yellow")
        
        for chapter in engine.outline.chapters[:5]:  # 只显示前5章
            table.add_row(
                str(chapter.order),
                chapter.title,
                f"{chapter.target_words:,}"
            )
        
        if len(engine.outline.chapters) > 5:
            table.add_row("...", "...", "...")
        
        console.print(table)
        
        console.print(f"\n[yellow]使用以下命令开始生成:[/yellow]")
        console.print(f"  python -m biography write --id {book_id}")
        
        return book_id
    
    asyncio.run(do_init())


@app.command()
def write(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID（留空则使用最新项目）"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c", help="仅生成指定章节"),
):
    """生成传记内容"""
    
    async def do_write():
        engine = BiographyEngine()
        
        # 加载项目
        if id:
            if not engine.load_project(id):
                console.print(f"[red]项目不存在: {id}[/red]")
                raise typer.Exit(1)
            book_id = id
        else:
            # 查找最新的项目
            cache_dir = Path(settings.paths.cache_dir)
            outline_files = list(cache_dir.glob("*_outline.json"))
            if not outline_files:
                console.print("[red]没有找到现有项目，请先运行 init 命令[/red]")
                raise typer.Exit(1)
            
            latest = max(outline_files, key=lambda p: p.stat().st_mtime)
            book_id = latest.stem.replace("_outline", "")
            engine.load_project(book_id)
            console.print(f"[green]加载项目: {book_id}[/green]")
        
        # 生成内容
        if chapter:
            # 仅生成单章
            console.print(f"[yellow]正在生成第{chapter}章...[/yellow]")
            result = await engine.generate_single_chapter(chapter)
            console.print(f"[green]第{chapter}章生成完成，字数: {result.word_count}[/green]")
        else:
            # 生成全书
            console.print(f"[bold]开始生成完整传记...[/bold]")
            console.print(f"目标: {engine.outline.target_total_words:,}字，{engine.outline.total_chapters}章\n")
            
            generated_chapters = 0
            total_words = 0
            
            def on_progress(msg: str):
                console.print(f"  [dim]{msg}[/dim]")
            
            book = await engine.generate_book(progress_callback=on_progress)
            
            # 保存
            console.print("\n[yellow]正在保存...[/yellow]")
            saved_files = await engine.save_book(book)
            
            # 显示结果
            console.print()
            console.print(Panel(
                f"[bold green]传记生成完成![/bold green]\n\n"
                f"[bold]书名:[/bold] {book.outline.title}\n"
                f"[bold]总字数:[/bold] {book.total_word_count:,}字\n"
                f"[bold]章节数:[/bold] {len(book.chapters)}章\n\n"
                f"[bold]输出文件:[/bold]\n"
                f"  Markdown: {saved_files.get('markdown', 'N/A')}\n"
                f"  Text: {saved_files.get('text', 'N/A')}\n"
                f"  章节目录: {saved_files.get('chapters_dir', 'N/A')}",
                title="生成完成",
                box=box.ROUNDED
            ))
    
    asyncio.run(do_write())


@app.command()
def styles():
    """列出所有可用的写作风格"""
    from src.layers.planning import StyleController
    
    controller = StyleController()
    styles_list = controller.list_styles()
    
    console.print("\n[bold]可用的写作风格:[/bold]\n")
    
    table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED)
    table.add_column("ID", style="magenta", width=15)
    table.add_column("名称", style="green", width=12)
    table.add_column("描述", style="white")
    
    for style in styles_list:
        table.add_row(
            style["id"],
            style["name"],
            style["description"]
        )
    
    console.print(table)
    console.print()


@app.command()
def status(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """查看项目状态"""
    engine = BiographyEngine()
    
    if id:
        if not engine.load_project(id):
            console.print(f"[red]项目不存在: {id}[/red]")
            raise typer.Exit(1)
    else:
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)
        
        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        engine.load_project(book_id)
    
    progress = engine.get_progress()

    console.print(
        Panel(
            f"[bold]项目ID:[/bold] {progress['book_id']}\n"
            f"[bold]当前进度:[/bold] 第{progress['current_chapter']}/{progress['total_chapters']}章\n"
            f"[bold]完成度:[/bold] {progress['progress_percent']:.1f}%\n"
            f"[bold]状态:[/bold] {progress['status']}\n"
            f"[bold]运行ID:[/bold] {progress.get('run_id') or 'N/A'}\n"
            f"[bold]当前阶段:[/bold] {progress.get('runtime_stage') or 'N/A'}\n"
            f"[bold]最后消息:[/bold] {progress.get('last_message') or 'N/A'}\n"
            f"[bold]事件数:[/bold] {progress.get('event_count', 0)}",
            title="项目状态",
            box=box.ROUNDED,
        )
    )
    if progress.get("status_file"):
        console.print(f"[dim]status.json: {progress['status_file']}[/dim]")
    if progress.get("events_file"):
        console.print(f"[dim]events.jsonl: {progress['events_file']}[/dim]")
    if progress.get("artifacts_dir"):
        console.print(f"[dim]artifacts/: {progress['artifacts_dir']}[/dim]")


@app.command(name="runtime-status")
def runtime_status(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID（可选）"),
    tail: int = typer.Option(8, "--tail", help="显示最近N条事件"),
    follow: bool = typer.Option(False, "--follow", "-f", help="持续追踪运行事件"),
    interval: float = typer.Option(2.0, "--interval", help="追踪轮询间隔（秒）"),
):
    """查看最新运行态监控信息（无需项目已完成初始化）"""
    monitor = get_runtime_monitor(project_root=project_root)
    status = monitor.get_latest_status(book_id=id)
    if not status:
        console.print("[yellow]没有找到运行记录[/yellow]")
        raise typer.Exit(0)

    console.print(
        Panel(
            f"[bold]运行ID:[/bold] {status.get('run_id', 'N/A')}\n"
            f"[bold]项目ID:[/bold] {status.get('book_id', 'N/A')}\n"
            f"[bold]状态:[/bold] {status.get('status', 'N/A')}\n"
            f"[bold]当前阶段:[/bold] {status.get('current_stage', 'N/A')}\n"
            f"[bold]最后消息:[/bold] {status.get('last_message', 'N/A')}\n"
            f"[bold]更新时间:[/bold] {status.get('updated_at', 'N/A')}\n"
            f"[bold]事件数:[/bold] {status.get('event_count', 0)}",
            title="运行态监控",
            box=box.ROUNDED,
        )
    )
    for key in ["status_file", "events_file", "artifacts_dir", "manifest_file"]:
        if status.get(key):
            console.print(f"[dim]{key}: {status[key]}[/dim]")

    events_file = status.get("events_file")
    if events_file and tail > 0:
        path = Path(events_file)
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()[-tail:]
            table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
            table.add_column("时间", style="green", width=19)
            table.add_column("阶段", style="magenta", width=18)
            table.add_column("状态", style="yellow", width=10)
            table.add_column("消息", style="white")
            for line in lines:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                table.add_row(
                    str(event.get("timestamp", ""))[:19],
                    str(event.get("stage", "")),
                    str(event.get("status", "")),
                    str(event.get("message", "")),
                )
            console.print()
            console.print(table)

    if not follow:
        return

    if not events_file:
        console.print("[yellow]当前运行没有事件文件，无法 follow[/yellow]")
        return

    events_path = Path(events_file)
    if not events_path.exists():
        console.print(f"[yellow]事件文件不存在: {events_path}[/yellow]")
        return

    console.print(f"\n[cyan]进入追踪模式（轮询间隔 {interval:.1f}s，按 Ctrl+C 退出）[/cyan]")
    last_sequence = 0

    # 先读取一次已有事件，避免重复打印
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                event = json.loads(line)
                seq = int(event.get("sequence", 0) or 0)
                last_sequence = max(last_sequence, seq)
            except Exception:
                continue
    except Exception:
        pass

    try:
        while True:
            latest = monitor.get_latest_status(book_id=id) or {}
            latest_status = latest.get("status")
            latest_events_file = latest.get("events_file") or str(events_path)
            current_path = Path(latest_events_file)

            if current_path.exists():
                for line in current_path.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    seq = int(event.get("sequence", 0) or 0)
                    if seq <= last_sequence:
                        continue
                    last_sequence = seq
                    console.print(
                        f"[dim]{str(event.get('timestamp', ''))[:19]}[/dim] "
                        f"[magenta]{event.get('stage', '')}[/magenta] "
                        f"[yellow]{event.get('status', '')}[/yellow] "
                        f"{event.get('message', '')}"
                    )

            if latest_status in {"completed", "failed"}:
                console.print(f"[green]运行结束，状态: {latest_status}[/green]")
                break
            time.sleep(max(0.5, interval))
    except KeyboardInterrupt:
        console.print("[yellow]已停止追踪[/yellow]")


@app.command(name="runtime-report")
def runtime_report(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID（可选）"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="运行ID（可选，优先级高于 --id）"),
):
    """汇总运行事件与节点产物，输出结构化报告。"""
    monitor = get_runtime_monitor(project_root=project_root)

    if run_id:
        status_path = project_root / ".observability" / "runs" / run_id / "status.json"
        if not status_path.exists():
            console.print(f"[red]未找到运行ID: {run_id}[/red]")
            raise typer.Exit(1)
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["status_file"] = str(status_path)
    else:
        status = monitor.get_latest_status(book_id=id)
        if not status:
            console.print("[yellow]没有找到运行记录[/yellow]")
            raise typer.Exit(0)

    events_file = Path(status.get("events_file", ""))
    manifest_file = Path(status.get("manifest_file", ""))
    run_dir = Path(status.get("run_dir", ""))

    stage_counter = defaultdict(int)
    status_counter = defaultdict(int)
    latest_stage_message = {}

    if events_file.exists():
        for line in events_file.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except Exception:
                continue
            stage = str(event.get("stage", "unknown"))
            event_status = str(event.get("status", "unknown"))
            stage_counter[stage] += 1
            status_counter[event_status] += 1
            latest_stage_message[stage] = event.get("message", "")

    artifacts = []
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            artifacts = manifest.get("artifacts", [])
        except Exception:
            artifacts = []

    console.print(
        Panel(
            f"[bold]运行ID:[/bold] {status.get('run_id', 'N/A')}\n"
            f"[bold]项目ID:[/bold] {status.get('book_id', 'N/A')}\n"
            f"[bold]状态:[/bold] {status.get('status', 'N/A')}\n"
            f"[bold]事件总数:[/bold] {status.get('event_count', 0)}\n"
            f"[bold]产物总数:[/bold] {len(artifacts)}",
            title="运行报告",
            box=box.ROUNDED,
        )
    )

    if stage_counter:
        table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
        table.add_column("阶段", style="magenta")
        table.add_column("事件数", justify="right", style="yellow")
        table.add_column("最新消息", style="white")
        for stage, count in sorted(stage_counter.items(), key=lambda x: x[0]):
            table.add_row(stage, str(count), str(latest_stage_message.get(stage, "")))
        console.print("\n[bold]阶段统计[/bold]")
        console.print(table)

    if artifacts:
        artifact_table = Table(show_header=True, header_style="bold green", box=box.SIMPLE)
        artifact_table.add_column("阶段", style="cyan")
        artifact_table.add_column("文件", style="white")
        artifact_table.add_column("大小(bytes)", justify="right", style="yellow")
        for artifact in artifacts[-15:]:
            artifact_table.add_row(
                str(artifact.get("stage", "")),
                str(artifact.get("name", "")),
                str(artifact.get("size_bytes", 0)),
            )
        console.print("\n[bold]最近节点产物（最多15条）[/bold]")
        console.print(artifact_table)

    report_path = run_dir / "runtime_report.json" if run_dir else None
    if report_path:
        payload = {
            "run_id": status.get("run_id"),
            "book_id": status.get("book_id"),
            "status": status.get("status"),
            "stage_counter": dict(stage_counter),
            "status_counter": dict(status_counter),
            "latest_stage_message": latest_stage_message,
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"\n[dim]报告已写入: {report_path}[/dim]")


@app.command()
def resume(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """从断点继续生成"""
    async def do_resume():
        engine = BiographyEngine()

        if id:
            if not engine.load_project(id):
                console.print(f"[red]项目不存在: {id}[/red]")
                raise typer.Exit(1)
            book_id = id
        else:
            cache_dir = Path(settings.paths.cache_dir)
            outline_files = list(cache_dir.glob("*_outline.json"))
            if not outline_files:
                console.print("[yellow]没有找到可恢复的项目[/yellow]")
                raise typer.Exit(0)

            latest = max(outline_files, key=lambda p: p.stat().st_mtime)
            book_id = latest.stem.replace("_outline", "")
            engine.load_project(book_id)

        progress = engine.get_progress()
        console.print(f"[green]从第{progress['current_chapter']}章继续生成...[/green]")

        # 继续生成剩余章节
        # 这里需要实现增量生成逻辑
        console.print("[yellow]注意: 断点续传功能需要先生成已有章节的缓存，当前版本建议重新运行 write 命令[/yellow]")

    asyncio.run(do_resume())


@app.command(name="git-status")
def git_status(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """查看项目Git版本状态"""
    from src.version_control import GitManager

    # 确定项目路径
    if id:
        project_path = Path(settings.paths.output_dir) / id
    else:
        # 查找最新项目
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)

        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        project_path = Path(settings.paths.output_dir) / book_id

    if not project_path.exists():
        console.print(f"[red]项目目录不存在: {project_path}[/red]")
        raise typer.Exit(1)

    git_manager = GitManager(str(project_path))
    status = git_manager.get_status()

    if not status.is_repo:
        console.print(f"[yellow]项目尚未初始化Git仓库[/yellow]")
        console.print(f"运行以下命令初始化:\n  python -m src.cli init-git --id {id or book_id}")
        raise typer.Exit(0)

    # 显示状态
    console.print(Panel(
        f"[bold]分支:[/bold] {status.branch}\n"
        f"[bold]总提交数:[/bold] {status.total_commits}\n"
        f"[bold]有未提交变更:[/bold] {'是' if status.has_changes else '否'}",
        title="Git状态",
        box=box.ROUNDED
    ))

    if status.last_commit:
        console.print(f"\n[bold]最新提交:[/bold]")
        console.print(f"  Hash: {status.last_commit.short_hash}")
        console.print(f"  消息: {status.last_commit.message}")
        console.print(f"  作者: {status.last_commit.author}")
        console.print(f"  时间: {status.last_commit.date.strftime('%Y-%m-%d %H:%M:%S')}")
        if status.last_commit.tags:
            console.print(f"  标签: {', '.join(status.last_commit.tags)}")

    if status.untracked_files:
        console.print(f"\n[yellow]未跟踪文件 ({len(status.untracked_files)}):[/yellow]")
        for f in status.untracked_files[:10]:
            console.print(f"  {f}")
        if len(status.untracked_files) > 10:
            console.print(f"  ... 还有 {len(status.untracked_files) - 10} 个文件")

    if status.modified_files:
        console.print(f"\n[yellow]已修改文件 ({len(status.modified_files)}):[/yellow]")
        for f in status.modified_files[:10]:
            console.print(f"  {f}")
        if len(status.modified_files) > 10:
            console.print(f"  ... 还有 {len(status.modified_files) - 10} 个文件")


@app.command(name="git-log")
def git_log(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID"),
    n: int = typer.Option(20, "--n", help="显示最近N条提交")
):
    """查看项目提交历史"""
    from src.version_control import GitManager

    # 确定项目路径
    if id:
        project_path = Path(settings.paths.output_dir) / id
    else:
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)

        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        project_path = Path(settings.paths.output_dir) / book_id

    if not project_path.exists():
        console.print(f"[red]项目目录不存在: {project_path}[/red]")
        raise typer.Exit(1)

    git_manager = GitManager(str(project_path))

    if not git_manager.is_git_repo():
        console.print(f"[yellow]项目尚未初始化Git仓库[/yellow]")
        raise typer.Exit(0)

    commits = git_manager.get_history(max_count=n)

    if not commits:
        console.print("[yellow]没有提交历史[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
    table.add_column("Hash", style="dim", width=8)
    table.add_column("提交信息", style="white")
    table.add_column("时间", style="green", width=19)
    table.add_column("标签", style="magenta")

    for commit in commits:
        tags_str = ", ".join(commit.tags) if commit.tags else ""
        table.add_row(
            commit.short_hash,
            commit.message[:50] + "..." if len(commit.message) > 50 else commit.message,
            commit.date.strftime("%Y-%m-%d %H:%M"),
            tags_str
        )

    console.print(table)


@app.command(name="rollback")
def rollback(
    chapter: int = typer.Argument(..., help="回滚到指定章节"),
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """回滚到指定章节版本"""
    from src.version_control import GitManager

    # 确定项目路径
    if id:
        project_path = Path(settings.paths.output_dir) / id
    else:
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)

        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        project_path = Path(settings.paths.output_dir) / book_id

    if not project_path.exists():
        console.print(f"[red]项目目录不存在: {project_path}[/red]")
        raise typer.Exit(1)

    git_manager = GitManager(str(project_path))

    if not git_manager.is_git_repo():
        console.print(f"[red]项目尚未初始化Git仓库[/red]")
        raise typer.Exit(1)

    # 确认回滚
    if not typer.confirm(f"确定要回滚到第{chapter}章吗？这将丢失后续章节的更改。", default=False):
        console.print("[yellow]已取消回滚[/yellow]")
        raise typer.Exit(0)

    success = git_manager.rollback_to_chapter(chapter)
    if success:
        console.print(f"[green]成功回滚到第{chapter}章[/green]")
    else:
        console.print(f"[red]回滚失败[/red]")
        raise typer.Exit(1)


@app.command(name="tag")
def create_tag(
    tag_name: str = typer.Argument(..., help="标签名称"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="标签说明"),
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """为项目创建标签"""
    from src.version_control import GitManager

    # 确定项目路径
    if id:
        project_path = Path(settings.paths.output_dir) / id
    else:
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)

        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        project_path = Path(settings.paths.output_dir) / book_id

    if not project_path.exists():
        console.print(f"[red]项目目录不存在: {project_path}[/red]")
        raise typer.Exit(1)

    git_manager = GitManager(str(project_path))

    if not git_manager.is_git_repo():
        console.print(f"[red]项目尚未初始化Git仓库[/red]")
        raise typer.Exit(1)

    tag_message = message or f"Tag: {tag_name}"
    success = git_manager.create_tag(tag_name, tag_message)

    if success:
        console.print(f"[green]成功创建标签: {tag_name}[/green]")
    else:
        console.print(f"[red]创建标签失败[/red]")
        raise typer.Exit(1)


@app.command(name="git-tags")
def list_tags(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """列出项目所有标签"""
    from src.version_control import GitManager

    # 确定项目路径
    if id:
        project_path = Path(settings.paths.output_dir) / id
    else:
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)

        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        project_path = Path(settings.paths.output_dir) / book_id

    if not project_path.exists():
        console.print(f"[red]项目目录不存在: {project_path}[/red]")
        raise typer.Exit(1)

    git_manager = GitManager(str(project_path))

    if not git_manager.is_git_repo():
        console.print(f"[yellow]项目尚未初始化Git仓库[/yellow]")
        raise typer.Exit(0)

    tags = git_manager.list_tags()

    if not tags:
        console.print("[yellow]没有标签[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
    table.add_column("标签名", style="magenta")
    table.add_column("说明", style="white")

    for tag in tags:
        table.add_row(tag["name"], tag["message"])

    console.print(table)


@app.command(name="init-git")
def init_git(
    id: Optional[str] = typer.Option(None, "--id", help="项目ID")
):
    """为现有项目初始化Git仓库"""
    from src.version_control import GitManager

    # 确定项目路径
    if id:
        project_path = Path(settings.paths.output_dir) / id
    else:
        cache_dir = Path(settings.paths.cache_dir)
        outline_files = list(cache_dir.glob("*_outline.json"))
        if not outline_files:
            console.print("[yellow]没有找到项目[/yellow]")
            raise typer.Exit(0)

        latest = max(outline_files, key=lambda p: p.stat().st_mtime)
        book_id = latest.stem.replace("_outline", "")
        project_path = Path(settings.paths.output_dir) / book_id

    if not project_path.exists():
        console.print(f"[red]项目目录不存在: {project_path}[/red]")
        raise typer.Exit(1)

    git_manager = GitManager(str(project_path))

    if git_manager.is_git_repo():
        console.print(f"[yellow]Git仓库已存在[/yellow]")
        return

    success = git_manager.init_repo()
    if success:
        console.print(f"[green]Git仓库初始化成功[/green]")
    else:
        console.print(f"[red]Git仓库初始化失败[/red]")
        raise typer.Exit(1)


def main():
    """主入口"""
    setup_application_logging()

    # 显示欢迎信息
    if len(sys.argv) == 1:
        console.print(Panel(
            "[bold cyan]传记写作工具[/bold cyan] - 将采访转化为十万字传记\n\n"
            "[bold]快速开始:[/bold]\n"
            "  1. 将采访文件放入 interviews/ 目录\n"
            "  2. 运行: python -m biography init\n"
            "  3. 运行: python -m biography write\n\n"
            "[bold]常用命令:[/bold]\n"
            "  [green]init[/green]        - 初始化项目\n"
            "  [green]write[/green]       - 生成传记\n"
            "  [green]styles[/green]      - 查看可用风格\n"
            "  [green]status[/green]      - 查看项目状态\n"
            "  [green]runtime-status[/green] - 查看运行态监控\n"
            "  [green]runtime-report[/green] - 汇总运行事件与节点产物\n"
            "  [green]git-status[/green] - 查看Git版本状态\n"
            "  [green]git-log[/green]    - 查看提交历史\n"
            "  [green]rollback[/green]   - 回滚到指定章节\n"
            "  [green]tag[/green]        - 创建版本标签",
            title="欢迎使用",
            box=box.ROUNDED
        ))
        console.print()

    app()


if __name__ == "__main__":
    main()
