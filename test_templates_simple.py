#!/usr/bin/env python3
"""简化版模板系统测试 - 不依赖外部库"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 只测试Jinja2模板渲染
try:
    from jinja2 import Environment, FileSystemLoader
    print("✓ Jinja2 导入成功")
except ImportError as e:
    print(f"✗ Jinja2 导入失败: {e}")
    sys.exit(1)


def test_template_structure():
    """测试模板目录结构"""
    print("\n" + "=" * 60)
    print("测试模板目录结构")
    print("=" * 60)

    templates_dir = Path(__file__).parent / "templates"

    if not templates_dir.exists():
        print(f"✗ 模板目录不存在: {templates_dir}")
        return False

    print(f"✓ 模板目录存在: {templates_dir}")

    # 检查子目录
    expected_dirs = ["system", "sections", "styles", "output_schemas"]
    for subdir in expected_dirs:
        subdir_path = templates_dir / subdir
        if subdir_path.exists():
            files = list(subdir_path.glob("*.j2")) + list(subdir_path.glob("*.json"))
            print(f"✓ {subdir}/ 存在，包含 {len(files)} 个文件")
        else:
            print(f"✗ {subdir}/ 不存在")
            return False

    return True


def test_jinja2_rendering():
    """测试Jinja2模板渲染"""
    print("\n" + "=" * 60)
    print("测试Jinja2模板渲染")
    print("=" * 60)

    templates_dir = Path(__file__).parent / "templates"

    try:
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )
        print("✓ Jinja2 环境创建成功")
    except Exception as e:
        print(f"✗ Jinja2 环境创建失败: {e}")
        return False

    # 测试加载各个模板
    templates_to_test = [
        "system/base.j2",
        "system/generation.j2",
        "system/review.j2",
        "system/extraction.j2",
        "sections/constraints.j2",
        "sections/style_guide.j2",
        "sections/examples.j2",
        "styles/documentary.j2",
        "styles/literary.j2",
        "styles/investigative.j2",
        "styles/memoir.j2",
    ]

    for template_name in templates_to_test:
        try:
            template = env.get_template(template_name)
            print(f"✓ 成功加载: {template_name}")
        except Exception as e:
            print(f"✗ 加载失败 {template_name}: {e}")
            return False

    return True


def test_template_rendering():
    """测试实际渲染"""
    print("\n" + "=" * 60)
    print("测试模板渲染")
    print("=" * 60)

    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True
    )

    # 测试基础模板渲染
    try:
        template = env.get_template("system/base.j2")
        result = template.render(
            style_name="纪实",
            style_description="客观真实的记录风格",
            role_anchor="你是一位纪实作家"
        )
        print(f"✓ 基础模板渲染成功")
        print(f"  结果长度: {len(result)} 字符")
        print(f"  结果预览:\n{result[:300]}...")
    except Exception as e:
        print(f"✗ 基础模板渲染失败: {e}")
        return False

    # 测试约束片段渲染
    try:
        template = env.get_template("sections/constraints.j2")
        result = template.render()
        print(f"\n✓ 约束片段渲染成功")
        print(f"  结果长度: {len(result)} 字符")
    except Exception as e:
        print(f"✗ 约束片段渲染失败: {e}")
        return False

    # 测试示例片段渲染
    try:
        template = env.get_template("sections/examples.j2")
        result = template.render()
        print(f"✓ 示例片段渲染成功")
        print(f"  结果长度: {len(result)} 字符")
    except Exception as e:
        print(f"✗ 示例片段渲染失败: {e}")
        return False

    return True


def test_style_templates():
    """测试风格模板"""
    print("\n" + "=" * 60)
    print("测试风格模板")
    print("=" * 60)

    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True
    )

    styles = ["documentary", "literary", "investigative", "memoir"]

    for style in styles:
        try:
            template = env.get_template(f"styles/{style}.j2")
            # 风格模板继承自 generation.j2，需要提供一些变量
            result = template.render(
                style=style,
                context_level="l1",
                inference_mode=False
            )
            print(f"✓ {style} 风格模板渲染成功")
            print(f"  结果长度: {len(result)} 字符")
        except Exception as e:
            print(f"✗ {style} 风格模板渲染失败: {e}")
            return False

    return True


def test_output_schemas():
    """测试输出Schema"""
    print("\n" + "=" * 60)
    print("测试输出Schema")
    print("=" * 60)

    import json
    schemas_dir = Path(__file__).parent / "templates" / "output_schemas"

    schemas = ["chapter.json", "outline.json", "review.json"]

    for schema_name in schemas:
        schema_path = schemas_dir / schema_name
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            print(f"✓ {schema_name} 加载成功")
            print(f"  标题: {schema.get('title', 'N/A')}")
        except Exception as e:
            print(f"✗ {schema_name} 加载失败: {e}")
            return False

    return True


def main():
    """运行所有测试"""
    print("=" * 60)
    print("提示词模板系统测试 (简化版)")
    print("=" * 60)

    tests = [
        ("模板目录结构", test_template_structure),
        ("Jinja2模板加载", test_jinja2_rendering),
        ("模板渲染", test_template_rendering),
        ("风格模板", test_style_templates),
        ("输出Schema", test_output_schemas),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ 测试 '{name}' 发生异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status}: {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit(main())
