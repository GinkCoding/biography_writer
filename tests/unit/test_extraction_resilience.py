"""关键信息提取与容错能力测试。"""

from pathlib import Path

import pytest

from src.layers.data_ingestion import DataCleaner, DataIngestionLayer, TopicSegmenter
from src.observability.runtime_monitor import get_runtime_monitor
from src.utils import extract_entities, extract_key_information, extract_time_expressions


class _NoopVectorStore:
    """测试用向量存储桩，避免真实 embedding 依赖。"""

    def __init__(self):
        self.saved = []

    def add_materials(self, materials):
        self.saved.extend(materials)


class _ResilientDataIngestionLayer(DataIngestionLayer):
    """跳过真实向量库初始化的轻量版本。"""

    def __init__(self):
        self.cleaner = DataCleaner()
        self.segmenter = TopicSegmenter()
        self.vector_store = _NoopVectorStore()
        self.retriever = None
        self.runtime_monitor = get_runtime_monitor(project_root=Path(__file__).resolve().parents[2])


@pytest.mark.unit
def test_extract_time_expressions_with_noisy_text():
    text = "我１９８４年５月6日到上海，后来在1990年代又去了深圳。"
    results = extract_time_expressions(text)
    assert results
    assert any(item.get("normalized") == "1984-05-06" for item in results)
    assert any(item.get("type") == "relative" for item in results)


@pytest.mark.unit
def test_extract_entities_with_roles_and_orgs():
    text = "父亲张建国在苏州市纺织厂工作，后来调到广东省佛山市南海区。"
    entities = extract_entities(text)
    assert any(item.get("type") == "PERSON" and "张建国" in item.get("text", "") for item in entities)
    assert any(item.get("type") == "LOCATION" for item in entities)
    assert any(item.get("type") == "ORG" for item in entities)


@pytest.mark.unit
def test_extract_key_information_never_raises():
    info = extract_key_information(None)
    assert isinstance(info, dict)
    assert "warnings" in info
    assert info["warnings"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_process_interview_fallback_when_extractor_fails(tmp_path, monkeypatch):
    interview = tmp_path / "采访.txt"
    interview.write_text(
        "1988年我考上大学。后来在工厂工作。母亲李桂芳一直支持我。",
        encoding="utf-8",
    )

    def _raise_extractor(_text):
        raise RuntimeError("simulated extractor failure")

    monkeypatch.setattr("src.layers.data_ingestion.extract_key_information", _raise_extractor)

    layer = _ResilientDataIngestionLayer()
    materials = await layer.process_interview(interview)

    assert materials
    assert all(material.content for material in materials)
    assert any("1988" in " ".join(material.time_references) for material in materials)
