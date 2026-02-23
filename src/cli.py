#!/usr/bin/env python3
"""命令行入口"""
import os
import sys
import asyncio
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


@app.command()
def init(
    file: Optional[str] = typer.Argument(None, help="采访文件路径（相对于interviews目录）"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="传主姓名"),
    style: WritingStyle = typer.Option(WritingStyle.LITERARY, "--style", help="写作风格"),
    words: int = typer.Option(100000, "--words", "-w", help="目标字数"),
):
    """从采访文件初始化传记项目"""
    
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
    
    # 检查API密钥
    if not settings.model.api_key and not os.getenv("API_KEY"):
        console.print("[red]错误: 未设置API密钥[/red]")
        console.print("[yellow]请设置环境变量: export API_KEY=your_api_key[/yellow]")
        raise typer.Exit(1)
    
    async def do_init():
        engine = BiographyEngine()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("正在初始化项目...", total=None)
            
            book_id = await engine.initialize_from_interview(
                interview_file=file_path,
                subject_hint=subject,
                style=style,
                target_words=words
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
    
    console.print(Panel(
        f"[bold]项目ID:[/bold] {progress['book_id']}\n"
        f"[bold]当前进度:[/bold] 第{progress['current_chapter']}/{progress['total_chapters']}章\n"
        f"[bold]完成度:[/bold] {progress['progress_percent']:.1f}%\n"
        f"[bold]状态:[/bold] {progress['status']}",
        title="项目状态",
        box=box.ROUNDED
    ))


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


def main():
    """主入口"""
    # 显示欢迎信息
    if len(sys.argv) == 1:
        console.print(Panel(
            "[bold cyan]传记写作工具[/bold cyan] - 将采访转化为十万字传记\n\n"
            "[bold]快速开始:[/bold]\n"
            "  1. 将采访文件放入 interviews/ 目录\n"
            "  2. 运行: python -m biography init\n"
            "  3. 运行: python -m biography write\n\n"
            "[bold]常用命令:[/bold]\n"
            "  [green]init[/green]    - 初始化项目\n"
            "  [green]write[/green]   - 生成传记\n"
            "  [green]styles[/green]  - 查看可用风格\n"
            "  [green]status[/green]  - 查看项目状态",
            title="欢迎使用",
            box=box.ROUNDED
        ))
        console.print()
    
    app()


if __name__ == "__main__":
    main()