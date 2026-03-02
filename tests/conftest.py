"""
Pytest配置和全局fixture
"""
import pytest
import asyncio
from pathlib import Path
import sys

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.mocks import MockLLM, MockVectorStore


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_llm():
    """提供Mock LLM实例"""
    return MockLLM()


@pytest.fixture
def mock_vector_store():
    """提供Mock向量存储"""
    return MockVectorStore()


@pytest.fixture
def sample_interview_text():
    """提供示例采访文本"""
    return """
访谈录数据：张明的一生（1965-2020）

受访者：张明（男，55岁）
采访时间：2020年3月
地点：北京某咖啡馆

【童年时期】

Q：张总，您先做个自我介绍，讲讲您小时候的事。

张明：我是65年的，属蛇。老家在江苏苏州。那时候家里条件不好，我爸是纺织厂工人，我妈在家带孩子。

我记得最清楚的是78年改革开放，那时候我13岁。家里开始能吃饱饭了，我爸还从厂里带回来一些碎布头，我妈给我们做衣服。

【求学时期】

Q：后来您怎么考上大学的？

张明：我81年考上县重点中学。那时候高考刚恢复没几年，大家都拼命读书。我每天早上5点起床，晚上11点才睡。

84年考上大学，学的机械工程。那是我第一次离开苏州，坐火车去南京。
"""


@pytest.fixture
def sample_chen_guowei_text():
    """提供陈国伟采访文本"""
    return """
访谈录数据：陈国伟的一生（1965-2026）

受访者：陈国伟（男，61岁）
采访时间：2026年2月15日
地点：广州某早茶店

【第一部分：饥饿与水的记忆（1965-1978）】

Q：陈叔，您可以先做个自我介绍，讲讲您小时候的事。

陈国伟：我是65年的蛇，属蛇的。老家在南海那边，现在的佛山。

我家里排行老三，上面两个姐姐，下面一个弟弟。那时候讲究"人多力量大"，但人多嘴也多啊。

我记得有一次，我偷了生产队的一根甘蔗，被队长抓住了。我爸没打我，就在门口坐着抽烟，抽那种自己卷的旱烟，一晚上没说话。那个沉默比打我一顿还难受。

【第二部分：南风窗打开了（1979-1988）】

Q：改革开放开始的时候，您应该十几岁，当时广东这边变化很大吧？

陈国伟：82年，我高中没毕业就出来做事了。一开始在镇上的藤编厂，编那个椅子。一个月能拿30多块钱。

84年，我第一次离开佛山，去了广州。那时候广州火车站乱啊，真的乱。我在流花湖那边倒腾过服装。
"""


def pytest_configure(config):
    """Pytest配置"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
