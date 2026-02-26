"""
信息推理引擎 - 基于人物画像补全缺失信息

功能：
1. 分析采访信息的完整性和缺口
2. 基于时间、地理、性别、学历等线索推断合理中间过程
3. 生成符合时代背景和社会规律的生活轨迹
4. 明确标注推断内容与原始事实的边界

原则：
- 合理性优先：推断必须符合时代背景和社会规律
- 可解释性：每个推断必须有明确的依据
- 可追溯性：推断内容必须标注为"合理推断"
- 不犯错：不编造具体事件，只推断类别和可能性
"""
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import json
from loguru import logger


class InformationGapType(Enum):
    """信息缺口类型"""
    TIME_GAP = "time_gap"           # 时间断档
    LOCATION_GAP = "location_gap"   # 地理空白
    CAREER_GAP = "career_gap"       # 职业断档
    RELATION_GAP = "relation_gap"   # 关系缺失
    EDUCATION_GAP = "education_gap" # 教育空白
    MOTIVATION_GAP = "motivation_gap"  # 动机不明


@dataclass
class InformationGap:
    """信息缺口定义"""
    gap_type: InformationGapType
    start_time: Optional[str]       # 开始时间（可选）
    end_time: Optional[str]         # 结束时间（可选）
    description: str                # 缺口描述
    severity: str                   # 严重程度: critical/high/medium/low
    context_hints: Dict[str, Any] = field(default_factory=dict)  # 上下文线索


@dataclass
class InferredSegment:
    """推断的人生阶段"""
    period: str                     # 时期描述
    start_year: Optional[int]
    end_year: Optional[int]
    life_stage: str                 # 人生阶段：童年/少年/青年/中年/老年
    typical_events: List[str]       # 典型事件类别
    social_context: str             # 社会背景
    confidence: float               # 置信度 0-1
    basis: List[str]                # 推断依据
    is_inferred: bool = True        # 标记为推断内容


@dataclass
class CharacterArchetype:
    """人物原型"""
    archetype_id: str
    name: str
    description: str
    typical_trajectory: List[str]   # 典型人生轨迹阶段
    era_indicators: Dict[str, Any]  # 时代特征指标
    common_transitions: List[Dict]  # 常见人生转折点


