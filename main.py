#!/usr/bin/env python3
"""
传记生成系统 - 唯一入口
"""
import asyncio
import argparse
import json
from pathlib import Path
from datetime import datetime

from src.storage.project import Project
from src.pipeline import BiographyPipeline
from src.storage.project import ProjectStorage
from src.storage.git import GitManager


def create_project(name: str, material_path: str) -> Project:
    """创建新项目"""
    project_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    project = Project(
        project_id=project_id,
        name=name,
        material_path=material_path,
        current_phase="init",
        created_at=datetime.now().isoformat()
    )
    
    # 保存项目
    storage = ProjectStorage(project_id)
    storage.save_project(project)
    
    print(f"✅ 项目创建成功: {name}")
    print(f"   项目ID: {project_id}")
    print(f"   状态文件: output/{project_id}/state.json")
    
    return project


def run_project(project_id: str):
    """运行项目"""
    storage = ProjectStorage(project_id)
    project = storage.load_project()
    
    if not project:
        print(f"❌ 项目不存在: {project_id}")
        return
    
    print(f"🚀 启动传记生成: {project.name}")
    print(f"   当前阶段: {project.current_phase}")
    print(f"   当前章节: {project.current_chapter}")
    
    # 初始化流水线
    pipeline = BiographyPipeline(project, storage)
    
    # 运行
    asyncio.run(pipeline.run())


def resume_project(project_id: str):
    """续传项目"""
    storage = ProjectStorage(project_id)
    project = storage.load_project()
    
    if not project:
        print(f"❌ 项目不存在: {project_id}")
        return
    
    print(f"🔄 继续传记生成: {project.name}")
    print(f"   从第 {project.current_chapter} 章继续")
    
    pipeline = BiographyPipeline(project, storage)
    asyncio.run(pipeline.run())


def status_project(project_id: str):
    """查看项目状态"""
    storage = ProjectStorage(project_id)
    project = storage.load_project()
    
    if not project:
        print(f"❌ 项目不存在: {project_id}")
        return
    
    print(f"📊 项目状态: {project.name}")
    print(f"   ID: {project.project_id}")
    print(f"   阶段: {project.current_phase}")
    print(f"   章节: {project.current_chapter}/{project.total_chapters}")
    print(f"   创建时间: {project.created_at}")


def main():
    parser = argparse.ArgumentParser(description="传记生成系统")
    subparsers = parser.add_subparsers(dest="command")
    
    # create 命令
    create_parser = subparsers.add_parser("create", help="创建新项目")
    create_parser.add_argument("--name", required=True, help="项目名称")
    create_parser.add_argument("--material", required=True, help="素材文件路径")
    
    # run 命令
    run_parser = subparsers.add_parser("run", help="运行项目")
    run_parser.add_argument("--project", required=True, help="项目ID")
    
    # resume 命令
    resume_parser = subparsers.add_parser("resume", help="续传项目")
    resume_parser.add_argument("--project", required=True, help="项目ID")
    
    # status 命令
    status_parser = subparsers.add_parser("status", help="查看状态")
    status_parser.add_argument("--project", required=True, help="项目ID")
    
    args = parser.parse_args()
    
    if args.command == "create":
        create_project(args.name, args.material)
    elif args.command == "run":
        run_project(args.project)
    elif args.command == "resume":
        resume_project(args.project)
    elif args.command == "status":
        status_project(args.project)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
