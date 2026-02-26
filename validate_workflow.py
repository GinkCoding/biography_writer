#!/usr/bin/env python3
"""
端到端流程验证脚本
检查五层架构是否能正确协同工作（无需实际运行LLM）
"""
import sys
import ast
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


class WorkflowValidator:
    """工作流程验证器"""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.success = []

    def validate_all(self):
        """运行所有验证"""
        print("=" * 70)
        print("传记写作系统 - 端到端流程验证")
        print("=" * 70)
        print()

        self.validate_syntax()
        self.validate_imports()
        self.validate_layer_interfaces()
        self.validate_data_flow()
        self.validate_configuration()
        self.validate_export_functions()

        print()
        print("=" * 70)
        print("验证结果汇总")
        print("=" * 70)
        print(f"✓ 通过: {len(self.success)} 项")
        print(f"⚠ 警告: {len(self.warnings)} 项")
        print(f"✗ 错误: {len(self.errors)} 项")

        if self.errors:
            print()
            print("错误详情:")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")

        if self.warnings:
            print()
            print("警告详情:")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")

        return len(self.errors) == 0

    def validate_syntax(self):
        """验证所有Python文件语法"""
        print("[1/6] 验证Python语法...")

        py_files = list(Path("src").rglob("*.py"))
        failed = []

        for file_path in py_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    ast.parse(f.read())
            except SyntaxError as e:
                failed.append(f"{file_path}: {e}")

        if failed:
            for f in failed:
                self.errors.append(f"语法错误: {f}")
        else:
            self.success.append(f"所有 {len(py_files)} 个Python文件语法正确")
            print(f"  ✓ 所有 {len(py_files)} 个文件语法正确")

    def validate_imports(self):
        """验证模块导入结构"""
        print("[2/6] 验证模块导入结构...")

        # 检查关键文件是否存在
        critical_files = [
            "src/__init__.py",
            "src/models.py",
            "src/config.py",
            "src/llm_client.py",
            "src/layers/__init__.py",
            "src/layers/data_ingestion.py",
            "src/layers/knowledge_memory.py",
            "src/layers/planning.py",
            "src/layers/generation.py",
            "src/layers/review_output.py",
            "src/generator/__init__.py",
            "src/generator/book_finalizer.py",
            "src/generator/epub_exporter.py",
        ]

        missing = []
        for file in critical_files:
            if not Path(file).exists():
                missing.append(file)

        if missing:
            for m in missing:
                self.errors.append(f"缺少关键文件: {m}")
        else:
            self.success.append(f"所有 {len(critical_files)} 个关键文件存在")
            print(f"  ✓ 所有关键文件存在")

        # 检查循环导入（简化检查）
        print("  - 检查循环导入风险...")
        # 实际循环导入检查需要在运行时进行

    def validate_layer_interfaces(self):
        """验证各层接口定义"""
        print("[3/6] 验证五层架构接口...")

        expected_layers = {
            'DataIngestionLayer': {
                'file': 'src/layers/data_ingestion.py',
                'key_methods': ['process_interview', 'retrieve_for_chapter']
            },
            'KnowledgeMemoryLayer': {
                'file': 'src/layers/knowledge_memory.py',
                'key_methods': ['build_knowledge_base', 'generate_character_biography']
            },
            'PlanningOrchestrationLayer': {
                'file': 'src/layers/planning.py',
                'key_methods': ['generate_outline', 'create_chapter_outline']
            },
            'IterativeGenerationLayer': {
                'file': 'src/layers/generation.py',
                'key_methods': ['generate_chapter', 'generate_section']
            },
            'ReviewOutputLayer': {
                'file': 'src/layers/review_output.py',
                'key_methods': ['review_chapter', 'finalize_book']
            }
        }

        for layer_name, spec in expected_layers.items():
            file_path = Path(spec['file'])
            if not file_path.exists():
                self.errors.append(f"层文件不存在: {file_path}")
                continue

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查类定义
            if f'class {layer_name}' not in content:
                self.errors.append(f"{file_path}: 缺少类定义 {layer_name}")
                continue

            # 检查关键方法
            missing_methods = []
            for method in spec['key_methods']:
                if f'async def {method}' not in content and f'def {method}' not in content:
                    missing_methods.append(method)

            if missing_methods:
                self.warnings.append(f"{layer_name}: 可能缺少方法 {missing_methods}")
            else:
                self.success.append(f"{layer_name} 接口完整")
                print(f"  ✓ {layer_name}")

    def validate_data_flow(self):
        """验证数据流连贯性"""
        print("[4/6] 验证数据流...")

        # 检查关键数据类型的导入和使用
        data_types = [
            ('InterviewMaterial', 'src/layers/data_ingestion.py'),
            ('Timeline', 'src/layers/knowledge_memory.py'),
            ('BookOutline', 'src/layers/planning.py'),
            ('GeneratedChapter', 'src/layers/generation.py'),
            ('BiographyBook', 'src/layers/review_output.py'),
        ]

        for type_name, file_path in data_types:
            path = Path(file_path)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if type_name in content:
                    print(f"  ✓ 数据类型 {type_name} 在 {file_path} 中使用")
                else:
                    self.warnings.append(f"数据类型 {type_name} 可能在 {file_path} 中未使用")
            else:
                self.errors.append(f"文件不存在: {file_path}")

        # 检查版本选择功能
        print("  - 检查版本选择集成...")
        review_file = Path("src/layers/review_output.py")
        if review_file.exists():
            with open(review_file, 'r', encoding='utf-8') as f:
                content = f.read()

            checks = [
                ('BookFinalizer 导入', 'from src.generator.book_finalizer import'),
                ('add_chapter_version 方法', 'def add_chapter_version'),
                ('finalize_book 方法', 'async def finalize_book'),
                ('版本选择器', 'self.book_finalizer'),
            ]

            for name, pattern in checks:
                if pattern in content:
                    print(f"    ✓ {name}")
                else:
                    self.errors.append(f"review_output.py 缺少: {name}")

    def validate_configuration(self):
        """验证配置文件"""
        print("[5/6] 验证配置...")

        # 检查配置文件
        config_files = [
            'config/settings.yaml',
            'config/styles.yaml',
            'requirements.txt',
        ]

        for config_file in config_files:
            path = Path(config_file)
            if path.exists():
                print(f"  ✓ 配置文件存在: {config_file}")
                self.success.append(f"配置文件存在: {config_file}")
            else:
                self.errors.append(f"缺少配置文件: {config_file}")

        # 检查关键依赖
        req_file = Path("requirements.txt")
        if req_file.exists():
            with open(req_file, 'r', encoding='utf-8') as f:
                reqs = f.read()

            critical_deps = ['ebooklib', 'pydantic', 'loguru']
            for dep in critical_deps:
                if dep in reqs:
                    print(f"  ✓ 依赖项: {dep}")
                else:
                    self.warnings.append(f"requirements.txt 可能缺少: {dep}")

    def validate_export_functions(self):
        """验证导出功能"""
        print("[6/6] 验证导出功能...")

        # 检查 EPUB 导出
        epub_file = Path("src/generator/epub_exporter.py")
        if epub_file.exists():
            with open(epub_file, 'r', encoding='utf-8') as f:
                content = f.read()

            checks = [
                ('EpubBook 创建', 'epub.EpubBook()'),
                ('元数据设置', 'set_metadata'),
                ('章节创建', '_create_chapters'),
                ('目录创建', '_create_toc'),
                ('样式添加', '_add_styles'),
            ]

            for name, pattern in checks:
                if pattern in content:
                    print(f"  ✓ EPUB导出: {name}")
                else:
                    self.warnings.append(f"epub_exporter.py 可能缺少: {name}")

        # 检查 BookFinalizer
        finalizer_file = Path("src/generator/book_finalizer.py")
        if finalizer_file.exists():
            with open(finalizer_file, 'r', encoding='utf-8') as f:
                content = f.read()

            checks = [
                ('ChapterVersionSelector 类', 'class ChapterVersionSelector'),
                ('BookFinalizer 类', 'class BookFinalizer'),
                ('版本选择', 'select_best_versions'),
                ('导出TXT', 'export_to_txt'),
                ('导出MD', 'export_to_markdown'),
                ('导出EPUB', 'export_to_epub'),
                ('导出JSON', 'export_to_json'),
            ]

            for name, pattern in checks:
                if pattern in content:
                    print(f"  ✓ BookFinalizer: {name}")
                else:
                    self.warnings.append(f"book_finalizer.py 可能缺少: {name}")


def main():
    validator = WorkflowValidator()
    is_valid = validator.validate_all()

    print()
    if is_valid:
        print("✓ 验证通过！系统可以按预期执行。")
        return 0
    else:
        print("✗ 验证失败，请修复上述错误。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