class EraContextDatabase:
    """时代背景数据库 - 提供各年代的社会背景信息"""

    # 中国近现代史关键时间节点
    ERA_MILESTONES = {
        "1949": {"event": "新中国成立", "impact": "社会秩序重建，土地改革"},
        "1958": {"event": "大跃进", "impact": "经济建设高潮，后续困难时期"},
        "1966": {"event": "文化大革命开始", "impact": "教育中断，上山下乡"},
        "1976": {"event": "文革结束", "impact": "拨乱反正，恢复高考"},
        "1978": {"event": "改革开放", "impact": "经济转型，个体户兴起"},
        "1984": {"event": "城市改革", "impact": "下海经商，人口流动"},
        "1992": {"event": "南巡讲话", "impact": "市场经济确立，创业潮"},
        "2001": {"event": "入世", "impact": "全球化，制造业发展"},
        "2008": {"event": "金融危机", "impact": "出口受挫，四万亿刺激"},
        "2015": {"event": "互联网+", "impact": "移动互联网普及，新业态"},
    }

    # 各年代典型教育轨迹
    EDUCATION_TRAJECTORIES = {
        "1940s_urban": ["私塾/小学", "中学", "大学/中专", "分配工作"],
        "1940s_rural": ["村小", "务农/参军", ...],
        "1950s_urban": ["小学", "中学", "大学/技校", "分配工作"],
        "1950s_rural": ["村小", "公社劳动", ...],
        "1960s_urban": ["小学", "中学", "文革中断", "上山下乡", "返城"],
        "1960s_rural": ["村小", "生产队", ...],
        "1970s_early": ["小学", "中学", "上山下乡", "返城/高考"],
        "1970s_late": ["小学", "中学", "高考", "大学", "分配/自主"],
        "1980s": ["小学", "中学", "大学/中专", "下海/外企/体制内"],
        "1990s": ["小学", "中学", "大学扩招", "互联网/外企/民企"],
        "2000s": ["小学", "中学", "大学", "研究生/留学/互联网"],
    }

    # 地域发展特征
    REGIONAL_CHARACTERISTICS = {
        "东北": {
            "1950s-1970s": "重工业基地，工人阶级为主",
            "1980s-1990s": "国企改革，下岗潮",
            "2000s+": "产业转型，人口外流"
        },
        "珠三角": {
            "1980s": "改革开放前沿，来料加工",
            "1990s": "制造业腾飞",
            "2000s+": "产业升级，科技创新"
        },
        "长三角": {
            "1980s": "乡镇企业兴起",
            "1990s": "浦东开发",
            "2000s+": "金融与制造中心"
        },
        "华北": {
            "全时期": "政治中心，体制内为主"
        },
        "西北": {
            "1950s-1970s": "三线建设",
            "1980s+": "资源开发，生态移民"
        },
    }

    # 职业变迁规律
    CAREER_TRANSITION_RULES = {
        "农民": {
            "1980s": ["乡镇企业工人", "个体户", "建筑工人"],
            "1990s": ["工厂工人", "小商贩", "运输司机"],
            "2000s": ["进城务工", "服务业", "返乡创业"]
        },
        "工人": {
            "1990s": ["下岗", "个体户", "私企工人"],
            "2000s": ["技术升级", "服务业转型", "内退"]
        },
        "知识分子": {
            "1966-1976": ["下放", "劳动改造", "靠边站"],
            "1978+": ["平反", "恢复工作", "学术复兴"]
        },
        "军人": {
            "退伍": ["转业干部", "国企保卫", "公安系统", "自主创业"]
        },
        "学生": {
            "1966-1976": ["红卫兵", "上山下乡", "工厂"],
            "1977+": ["高考", "大学", "研究生", "出国"]
        }
    }

    @classmethod
    def get_era_context(cls, year: int, region: Optional[str] = None) -> Dict[str, Any]:
        """获取特定年代的社会背景"""
        context = {
            "milestones": [],
            "education_context": "",
            "career_context": "",
            "social_atmosphere": ""
        }

        # 找出相关的时代节点
        for milestone_year, info in cls.ERA_MILESTONES.items():
            my = int(milestone_year)
            if abs(my - year) <= 5:
                context["milestones"].append({
                    "year": milestone_year,
                    **info
                })

        # 获取教育背景
        decade = (year // 10) * 10
        era_key = f"{decade}s"
        if era_key in cls.EDUCATION_TRAJECTORIES:
            context["education_context"] = cls.EDUCATION_TRAJECTORIES[era_key]

        # 地域背景
        if region and region in cls.REGIONAL_CHARACTERISTICS:
            for period, desc in cls.REGIONAL_CHARACTERISTICS[region].items():
                context["regional_context"] = desc

        return context

    @classmethod
    def infer_education_path(cls, birth_year: int, region: str,
                            family_background: Optional[str] = None) -> List[Dict]:
        """推断教育轨迹"""
        paths = []

        # 小学（通常6-12岁）
        primary_start = birth_year + 6
        primary_end = birth_year + 12

        # 根据年代判断教育中断可能性
        if 1966 <= primary_start <= 1976:
            # 文革期间上学
            paths.append({
                "stage": "小学",
                "period": f"{primary_start}-{min(primary_end, 1976)}",
                "note": "文革期间教育，内容受政治运动影响",
                "is_inferred": True
            })
            if primary_end > 1976:
                paths.append({
                    "stage": "小学/初中",
                    "period": f"1976-{primary_end}",
                    "note": "文革后恢复正规教育",
                    "is_inferred": True
                })
        else:
            paths.append({
                "stage": "小学",
                "period": f"{primary_start}-{primary_end}",
                "is_inferred": True
            })

        # 中学
        middle_start = primary_end
        middle_end = middle_start + 6

        if 1966 <= middle_start <= 1976:
            paths.append({
                "stage": "中学",
                "period": f"{middle_start}-{min(middle_end, 1976)}",
                "note": "文革期间，可能参与上山下乡",
                "possible_interruption": "上山下乡",
                "is_inferred": True
            })
        elif middle_end >= 1977 and middle_start <= 1977:
            # 刚好赶上高考恢复
            paths.append({
                "stage": "中学/高考",
                "period": f"{middle_start}-{middle_end}",
                "note": "1977年恢复高考，可能参加",
                "is_inferred": True
            })
        else:
            paths.append({
                "stage": "中学",
                "period": f"{middle_start}-{middle_end}",
                "is_inferred": True
            })

        # 高等教育（根据年代和家庭背景推断）
        higher_start = middle_end

        if higher_start < 1977:
            # 文革前或文革中 - 大学停止招生
            if family_background and "知识分子" in family_background:
                paths.append({
                    "stage": "高等教育",
                    "period": "中断",
                    "note": "文革期间大学停止招生，家庭受冲击",
                    "alternative": "可能参与上山下乡",
                    "is_inferred": True
                })
            else:
                paths.append({
                    "stage": "高等教育",
                    "period": "未经历",
                    "note": f"{higher_start}年尚未恢复高考",
                    "is_inferred": True
                })
        elif 1977 <= higher_start <= 1980:
            # 高考恢复初期，竞争激烈
            paths.append({
                "stage": "大学/中专",
                "period": f"{higher_start}起",
                "note": "恢复高考初期，录取率极低",
                "confidence": "中等",
                "is_inferred": True
            })
        elif 1980 <= higher_start <= 1999:
            # 精英教育时代
            paths.append({
                "stage": "大学",
                "period": f"{higher_start}起",
                "note": "精英教育时代，大学生含金量高",
                "is_inferred": True
            })
        else:
            # 扩招后
            paths.append({
                "stage": "大学",
                "period": f"{higher_start}起",
                "note": "大学扩招时期",
                "is_inferred": True
            })

        return paths

    @classmethod
    def infer_career_transitions(cls, start_occupation: str,
                                  start_year: int,
                                  region: str) -> List[Dict]:
        """推断职业变迁轨迹"""
        transitions = []

        current_occ = start_occupation
        current_year = start_year

        # 检查是否受大事件影响
        if current_occ == "工人" and 1990 <= current_year <= 2000:
            transitions.append({
                "period": f"{current_year}-1998",
                "occupation": current_occ,
                "note": "国企工人，可能经历下岗潮",
                "possible_change": "1998年前后国企改制",
                "is_inferred": True
            })
            transitions.append({
                "period": "1998-2005",
                "occupation": "待推断",
                "note": "可能的再就业：个体户、私企、服务业",
                "alternatives": ["个体户", "私企工人", "保安/物业", "自主创业"],
                "is_inferred": True
            })

        elif current_occ == "农民" and 1980 <= current_year <= 1995:
            transitions.append({
                "period": f"{current_year}-1990s",
                "occupation": "务农",
                "note": "农村改革，家庭联产承包",
                "is_inferred": True
            })
            if region in ["珠三角", "长三角", "福建"]:
                transitions.append({
                    "period": "1990s-2000s",
                    "occupation": "乡镇企业工人/外出务工",
                    "note": f"{region}地区，较早出现外出务工潮",
                    "is_inferred": True
                })

        elif current_occ == "学生" and 1966 <= current_year <= 1976:
            transitions.append({
                "period": f"{current_year}-1970s",
                "occupation": "红卫兵/上山下乡",
                "note": "文革期间学生参与政治运动，后上山下乡",
                "is_inferred": True
            })
            transitions.append({
                "period": "1970s-1980s",
                "occupation": "知青/返城",
                "note": "后期陆续返城，或在当地扎根",
                "is_inferred": True
            })

        return transitions


class CharacterInferenceEngine:
    """人物信息推理引擎"""

    def __init__(self):
        self.era_db = EraContextDatabase()
        self.gaps: List[InformationGap] = []
        self.inferred_segments: List[InferredSegment] = []

    def analyze_gaps(self, facts: Any, timeline: Any) -> List[InformationGap]:
        """分析信息缺口"""
        self.gaps = []

        # 获取关键时间点
        events = timeline.events if hasattr(timeline, 'events') else []
        birth_year = None
        death_year = None

        for event in events:
            event_time = event.time if hasattr(event, 'time') else event.get('time', '')
            if '出生' in str(event):
                try:
                    birth_year = int(event_time[:4])
                except:
                    pass
            if '去世' in str(event) or '逝世' in str(event):
                try:
                    death_year = int(event_time[:4])
                except:
                    pass

        if not birth_year:
            # 无法分析
            return self.gaps

        current_year = death_year or datetime.now().year

        # 检查人生各阶段
        life_stages = [
            ("童年", birth_year, birth_year + 12),
            ("少年", birth_year + 12, birth_year + 18),
            ("青年", birth_year + 18, birth_year + 35),
            ("中年", birth_year + 35, birth_year + 55),
            ("老年", birth_year + 55, current_year)
        ]

        for stage_name, start, end in life_stages:
            # 检查该阶段是否有足够的事件
            stage_events = [
                e for e in events
                if start <= self._extract_year(e) <= end
            ]

            if len(stage_events) < 1:
                self.gaps.append(InformationGap(
                    gap_type=InformationGapType.TIME_GAP,
                    start_time=str(start),
                    end_time=str(end),
                    description=f"{stage_name}时期信息空白",
                    severity="high" if stage_name in ["青年", "中年"] else "medium",
                    context_hints={"stage": stage_name, "era": self._get_era_decade(start)}
                ))
            elif len(stage_events) < 2 and stage_name in ["青年", "中年"]:
                self.gaps.append(InformationGap(
                    gap_type=InformationGapType.MOTIVATION_GAP,
                    start_time=str(start),
                    end_time=str(end),
                    description=f"{stage_name}时期关键转折点缺失",
                    severity="medium",
                    context_hints={"stage": stage_name, "has_events": len(stage_events)}
                ))

        return self.gaps

    def _extract_year(self, event) -> int:
        """从事件中提取年份"""
        try:
            time_str = event.time if hasattr(event, 'time') else event.get('time', '0')
            return int(time_str[:4])
        except:
            return 0

    def _get_era_decade(self, year: int) -> str:
        """获取年代"""
        return f"{(year // 10) * 10}s"

    def infer_life_trajectory(self, facts: Any, timeline: Any,
                              region: Optional[str] = None) -> List[InferredSegment]:
        """推断完整人生轨迹"""
        self.inferred_segments = []

        # 提取基础信息
        profile = facts.profile if hasattr(facts, 'profile') else {}
        birth_year = None
        birth_place = region or "未知"
        family_bg = None

        if profile:
            if hasattr(profile, 'birth_date') and profile.birth_date:
                try:
                    birth_year = int(profile.birth_date[:4])
                except:
                    pass
            if hasattr(profile, 'birth_place') and profile.birth_place:
                birth_place = profile.birth_place
            if hasattr(profile, 'family_background') and profile.family_background:
                family_bg = profile.family_background

        if not birth_year:
            logger.warning("无法推断：缺少出生年份")
            return self.inferred_segments

        # 推断教育轨迹
        education_path = self.era_db.infer_education_path(
            birth_year, birth_place, family_bg
        )

        for edu in education_path:
            self.inferred_segments.append(InferredSegment(
                period=edu["period"],
                start_year=self._parse_year(edu["period"].split('-')[0]) if '-' in edu["period"] else None,
                end_year=self._parse_year(edu["period"].split('-')[1]) if '-' in edu["period"] else None,
                life_stage="教育阶段",
                typical_events=[edu["stage"]],
                social_context=edu.get("note", ""),
                confidence=0.7 if "中等" in edu.get("confidence", "") else 0.8,
                basis=["出生年份", "时代背景", "地域特征"],
                is_inferred=True
            ))

        # 推断职业轨迹
        events = timeline.events if hasattr(timeline, 'events') else []
        occupations = self._extract_occupations(events)

        if occupations:
            for occ, start_yr in occupations:
                transitions = self.era_db.infer_career_transitions(
                    occ, start_yr, birth_place
                )
                for trans in transitions:
                    self.inferred_segments.append(InferredSegment(
                        period=trans["period"],
                        life_stage="职业阶段",
                        typical_events=[trans.get("occupation", ""), trans.get("possible_change", "")],
                        social_context=trans.get("note", ""),
                        confidence=0.6,
                        basis=["初始职业", "时代背景", f"{birth_place}地区特征"],
                        is_inferred=True
                    ))

        return self.inferred_segments

    def _parse_year(self, year_str: str) -> Optional[int]:
        """解析年份字符串"""
        try:
            return int(year_str.strip())
        except:
            return None

    def _extract_occupations(self, events: List[Any]) -> List[Tuple[str, int]]:
        """从事件中提取职业信息"""
        occupations = []
        for event in events:
            desc = str(event)
            if any(kw in desc for kw in ["工作", "上班", "厂", "公司", "单位"]):
                year = self._extract_year(event)
                # 简单提取职业名称
                for occ in ["工人", "农民", "教师", "医生", "军人", "干部", "个体户"]:
                    if occ in desc:
                        occupations.append((occ, year))
                        break
        return occupations

    def generate_completion_report(self) -> Dict[str, Any]:
        """生成信息补全报告"""
        return {
            "analysis_summary": {
                "total_gaps": len(self.gaps),
                "critical_gaps": len([g for g in self.gaps if g.severity == "critical"]),
                "high_gaps": len([g for g in self.gaps if g.severity == "high"])
            },
            "gaps": [
                {
                    "type": g.gap_type.value,
                    "period": f"{g.start_time or '?'}-{g.end_time or '?'}" if g.start_time or g.end_time else "未知",
                    "description": g.description,
                    "severity": g.severity
                }
                for g in self.gaps
            ],
            "inferred_segments": [
                {
                    "period": s.period,
                    "life_stage": s.life_stage,
                    "typical_events": s.typical_events,
                    "social_context": s.social_context,
                    "confidence": s.confidence,
                    "basis": s.basis,
                    "is_inferred": s.is_inferred
                }
                for s in self.inferred_segments
            ],
            "warnings": [
                "所有推断内容均基于时代背景和社会规律，仅供参考",
                "具体个人经历可能有特殊性，需进一步核实",
                "涉及敏感历史时期的推断需谨慎使用"
            ]
        }

    def enrich_character_profile(self, facts: Any) -> Dict[str, Any]:
        """丰富人物画像信息"""
        profile = facts.profile if hasattr(facts, 'profile') else {}
        if not profile:
            return {}

        enrichments = {}

        # 基于已有信息推断
        if hasattr(profile, 'birth_date') and profile.birth_date:
            try:
                birth_year = int(profile.birth_date[:4])
                current_year = datetime.now().year
                age = current_year - birth_year

                # 推断当前人生阶段
                if age < 30:
                    enrichments["life_stage"] = "青年期"
                    enrichments["typical_concerns"] = ["职业发展", "婚恋", "独立生活"]
                elif age < 45:
                    enrichments["life_stage"] = "中青年期"
                    enrichments["typical_concerns"] = ["事业上升", "家庭责任", "子女教育"]
                elif age < 60:
                    enrichments["life_stage"] = "中年期"
                    enrichments["typical_concerns"] = ["职业稳定", "赡养父母", "子女成家"]
                else:
                    enrichments["life_stage"] = "老年期"
                    enrichments["typical_concerns"] = ["退休生活", "健康管理", "传承经验"]

                # 时代标签
                if 1949 <= birth_year <= 1959:
                    enrichments["generation"] = "建国一代"
                    enrichments["era_features"] = ["经历建国初期", "大跃进", "困难时期"]
                elif 1960 <= birth_year <= 1969:
                    enrichments["generation"] = "文革一代"
                    enrichments["era_features"] = ["文革中成长", "上山下乡", "恢复高考"]
                elif 1970 <= birth_year <= 1979:
                    enrichments["generation"] = "改革一代"
                    enrichments["era_features"] = ["改革开放中成长", "市场经济", "下海潮"]
                elif 1980 <= birth_year <= 1989:
                    enrichments["generation"] = "80后"
                    enrichments["era_features"] = ["市场经济", "互联网", "全球化"]
                elif 1990 <= birth_year <= 1999:
                    enrichments["generation"] = "90后"
                    enrichments["era_features"] = ["互联网时代", "移动互联网", "创业潮"]

            except:
                pass

        # 地域特征推断
        if hasattr(profile, 'birth_place') and profile.birth_place:
            place = profile.birth_place
            for region in EraContextDatabase.REGIONAL_CHARACTERISTICS.keys():
                if region in place:
                    enrichments["region_type"] = region
                    break

        return {
            "original_profile": profile,
            "inferred_enrichments": enrichments,
            "is_inferred": True,
            "note": "推断信息基于群体特征，个体差异需进一步核实"
        }


# 便捷函数
def analyze_information_completeness(facts: Any, timeline: Any) -> Dict[str, Any]:
    """分析信息完整性"""
    engine = CharacterInferenceEngine()
    gaps = engine.analyze_gaps(facts, timeline)
    trajectory = engine.infer_life_trajectory(facts, timeline)
    report = engine.generate_completion_report()
    profile_enrichment = engine.enrich_character_profile(facts)

    return {
        **report,
        "profile_enrichment": profile_enrichment,
        "completeness_score": max(0, 1 - len(gaps) * 0.1)  # 简单的完整性评分
    }
