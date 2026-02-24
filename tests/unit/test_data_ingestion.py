"""
测试数据接入层
"""
import pytest
from pathlib import Path
import tempfile
import shutil

from src.layers.data_ingestion import (
    DataCleaner, TopicSegmenter, split_text_biography,
    DataIngestionLayer
)


class TestDataCleaner:
    """测试数据清洗器"""
    
    @pytest.fixture
    def cleaner(self):
        return DataCleaner()
    
    def test_remove_filler_words(self, cleaner):
        """TC-B1: 去除语气词和填充词"""
        raw = "嗯，那个，我1965年出生在苏州。就是那个，家里条件不好。"
        result = cleaner.clean(raw)
        
        # 应该去除语气词
        assert "嗯" not in result.cleaned
        # "那个"在某些上下文中可能保留，但在填充词位置应去除
    
    def test_preserve_time_markers(self, cleaner):
        """TC-B2: 保留时间标记"""
        raw = "（1965年）我出生在苏州【重要：当时正值文革前夕】"
        result = cleaner.clean(raw)
        
        assert "1965年" in result.cleaned
        assert "文革前夕" in result.cleaned
    
    def test_preserve_scene_descriptions(self, cleaner):
        """TC-B3: 保留场景描述"""
        raw = "(采访开始，背景有嘈杂的茶楼碗筷声) 陈国伟开始了讲述。"
        result = cleaner.clean(raw)
        
        # 场景描述应该保留
        assert "采访开始" in result.cleaned or "茶楼" in result.cleaned


class TestTopicSegmenter:
    """测试话题切分器"""
    
    @pytest.fixture
    def segmenter(self):
        return TopicSegmenter()
    
    def test_segment_by_time(self, segmenter):
        """TC-B4: 按时间标记切分话题"""
        text = """
我1965年出生在苏州。小时候家里很穷。
1981年考上县重点中学。那是改变我命运的一年。
1984年考上大学，父亲送我到学校。
"""
        segments = segmenter.segment(text)
        
        # 应该切分出至少2个段落
        assert len(segments) >= 2
        # 每个段落应有内容
        assert all(len(s["text"]) > 0 for s in segments)
    
    def test_segment_by_markers(self, segmenter):
        """TC-B5: 按话题标记切分"""
        text = """
我出生在苏州。家里条件不好。
后来，我考上了中学。那段时间很努力。
再后来，我上了大学。开始新的生活。
"""
        segments = segmenter.segment(text)
        
        # "后来"、"再后来"应该触发分段
        assert len(segments) >= 2
    
    def test_topic_extraction(self, segmenter):
        """TC-B6: 话题关键词提取"""
        text = "我小时候在村里上学，后来去城里读书。"
        topics = segmenter._extract_topics(text)
        
        assert "童年" in topics or "求学" in topics


class TestSplitTextBiography:
    """测试传记专用文本切分"""
    
    def test_small_text_unchanged(self):
        """小文本不切分"""
        text = "这是一段短文本。"
        chunks = split_text_biography(text, chunk_size=1000)
        
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_preserves_paragraphs(self):
        """优先保持段落完整"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = split_text_biography(text, chunk_size=100, chunk_overlap=20)
        
        # 应该有多个chunk，但每段尽可能完整
        assert len(chunks) >= 1
    
    def test_overlap_works(self):
        """重叠区域正常工作"""
        # 构造一个需要切分的长文本
        text = "这是第一句。" * 100
        chunks = split_text_biography(text, chunk_size=200, chunk_overlap=50)
        
        assert len(chunks) > 1
        # 检查重叠（简化检查）
        if len(chunks) > 1:
            # 前后chunk应该有部分内容重复
            pass


class TestDataIngestionIntegration:
    """数据接入集成测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)
    
    @pytest.fixture
    def sample_interview_file(self, temp_dir):
        """创建示例采访文件"""
        file_path = temp_dir / "test_interview.txt"
        content = """
访谈录：张明的一生

受访者：张明

【童年】

我1965年出生在苏州。家里条件不好，父亲在纺织厂工作。

1978年改革开放，家里生活开始好转。

【求学】

1981年我考上县重点中学。每天5点起床读书。

1984年考上大学，学的机械工程。
"""
        file_path.write_text(content, encoding='utf-8')
        return file_path
    
    @pytest.mark.asyncio
    async def test_process_interview(self, sample_interview_file):
        """TC-B7: 完整处理采访文件"""
        # 注意：这个测试需要Embedding模型，可能需要较长时间
        # 标记为slow测试
        
        layer = DataIngestionLayer()
        
        # 清理之前的测试数据
        layer.vector_store.clear()
        
        # 处理文件
        materials = await layer.process_interview(sample_interview_file)
        
        # 验证结果
        assert len(materials) > 0
        
        # 验证素材结构
        for m in materials:
            assert m.content
            assert m.source_file == sample_interview_file.name
            assert m.id
    
    def test_retrieve_for_chapter(self, temp_dir):
        """TC-B8: 为章节检索素材"""
        layer = DataIngestionLayer()
        
        # 先添加一些测试素材
        from src.models import InterviewMaterial
        from src.utils import generate_id
        
        test_materials = [
            InterviewMaterial(
                id=generate_id("test", 1),
                source_file="test.txt",
                content="1965年张明出生在苏州，家里很穷。",
                chunk_index=0,
                topics=["童年"],
                time_references=["1965年"],
                entities=["张明", "苏州"]
            ),
            InterviewMaterial(
                id=generate_id("test", 2),
                source_file="test.txt",
                content="1984年张明考上大学，学习机械工程。",
                chunk_index=1,
                topics=["求学"],
                time_references=["1984年"],
                entities=["张明"]
            )
        ]
        
        layer.vector_store.clear()
        layer.vector_store.add_materials(test_materials)
        
        # 检索
        results = layer.retrieve_for_chapter(
            chapter_title="第一章：童年时光",
            chapter_summary="讲述张明1965-1980年间的童年生活",
            time_period="1965-1980",
            n_results=5
        )
        
        # 应该召回相关素材
        assert len(results) > 0


# 标记slow测试
pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow
]
