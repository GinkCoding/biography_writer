"""
生成模块集成测试
"""
import pytest
from pathlib import Path

from src.layers.generation import (
    ContextAssembler, ContentGenerationEngine, IterativeGenerationLayer
)
from src.models import (
    BookOutline, ChapterOutline, SectionOutline, 
    WritingStyle, GlobalState
)
from tests.mocks import MockLLM, MockVectorStore, MockContentGenerator


class TestContextAssembler:
    """测试上下文组装器"""
    
    @pytest.fixture
    def mock_llm(self):
        return MockLLM()
    
    @pytest.fixture
    def mock_vector_store(self):
        store = MockVectorStore()
        # 添加一些测试素材
        from src.models import InterviewMaterial
        from src.utils import generate_id
        
        materials = [
            InterviewMaterial(
                id=generate_id("test", 1),
                source_file="test.txt",
                content="1965年陈国伟出生在佛山陈家村。家里排行老三。",
                chunk_index=0,
                topics=["童年"],
                time_references=["1965年"],
                entities=["陈国伟", "佛山", "陈家村"]
            )
        ]
        store.add_materials(materials)
        return store
    
    @pytest.fixture
    def sample_chapter(self):
        return ChapterOutline(
            id="ch1",
            title="第一章：童年时光",
            order=1,
            summary="讲述陈国伟的童年经历",
            sections=[
                SectionOutline(
                    id="s1",
                    title="陈家村的日子",
                    target_words=2000,
                    content_summary="描述1965年出生的背景和家庭情况",
                    key_events=["1965年出生"],
                    emotional_tone="怀旧"
                )
            ],
            time_period_start="1965",
            time_period_end="1978"
        )
    
    @pytest.fixture
    def sample_outline(self):
        return BookOutline(
            id="book1",
            title="陈国伟传",
            subtitle="一个佛山企业家的真实人生",
            subject_name="陈国伟",
            style=WritingStyle.LITERARY,
            total_chapters=5,
            target_total_words=10000,
            chapters=[]
        )
    
    @pytest.mark.asyncio
    async def test_assemble_context(self, mock_llm, mock_vector_store, sample_chapter, sample_outline):
        """TC-C1: 测试上下文组装"""
        assembler = ContextAssembler(mock_llm, mock_vector_store)
        
        global_state = {
            "subject_name": "陈国伟",
            "subject_age": "61",
            "chapter_progress": "第1章/共5章"
        }
        
        context = await assembler.assemble_context(
            section=sample_chapter.sections[0],
            chapter=sample_chapter,
            outline=sample_outline,
            global_state=global_state
        )
        
        # 验证上下文包含必要字段
        assert "global" in context
        assert "section" in context
        assert "materials" in context
        assert "continuity" in context
        assert "era" in context
        
        # 验证素材已检索
        assert "相关素材" in context["materials"]
    
    @pytest.mark.asyncio
    async def test_retrieve_materials_enhanced(self, mock_llm, mock_vector_store, sample_chapter, sample_outline):
        """TC-C2: 测试素材检索"""
        assembler = ContextAssembler(mock_llm, mock_vector_store)
        
        materials_text = await assembler._retrieve_materials_enhanced(
            section=sample_chapter.sections[0],
            chapter=sample_chapter
        )
        
        # 应该检索到素材
        assert "素材" in materials_text
        # 应该包含具体细节
        assert "1965" in materials_text or "佛山" in materials_text or "陈家村" in materials_text


class TestContentGenerationEngine:
    """测试内容生成引擎"""
    
    @pytest.fixture
    def engine(self):
        mock_llm = MockLLM()
        return ContentGenerationEngine(mock_llm)
    
    def test_build_system_prompt(self, engine):
        """TC-C3: 测试系统提示词构建"""
        prompt = engine._build_system_prompt(WritingStyle.LITERARY)
        
        # 验证关键约束存在
        assert "禁止事项" in prompt
        assert "占位符" in prompt
        assert "模板套话" in prompt
        assert "正反面示例" in prompt
    
    def test_detect_placeholders(self, engine):
        """TC-C4: 测试占位符检测"""
        content_with_placeholder = "这里有一些内容。此处需要补充更多细节。"
        issues = engine._detect_placeholders(content_with_placeholder)
        
        assert len(issues) > 0
        assert any("占位符" in i for i in issues)
    
    def test_detect_placeholders_clean(self, engine):
        """TC-C5: 测试干净内容无占位符"""
        clean_content = "1965年，张明出生在苏州。家里条件不好。"
        issues = engine._detect_placeholders(clean_content)
        
        assert len(issues) == 0


class TestGenerationQuality:
    """生成质量测试"""
    
    def test_mock_content_variants(self):
        """TC-C6: 测试Mock内容生成器的各种变体"""
        generator = MockContentGenerator()
        
        # 测试干净内容
        clean = generator.generate_clean_content()
        assert "1965" in clean
        assert "来源：素材" in clean
        
        # 测试有问题内容
        bad = generator.generate_content_with_placeholder()
        assert "待补充" in bad
        
        template = generator.generate_content_with_templates()
        assert "尘埃" in template
    
    @pytest.mark.asyncio
    async def test_generation_with_mock_llm(self):
        """TC-C7: 使用Mock LLM测试完整生成流程"""
        mock_llm = MockLLM()
        mock_llm.set_default_response("""
1965年，陈国伟出生在佛山南海的陈家村（来源：素材1）。
家里排行老三，上面有两个姐姐，下面有一个弟弟。
父亲陈大勇是老实巴交的农民，因为爷爷是小地主，家里夹着尾巴做人。
""")
        
        engine = ContentGenerationEngine(mock_llm)
        
        context = {
            "global": "传记标题: 陈国伟传",
            "section": "章节: 第一章：童年时光\n小节: 陈家村的日子",
            "materials": "=== 相关素材 ===\n[素材1] 1965年陈国伟出生在佛山陈家村",
            "continuity": "",
            "era": "时间: 1965年代",
            "section_title": "陈家村的日子"
        }
        
        section = await engine.generate_section(
            context=context,
            style=WritingStyle.LITERARY,
            target_words=1000
        )
        
        # 验证生成结果
        assert section.content
        assert section.word_count > 0
        
        # 验证调用了LLM
        assert mock_llm.get_call_count() > 0


# 标记集成测试
pytestmark = [
    pytest.mark.integration
]
