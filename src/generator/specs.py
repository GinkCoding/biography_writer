"""章节规格定义"""
from .chapter_generator import ChapterSpec, SectionSpec


def get_chapter_specs() -> list:
    """获取所有章节规格"""
    
    # 第三章：闯深圳与第一桶金
    ch3 = ChapterSpec(
        chapter_num=3,
        title="第三章：闯深圳与第一桶金",
        time_range="1989-1998",
        summary="讲述陈国伟如何进入深圳，从流水线工人成长为工厂老板的过程。包括办理边防证、进入港资工厂、学习技术、遇到妻子、1992年南巡讲话后的创业决定、睡在原料袋子上的艰辛岁月、第一笔大单的挑战、以及1997年香港回归时买第一辆桑塔纳的喜悦。",
        target_words=20000,
        sections=[
            SectionSpec(
                title="一、过关证",
                target_words=5000,
                key_events=["办理边防证", "进入沙头角", "第一次接触现代化工厂"],
                characters=["陈国伟", "香港老板", "工友"],
                setting="1988年深圳沙头角",
                emotional_tone="期待、紧张、奋斗"
            ),
            SectionSpec(
                title="二、睡原料袋",
                target_words=5000,
                key_events=["升为拉长", "与王秀英相识", "1992年决定创业", "筹集8万元"],
                characters=["陈国伟", "王秀英", "亲戚"],
                setting="1989-1994年深圳宝安",
                emotional_tone="甜蜜、艰辛、决心"
            ),
            SectionSpec(
                title="三、刮毛边",
                target_words=5000,
                key_events=["租铁皮房", "买二手机器", "第一笔随身听外壳订单", "通宵刮毛边"],
                characters=["陈国伟", "王秀英", "台湾老板"],
                setting="1994-1995年深圳工厂",
                emotional_tone="艰辛、坚持、希望"
            ),
            SectionSpec(
                title="四、桑塔纳",
                target_words=5000,
                key_events=["1995-96年订单稳定", "1997年香港回归", "买第一辆桑塔纳", "开车回老家"],
                characters=["陈国伟", "全厂工人", "家人"],
                setting="1996-1997年深圳",
                emotional_tone="自豪、喜悦、成就感"
            )
        ]
    )
    
    # 第四章：危机与转型
    ch4 = ChapterSpec(
        chapter_num=4,
        title="第四章：危机与转型",
        time_range="1999-2015",
        summary="讲述陈国伟在2003年非典和2008年金融危机中经历的重大挫折，以及如何挺过难关、实现转型。包括非典期间的恐慌、08年订单断流的绝望、卖车抵押房发工资的艰难决定、国家4万亿救市政策的影响、从代工转向内销、以及因环保压力从深圳搬到东莞的过程。",
        target_words=20000,
        sections=[
            SectionSpec(
                title="一、人心惶惶",
                target_words=5000,
                key_events=["2003年非典", "工厂差点停工", "工人恐慌"],
                characters=["陈国伟", "工人", "客户"],
                setting="2003年深圳",
                emotional_tone="恐慌、焦虑、坚持"
            ),
            SectionSpec(
                title="二、空荡荡的车间",
                target_words=5000,
                key_events=["2008年金融危机", "美国订单断流", "货款收不回", "材料商催债"],
                characters=["陈国伟", "老婆", "材料商", "工人"],
                setting="2008年深圳工厂",
                emotional_tone="绝望、焦虑、不甘"
            ),
            SectionSpec(
                title="三、四万亿",
                target_words=5000,
                key_events=["卖桑塔纳", "抵押房子", "发工人工资", "国家4万亿", "转内销"],
                characters=["陈国伟", "老婆", "新客户"],
                setting="2008-2010年",
                emotional_tone="绝望中的希望、转机"
            ),
            SectionSpec(
                title="四、搬离深圳",
                target_words=5000,
                key_events=["环保严查", "从深圳搬到东莞长安", "老员工离职", "重新招人"],
                characters=["陈国伟", "老员工", "新工人"],
                setting="2012-2013年东莞",
                emotional_tone="无奈、重生、坚持"
            )
        ]
    )
    
    # 第五章：知天命
    ch5 = ChapterSpec(
        chapter_num=5,
        title="第五章：知天命",
        time_range="2016-至今",
        summary="讲述陈国伟退休后的生活状态和人生感悟。包括工厂交给职业经理人管理、招工难和00后不愿进厂的现象、与大儿子关系疏远的心结、体检发现肺结节后的感悟、以及对一生的回顾和总结。",
        target_words=20000,
        sections=[
            SectionSpec(
                title="一、零零后不进厂",
                target_words=5000,
                key_events=["退休", "工厂交给职业经理人", "招工难", "00后宁愿送外卖"],
                characters=["陈国伟", "职业经理人", "年轻工人"],
                setting="2016年后东莞",
                emotional_tone="感慨、理解、释然"
            ),
            SectionSpec(
                title="二、父子隔阂",
                target_words=5000,
                key_events=["大儿子去美国", "关系疏远", "不愿接班", "想通了"],
                characters=["陈国伟", "大儿子", "老婆"],
                setting="家庭场景",
                emotional_tone="遗憾、理解、接受"
            ),
            SectionSpec(
                title="三、肺结节",
                target_words=5000,
                key_events=["体检", "肺结节", "反思", "对金钱和生命的重新认识"],
                characters=["陈国伟", "医生"],
                setting="医院、家里",
                emotional_tone="震惊、反思、释然"
            ),
            SectionSpec(
                title="四、那块石头",
                target_words=5000,
                key_events=["接受采访", "回顾一生", "\"过河\"的含义", "给年轻人垫脚"],
                characters=["陈国伟", "采访者"],
                setting="广州早茶店",
                emotional_tone="豁达、智慧、传承"
            )
        ]
    )
    
    return [ch3, ch4, ch5]


def get_book_metadata() -> dict:
    """获取书籍元数据"""
    return {
        "title": "过河：陈国伟传",
        "subtitle": "一个广东实业家的大时代漂流",
        "subject": "陈国伟",
        "subject_desc": "1949年后成长起来的第一代民营企业家",
        "gender": "男",
        "target_words": 100000,
        "epilogue_content": "陈国伟说：\"我们就是那个石头，给后面的年轻人垫脚的。\"这句话，是这个时代最朴实的注脚。"
    }
