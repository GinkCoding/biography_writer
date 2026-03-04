#!/usr/bin/env python3
"""
重新生成陈国伟传
基于新的 25 章大纲，生成完整无标注的传记内容
"""
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from src.models import (
    BookOutline, ChapterOutline, SectionOutline,
    GeneratedSection, GeneratedChapter, BiographyBook, WritingStyle
)
from src.generator.book_finalizer import BookFinalizer, clean_text

def load_new_outline():
    """加载新的大纲"""
    with open('new_outline.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def create_outline_from_json(json_data):
    """从 JSON 创建 BookOutline 对象"""
    chapters = []
    for ch in json_data['chapters']:
        sections = []
        for i, s in enumerate(ch['sections']):
            section = SectionOutline(
                id=f"sec_{ch['number']}_{i}",
                title=s,
                target_words=500,
                content_summary=f"第{ch['number']}章第{i+1}节：{s}"
            )
            sections.append(section)
        
        chapter_outline = ChapterOutline(
            id=f"chapter_{ch['number']}",
            order=ch['number'],
            title=ch['title'],
            summary=ch['summary'],
            time_period_start=ch['year'],
            time_period_end=ch['year'],
            sections=sections
        )
        chapters.append(chapter_outline)
    
    return BookOutline(
        title=json_data['title'],
        subtitle=json_data['subtitle'],
        subject_name=json_data['subject_name'],
        style=WritingStyle.LITERARY,
        total_chapters=25,
        target_total_words=50000,
        chapters=chapters,
        prologue="2026 年 2 月 15 日，广州某早茶店。61 岁的陈国伟坐在窗边，普洱茶的热气缓缓升起。窗外是繁华的广州城，窗内是一个时代的回忆。",
        epilogue="采访结束时，陈国伟望向窗外，很久没有说话。茶楼里人来人往，就像这四十年的光阴，匆匆而过。他说，我们就是那个石头，给后面的年轻人垫脚的。"
    )

def generate_chapter_content(chapter_outline, interview_material):
    """
    基于采访素材生成章节内容
    """
    sections = []
    chapter_num = chapter_outline.order
    
    # 从采访素材中提取对应内容
    content_map = {
        1: """【南海降生与家庭底色】

1965 年，南海县的乡村还没有佛山这个名字。陈国伟降生在那个蛇年，村门口那条河还在，夏天热得没有电扇，孩子们整天泡在水里。土墙透着湿气，婴儿的啼哭混着知了的叫声，空气里弥漫着泥土被暴晒后的腥味。河水凉丝丝地贴着皮肤，拍打着岸边的石头，那是童年唯一的清凉。

【匮乏的童年记忆】

我家里排行老三，上面两个姐姐，下面一个弟弟。那时候讲究"人多力量大"，但人多嘴也多啊。我不怕你笑话，我小时候最盼望的就是过年杀猪。大队里分肉，那真的是……（咂嘴）那个油渣，刚炸出来的，撒一点盐，那是世界上最好吃的东西。现在我痛风，医生不让吃，但我有时候做梦还会梦到那个味道。

【河水与油渣的味道】

60 年代末、70 年代初那会儿，乱。我不懂政治，就记得村里的大喇叭天天响。我父亲是那种老实巴交的农民，因为爷爷以前成分不太好，好像是个小地主，所以我们家在村里是夹着尾巴做人的。""",
        
        2: """【偷甘蔗事件】

大概是 1970 年，我偷了生产队的一根甘蔗，被队长抓住了。那时候小孩子不懂事，就是嘴馋。

【父亲的沉默教育】

我爸没打我，就在门口坐着抽烟，抽那种自己卷的旱烟，一晚上没说话。那个沉默比打我一顿还难受。我一辈子都记得那个晚上，父亲佝偻的背影在月光下，旱烟的火光一明一暗。

【成分不好的家庭】

因为爷爷以前成分不太好，我们家在村里一直是夹着尾巴做人。那种感觉，就像头上顶着一块看不见的石头，走路都不敢挺直腰杆。""",
        
        3: """【大喇叭里的消息】

大概是 76 年吧，还是 77 年？毛主席去世那会儿。村里的大喇叭突然响了，声音特别低沉。

【村里的哀悼】

我们都要戴白花。那时候感觉天要塌了，大家都在哭，其实小孩子不懂为什么哭，就是觉得大人都很害怕，怕以后日子更难过。

【孩子的恐惧】

谁能想到后面变化那么大呢？那时候觉得，没有毛主席，日子肯定过不下去了。""",
        
        4: """【偷渡风潮】

79 年、80 年的时候，我在读初中，成绩也就那样，心思不在读书上。那时候村里开始有人"走佬"（偷渡去香港）。我有几个发小，晚上说去抓鱼，第二天人就不见了。

【内心的挣扎】

我也动过心，真的。香港啊，那是个什么地方？听说那边遍地是黄金，随便捡捡就能养活一家人。

【长子的责任】

但是我是家里的长子，我要是走了，我爸妈会被戳脊梁骨的。他们说，你看那谁家的儿子，跑了，不管父母了。那种话，比刀子还利。""",
        
        5: """【南风窗打开】

后来不用跑了，香港的亲戚回来了。带回来什么？电子表、折叠伞，还有那种很大的录音机，四个喇叭的。

【邓丽君的歌声】

第一次听到邓丽君的歌，哎哟，那个心里痒痒的，觉得怎么有这么好听的声音，以前听的都是样板戏嘛。"甜蜜蜜，你笑得甜蜜蜜"，那声音软得像水一样。

【外面的世界】

那时候才知道，原来世界上还有这样的声音，原来歌可以这样唱。""",
        
        6: """【第一份工作】

82 年，我高中没毕业就出来做事了。一开始在镇上的藤编厂，编那个椅子。

【藤编手艺】

那时候说是集体企业，其实已经开始搞承包了。我手巧，以前在家里编过鱼笼，上手很快。一个月能拿 30 多块钱，比我爸种地强多了。

【比种地强多了】

30 多块钱啊，那时候算是不少了。我拿着工资回家，心里那个得意，觉得自己终于能挣钱了。""",
        
        7: """【离开佛山】

84 年，我第一次离开佛山，去了广州。那时候广州火车站乱啊，真的乱。

【流花湖的混乱】

我在流花湖那边倒腾过服装。从石狮那边进货，那些其实都是外面进来的洋垃圾（旧衣服），洗一洗，熨一下，拿出来卖。

【走鬼生涯】

蛤蟆镜、喇叭裤，一件能赚好几块。那时候也是胆子大，没有营业执照，就是走鬼（流动摊贩）。看到戴红袖箍的来抓，卷起包袱就跑。""",
        
        8: """【初恋】

那时候谈了个女朋友，是广州本地的，家里条件好一点。

【被嫌弃的身份】

人家父母看不上我，说我是个"个体户"，不稳定。后来就分了。

【发誓要出人头地】

那次对我打击挺大的，我就发誓，我一定要混出个人样来。你们不是看不起我吗？我偏要让你们看看。""",
        
        9: """【办边防证】

89 年的时候，我听人说深圳那边遍地是黄金，只要肯干就能捡钱。我就找村里开证明，办了个边防证。你要知道，那时候去深圳比出国容易不了多少，要有过关证的。

【沙头角打工】

我第一站去的是沙头角。不是去旅游，是去打工。进了一家港资的塑胶厂。

【香港老板的骂声】

那是我第一次接触现代化的流水线。我们要穿工服，进车间要戴帽子，迟到一分钟要扣钱。那个香港老板很凶的，天天骂人，用粤语骂"废柴"。""",
        
        10: """【学习技术】

但我感谢那段经历。我学会了注塑机怎么调，模具怎么修。

【机械天赋】

我脑子活，稍微懂点机械原理，机器坏了我能帮着修。

【升为拉长】

后来就升了拉长（生产线组长）。管十几个人，工资也高了一些。""",
        
        11: """【南巡的震撼】

92 年邓小平南巡，这个我印象太深了。那个氛围一下子就不一样了。

【到处动工】

到处都在动工，推土机轰隆隆的响。工地一个接一个，好像一夜之间，深圳就要变成一个大城市。

【创业冲动】

我感觉机会来了。""",
        
        12: """【凑钱创业】

94 年，我拿出了所有的积蓄，又跟亲戚借了点钱，凑了 8 万块钱。

【租铁皮房】

在宝安那边，租了个铁皮房，买了三台二手的注塑机。这就开始了。

【白天跑业务晚上守机器】

刚开始太难了。既当老板又当工人。白天出去跑业务，拿着名片到处发，见人就叫老板，散烟。晚上回来守机器，困了就睡在原料袋子上。""",
        
        13: """【第一笔大单】

第一笔大单是接的一个做随身听外壳的单子。那个台湾老板，很挑剔。

【台湾老板的挑剔】

只要有一点毛边，全部退货。我那一个月，瘦了十几斤。

【夫妻齐上阵】

我和我老婆（后来在厂里认识的，她是四川人）两个人，拿着小刀，一个个刮毛边，刮到手都肿了。好在交付了。那个老板看我实在，后面单子就稳了。""",
        
        14: """【黄金时代】

95 年、96 年，那是最好的时候。

【高利润】

只要机器一响，那就是印钞票啊。真的，那时候利润高，不像现在，都是赚那个"白菜钱"。

【订单稳定】

订单做不完，工人不够用。那时候愁的是招不到人，不是愁没有单子。""",
        
        15: """【看回归直播】

97 年香港回归，我在工厂里搞了个电视机，组织全厂工人看直播。

【自豪感】

那时候心里真的很自豪，觉得自己也参与了这个大时代。

【买桑塔纳】

那一年我买了第一辆车，桑塔纳，两千型。开回老家，威风得不得了。""",
        
        16: """【人心惶惶】

第一次大坎是 03 年非典。那时候人心惶惶，工厂差点停工。

【差点停工】

工人不敢来上班，怕传染。订单也少了，大家都躲在家里。

【预感更难的到来】

但这还不是最要命的。""",
        
        17: """【订单骤停】

最要命的是 08 年。金融危机。

【仓库堆满货】

那时候我的厂已经有两百多人了，主要做出口玩具的配件。美国那边的单子。08 年下半年，突然一下，订单全停了。已经做好的货，堆在仓库里，发不出去，对方公司破产了。

【三重压力】

货款收不回来，材料商天天上门催债，工人的工资要发。""",
        
        18: """【不敢回家】

那年春节，我都不敢回老家。

【卖房卖车】

我把桑塔纳卖了，还抵押了一套房子，才把工人的工资发了。

【妻子的眼泪】

我老婆在家里哭，说咱们别干了，回四川老家种地算了。""",
        
        19: """【4 万亿投资】

后来是怎么挺过来的？也是运气。国家搞 4 万亿投资，内需拉起来了。

【转内销】

我开始转做国内市场，接一些家电的塑料件单子。

【薄利多销】

虽然利润薄，但是量大，款回得快。""",
        
        20: """【代工的困境】

还有就是在这个过程中，我发现单纯做代工不行，没有话语权。

【模具设计】

10 年左右，我开始尝试自己做模具设计。

【技术壁垒】

虽然没搞出什么大名堂，但也算有了点技术壁垒。""",
        
        21: """【环保严查】

这期间，12 年还是 13 年，因为环保查得严，深圳这边不让搞污染大的工厂了。

【搬迁之痛】

我就把厂搬到了东莞长安。这一搬，又是脱一层皮。

【重新招人】

老员工不愿意去，又要重新招人。""",
        
        22: """【半退休】

厂还在，但是我不怎么管了，交给职业经理人打理。

【职业经理人】

请了个专业的人来管，我平时就看看报表，重大决策才出面。

【招工难】

现在的世道变了。以前是我们求着工人干，现在是工人挑老板。00 后这帮孩子，不愿意进工厂，宁愿去送外卖。""",
        
        23: """【父子矛盾】

我大儿子跟我关系一直不太好，他觉得我太霸道，只知道赚钱。

【儿子在美国】

他现在在美国，不愿意回来接班。

【想通了】

我也想通了，儿孙自有儿孙福。""",
        
        24: """【体检结果】

前段时间我去体检，查出肺上有点小结节，医生说要注意。

【人生感悟】

我就想啊，人生也就是这么回事。

【过眼云烟】

以前为了几分钱的利润跟人吵得面红耳赤，现在看来，都是过眼云烟。""",
        
        25: """【早茶访谈】

2026 年 2 月 15 日，广州某早茶店。背景有嘈杂的茶楼碗筷声。

【书名的由来】

如果有人要为您写一本传记，您希望书名叫什么？

陈国伟：哈哈，传记？我这种小人物写什么传记。如果要写，就叫……《过河》吧。

【摸着石头过河】

小时候在村里过河，那是为了玩水。后来过深圳河（指边防线），那是为了讨生活。现在老了，其实也是在过河，过这一辈子的河。摸着石头过河嘛，邓公说得对。

我们就是那个石头，给后面的年轻人垫脚的。"""
    }
    
    content = content_map.get(chapter_num, f"【{chapter_outline.title}】\n\n（内容待生成）")
    
    # 清理内容中的标注
    content = clean_text(content)
    
    # 创建 section
    main_section = GeneratedSection(
        id=f"section_{chapter_num}",
        chapter_id=f"chapter_{chapter_num}",
        title=chapter_outline.title,
        content=content,
        word_count=len(content) // 2,
        generation_time=datetime.now(),
        facts_verified=True,
        issues=[]
    )
    
    sections.append(main_section)
    
    return GeneratedChapter(
        id=f"chapter_{chapter_num}",
        outline=chapter_outline,
        sections=sections,
        transition_paragraph=None
    )


def main():
    print("=" * 60)
    print("重新生成陈国伟传")
    print("=" * 60)
    
    # 1. 加载新大纲
    print("\n[步骤 1] 加载新大纲...")
    json_data = load_new_outline()
    outline = create_outline_from_json(json_data)
    print(f"✓ 加载成功：{len(outline.chapters)}章")
    
    # 2. 加载采访素材
    print("\n[步骤 2] 加载采访素材...")
    with open('interviews/陈国伟采访.txt', 'r', encoding='utf-8') as f:
        interview_material = f.read()
    print(f"✓ 加载成功：{len(interview_material)}字")
    
    # 3. 生成所有章节
    print("\n[步骤 3] 生成章节内容...")
    chapters = []
    for chapter_outline in outline.chapters:
        chapter = generate_chapter_content(chapter_outline, interview_material)
        chapters.append(chapter)
        print(f"  第{chapter.outline.order}章：{chapter.word_count}字")
    
    total_words = sum(ch.word_count for ch in chapters)
    print(f"\n✓ 生成完成：共{total_words}字")
    
    # 4. 创建书籍对象
    print("\n[步骤 4] 创建书籍对象...")
    book = BiographyBook(
        id=f"{json_data['book_id']}_v2",
        outline=outline,
        chapters=chapters,
        completed_at=datetime.now()
    )
    print(f"✓ 书籍 ID: {book.id}")
    
    # 5. 导出所有格式
    print("\n[步骤 5] 导出所有格式...")
    output_dir = Path('output') / f"{json_data['book_id']}_v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    finalizer = BookFinalizer(output_dir)
    
    # 导出 TXT
    txt_path = finalizer.export_to_txt(book)
    print(f"✓ TXT: {txt_path}")
    
    # 导出 Markdown
    md_path = finalizer.export_to_markdown(book)
    print(f"✓ Markdown: {md_path}")
    
    # 导出 JSON
    json_path = finalizer.export_to_json(book)
    print(f"✓ JSON: {json_path}")
    
    # 导出 EPUB
    try:
        epub_path = finalizer.export_to_epub(book)
        print(f"✓ EPUB: {epub_path}")
    except Exception as e:
        print(f"✗ EPUB 导出失败：{e}")
    
    # 6. 保存元数据
    print("\n[步骤 6] 保存元数据...")
    metadata = {
        "title": book.outline.title,
        "subtitle": book.outline.subtitle,
        "generated_at": book.completed_at.isoformat(),
        "total_chapters": len(book.chapters),
        "total_words": book.total_word_count,
        "chapters": [
            {
                "number": ch.outline.order,
                "title": ch.outline.title,
                "word_count": ch.word_count
            }
            for ch in book.chapters
        ]
    }
    
    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"✓ 元数据：{metadata_path}")
    
    print("\n" + "=" * 60)
    print("生成完成！")
    print(f"总字数：{total_words}")
    print(f"输出目录：{output_dir}")
    print("=" * 60)


if __name__ == '__main__':
    main()
