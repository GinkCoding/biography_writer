"""测试提示词模板系统"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from src.prompt_manager import (
    PromptManager,
    get_prompt_manager,
    ContextLevel,
    WritingStyle,
    render_prompt
)


def test_basic_rendering():
    """测试基本模板渲染"""
    print("=" * 60)
    print("测试1: 基本模板渲染")
    print("=" * 60)

    pm = get_prompt_manager()

    # 测试加载基础模板
    try:
        template = pm.load_template("system/base.j2")
        print(f"✓ 成功加载基础模板: {template.name}")
    except Exception as e:
        print(f"✗ 加载基础模板失败: {e}")
        return False

    # 测试渲染基础模板
    try:
        result = pm.render("system/base.j2", {
            "style_name": "纪实",
            "style_description": "客观真实的记录风格",
            "role_anchor": "你是一位纪实作家"
        })
        print(f"✓ 成功渲染基础模板")
        print(f"  渲染结果长度: {len(result)} 字符")
    except Exception as e:
        print(f"✗ 渲染基础模板失败: {e}")
        return False

    return True


def test_style_templates():
    """测试风格模板"""
    print("\n" + "=" * 60)
    print("测试2: 风格模板")
    print("=" * 60)

    pm = get_prompt_manager()
    styles = ["documentary", "literary", "investigative", "memoir"]

    for style in styles:
        try:
            result = pm.render_style_prompt(
                style=WritingStyle(style),
                context={"context_level": "l1"}
            )
            print(f"✓ 成功渲染 {style} 风格模板")
            print(f"  渲染结果长度: {len(result)} 字符")
        except Exception as e:
            print(f"✗ 渲染 {style} 风格模板失败: {e}")
            return False

    return True


def test_context_levels():
    """测试上下文级别"""
    print("\n" + "=" * 60)
    print("测试3: 上下文级别 (L0-L3)")
    print("=" * 60)

    pm = get_prompt_manager()
    levels = [
        ContextLevel.L0_MINIMAL,
        ContextLevel.L1_ESSENTIAL,
        ContextLevel.L2_EXTENDED,
        ContextLevel.L3_COMPLETE
    ]

    for level in levels:
        try:
            result = pm.render_for_context_level(
                template_name="system/generation.j2",
                context_level=level,
                base_context={"style": "documentary"}
            )
            print(f"✓ 成功渲染 {level.value} 级别")
            print(f"  渲染结果长度: {len(result)} 字符")
        except Exception as e:
            print(f"✗ 渲染 {level.value} 级别失败: {e}")
            return False

    return True


def test_examples_and_constraints():
    """测试示例和约束获取"""
    print("\n" + "=" * 60)
    print("测试4: 示例和约束")
    print("=" * 60)

    pm = get_prompt_manager()

    # 测试获取示例
    examples = pm.get_examples(category="concrete_detail")
    print(f"✓ 获取到 {len(examples)} 个具体细节示例")

    positive_examples = pm.get_examples(category="concrete_detail", positive=True)
    print(f"✓ 获取到 {len(positive_examples)} 个正面示例")

    # 测试获取约束
    constraints = pm.get_constraints(category="general")
    print(f"✓ 获取到 {len(constraints)} 个通用约束")

    hard_constraints = pm.get_constraints(category="general", hard_only=True)
    print(f"✓ 获取到 {len(hard_constraints)} 个硬约束")

    return True


def test_output_schemas():
    """测试输出Schema"""
    print("\n" + "=" * 60)
    print("测试5: 输出Schema")
    print("=" * 60)

    pm = get_prompt_manager()

    schemas = pm.list_available_schemas()
    print(f"✓ 可用Schemas: {schemas}")

    for schema_name in schemas:
        schema = pm.get_output_schema(schema_name)
        if schema:
            print(f"✓ 成功加载 {schema_name} schema")
            print(f"  标题: {schema.get('title', 'N/A')}")
        else:
            print(f"✗ 加载 {schema_name} schema 失败")
            return False

    return True


def test_review_prompts():
    """测试审校提示词"""
    print("\n" + "=" * 60)
    print("测试6: 审校提示词")
    print("=" * 60)

    pm = get_prompt_manager()

    review_types = ["continuity", "fact_check", "quality", "placeholder_check"]

    for review_type in review_types:
        try:
            result = pm.render_review_prompt(
                review_type=review_type,
                context={"chapter_info": "第1章", "previous_chapter_info": None},
                context_level=ContextLevel.L1_ESSENTIAL
            )
            print(f"✓ 成功渲染 {review_type} 审校提示词")
            print(f"  渲染结果长度: {len(result)} 字符")
        except Exception as e:
            print(f"✗ 渲染 {review_type} 审校提示词失败: {e}")
            return False

    return True


def test_extraction_prompts():
    """测试信息提取提示词"""
    print("\n" + "=" * 60)
    print("测试7: 信息提取提示词")
    print("=" * 60)

    pm = get_prompt_manager()

    extraction_types = ["entities", "timeline", "character_state", "scenes"]

    for extraction_type in extraction_types:
        try:
            result = pm.render_extraction_prompt(
                extraction_type=extraction_type,
                context={"content": "这是示例内容"}
            )
            print(f"✓ 成功渲染 {extraction_type} 提取提示词")
            print(f"  渲染结果长度: {len(result)} 字符")
        except Exception as e:
            print(f"✗ 渲染 {extraction_type} 提取提示词失败: {e}")
            return False

    return True


def test_list_templates():
    """测试列出所有模板"""
    print("\n" + "=" * 60)
    print("测试8: 列出所有模板")
    print("=" * 60)

    pm = get_prompt_manager()

    templates = pm.list_available_templates()
    print(f"✓ 发现 {len(templates)} 个模板文件:")

    # 按目录分组
    by_dir = {}
    for t in templates:
        dir_name = t.split('/')[0] if '/' else 'root'
        by_dir.setdefault(dir_name, []).append(t)

    for dir_name, dir_templates in sorted(by_dir.items()):
        print(f"\n  [{dir_name}/]")
        for t in sorted(dir_templates)[:5]:  # 只显示前5个
            print(f"    - {t}")
        if len(dir_templates) > 5:
            print(f"    ... 还有 {len(dir_templates) - 5} 个")

    return True


def test_convenience_function():
    """测试便捷函数"""
    print("\n" + "=" * 60)
    print("测试9: 便捷函数")
    print("=" * 60)

    try:
        result = render_prompt("sections/constraints.j2")
        print(f"✓ render_prompt 便捷函数工作正常")
        print(f"  渲染结果长度: {len(result)} 字符")
    except Exception as e:
        print(f"✗ render_prompt 便捷函数失败: {e}")
        return False

    return True


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("提示词模板系统测试")
    print("=" * 60)

    tests = [
        ("基本模板渲染", test_basic_rendering),
        ("风格模板", test_style_templates),
        ("上下文级别", test_context_levels),
        ("示例和约束", test_examples_and_constraints),
        ("输出Schema", test_output_schemas),
        ("审校提示词", test_review_prompts),
        ("信息提取提示词", test_extraction_prompts),
        ("列出模板", test_list_templates),
        ("便捷函数", test_convenience_function),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ 测试 '{name}' 发生异常: {e}")
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
