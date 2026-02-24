"""
内容质量检测工具
用于检测生成的传记内容是否存在AI占位符、模板化套话、内容重复等问题
"""
import re
import json
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class QualityIssue:
    """质量问题"""
    type: str
    description: str
    severity: str  # high, medium, low
    location: str = ""  # 问题出现的文本位置
    suggestion: str = ""  # 修改建议


@dataclass
class QualityReport:
    """质量检测报告"""
    file_path: str
    total_issues: int
    high_severity: int
    medium_severity: int
    low_severity: int
    issues: List[QualityIssue]
    score: float  # 0-100


class ContentQualityChecker:
    """内容质量检测器"""
    
    # AI占位符检测模式
    PLACEHOLDER_PATTERNS = [
        (r'鉴于.*尚待补充', 'AI占位符'),
        (r'此处为通用型.*模板', 'AI占位符'),
        (r'.*待补充.*', 'AI占位符'),
        (r'.*待完善.*', 'AI占位符'),
        (r'.*待填写.*', 'AI占位符'),
        (r'请补充具体细节', 'AI占位符'),
        (r'此处需要展开', 'AI占位符'),
        (r'后续补充.*', 'AI占位符'),
        (r'章节概要.*待', 'AI占位符'),
        (r'内容.*待.*完善', 'AI占位符'),
        (r'由于您尚未提供.*', 'AI占位符'),
        (r'我为您撰写了一段通用', 'AI占位符'),
        (r'适用于多数.*风格', 'AI占位符'),
        (r'注：.*为通用型', 'AI占位符'),
        (r'示例段落', 'AI占位符'),
        (r'模板内容', 'AI占位符'),
        (r'占位符', 'AI占位符'),
    ]
    
    # 模板化套话黑名单
    TEMPLATE_PHRASES = [
        '尘埃在光柱中飞舞',
        '尘埃在光柱中起舞',
        '苦涩中带着回甘',
        '凉茶早已凉透',
        '凉茶已经凉透',
        '凉茶已经凉',
        '凉茶早已凉',
        '时光的流逝',
        '命运的齿轮',
        '命运的齿轮悄然转动',
        '暴风雨前的宁静',
        '真相正伺机而动',
        '真相伺机而动',
        '桌上摊开的文件',
        '摊开的文件',
        '摊开着文件',
        '关系着民生冷暖',
        '肩上担子很重',
        '这是一个特殊的年代',
        '那是一个特殊的年代',
        '重要的决定',
        '历史的洪流',
        '时代的浪潮',
        '春蚕噬叶',
        '细雨敲窗',
        '沙沙声',
        '滴答，滴答',
        '咔嚓，咔嚓',
    ]
    
    # 空洞悬念表达
    EMPTY_SUSPENSE_PHRASES = [
        '但他不知道的是',
        '然而他不知道',
        '没人能想到',
        '谁也没想到',
        '没人想到',
        '风暴正在酝酿',
        '暗流涌动',
        '更大的挑战',
        '等待着他的',
        '未来充满了未知',
    ]
    
    # 重复意象检测
    REPETITIVE_IMAGERY = [
        (r'晨光|晨光熹微|晨光透过|清晨.*阳光|早晨.*阳光|晨曦|朝阳', '晨光/阳光'),
        (r'夕阳|夕阳西下|落日|黄昏|傍晚|晚霞', '夕阳/黄昏'),
        (r'凉茶|茶水|茶杯|喝茶|饮茶|端起.*杯|抿.*茶', '喝茶'),
        (r'挂钟|钟表|时钟|滴答|咔嚓|指针|表盘', '钟表'),
        (r'钢笔|笔尖|写字|书写|沙沙|落下.*笔', '写字/钢笔'),
        (r'窗外|看着窗外|望向窗外|窗外.*树|窗外.*景', '窗外'),
        (r'文件|桌上.*文件|摊开的.*纸|一叠.*纸', '文件/纸张'),
        (r'沉思|陷入沉思|默默.*想|静静.*想', '沉思'),
    ]
    
    # 空泛表述
    VAGUE_EXPRESSIONS = [
        '中国社会发展的重要时期',
        '那是一个特殊的年代',
        '这是一个特殊的年代',
        '风云变幻',
        '波澜壮阔',
        '跌宕起伏',
        '不平凡',
        '意义重大',
        '深刻影响',
        '历史性',
    ]
    
    def __init__(self):
        self.issues: List[QualityIssue] = []
    
    def check_file(self, file_path: Path) -> QualityReport:
        """检测单个文件"""
        logger.info(f"检测文件: {file_path}")
        
        content = file_path.read_text(encoding='utf-8')
        return self.check_content(content, str(file_path))
    
    def check_content(self, content: str, source: str = "") -> QualityReport:
        """检测内容质量"""
        self.issues = []
        
        # 1. 检测AI占位符
        self._check_placeholders(content)
        
        # 2. 检测模板化套话
        self._check_template_phrases(content)
        
        # 3. 检测空洞悬念
        self._check_empty_suspense(content)
        
        # 4. 检测内容实质性
        self._check_content_substance(content)
        
        # 5. 检测重复意象
        self._check_repetitive_imagery(content)
        
        # 6. 检测空泛表述
        self._check_vague_expressions(content)
        
        # 7. 检测内容重复
        self._check_content_repetition(content)
        
        # 8. 检测章节衔接问题
        self._check_chapter_transitions(content)
        
        # 计算分数
        score = self._calculate_score(len(self.issues))
        
        # 统计严重程度
        high = sum(1 for i in self.issues if i.severity == 'high')
        medium = sum(1 for i in self.issues if i.severity == 'medium')
        low = sum(1 for i in self.issues if i.severity == 'low')
        
        return QualityReport(
            file_path=source,
            total_issues=len(self.issues),
            high_severity=high,
            medium_severity=medium,
            low_severity=low,
            issues=self.issues,
            score=score
        )
    
    def _check_placeholders(self, content: str):
        """检测AI占位符"""
        for pattern, issue_type in self.PLACEHOLDER_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                unique_matches = list(set(matches))[:3]
                self.issues.append(QualityIssue(
                    type='AI占位符',
                    description=f"发现AI生成占位符: {', '.join(unique_matches)}",
                    severity='high',
                    suggestion='删除占位符，补充具体的采访素材细节'
                ))
                break  # 只报告一次
    
    def _check_template_phrases(self, content: str):
        """检测模板化套话"""
        found = [p for p in self.TEMPLATE_PHRASES if p in content]
        
        if len(found) >= 2:
            self.issues.append(QualityIssue(
                type='模板化套话',
                description=f"发现{len(found)}个套路化表达: {', '.join(found[:3])}",
                severity='medium',
                suggestion='删除套路化表达，使用具体的事实细节替代'
            ))
    
    def _check_empty_suspense(self, content: str):
        """检测空洞悬念"""
        # 检查章节结尾
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        if not paragraphs:
            return
        
        last_para = paragraphs[-1]
        last_500_chars = content[-500:]
        
        found = []
        for phrase in self.EMPTY_SUSPENSE_PHRASES:
            if phrase in last_para or phrase in last_500_chars:
                found.append(phrase)
        
        if found:
            self.issues.append(QualityIssue(
                type='空洞悬念',
                description=f"章节结尾使用套路化悬念: {', '.join(found[:2])}",
                severity='medium',
                suggestion='章节结尾应自然收束，不要强行制造虚假悬念'
            ))
    
    def _check_content_substance(self, content: str):
        """检测内容实质性"""
        # 1. 检查对话内容
        dialogue_pattern = r'["""「『].*?["""」』]'
        dialogues = re.findall(dialogue_pattern, content)
        dialogue_chars = sum(len(d) for d in dialogues)
        dialogue_ratio = dialogue_chars / len(content) if content else 0
        
        if dialogue_ratio < 0.02:  # 对话内容少于2%
            self.issues.append(QualityIssue(
                type='内容空洞',
                description='缺乏人物对话，内容以叙述为主，缺少生动细节',
                severity='medium',
                suggestion='增加人物对话，使用直接引语增强真实感'
            ))
        
        # 2. 检查具体数字和时间
        numbers = re.findall(r'\d+年|\d+岁|\d+元|\d+月|\d+日|\d+万元|\d+块钱', content)
        if len(numbers) < 3:
            self.issues.append(QualityIssue(
                type='缺乏具体信息',
                description='内容中缺乏具体的时间、数字等可核实信息',
                severity='high',
                suggestion='补充具体的时间、金额、数量等可核实信息'
            ))
        
        # 3. 检查具体地名和人名
        locations = re.findall(r'[\u4e00-\u9fa5]{2,4}(?:村|镇|县|市|省|区|街|路|厂)', content)
        if len(locations) < 2:
            self.issues.append(QualityIssue(
                type='缺乏地点信息',
                description='内容中缺乏具体的地点信息',
                severity='medium',
                suggestion='补充具体的地名、场所名称'
            ))
    
    def _check_repetitive_imagery(self, content: str):
        """检测重复意象"""
        for pattern, desc in self.REPETITIVE_IMAGERY:
            matches = re.findall(pattern, content)
            if len(matches) > 3:
                self.issues.append(QualityIssue(
                    type='意象重复',
                    description=f"'{desc}'意象重复出现{len(matches)}次",
                    severity='low',
                    suggestion='多样化描写，避免重复使用相同的意象'
                ))
    
    def _check_vague_expressions(self, content: str):
        """检测空泛表述"""
        found = [e for e in self.VAGUE_EXPRESSIONS if e in content]
        
        if found:
            self.issues.append(QualityIssue(
                type='空泛表述',
                description=f"使用空泛表述: {', '.join(found[:3])}",
                severity='medium',
                suggestion='使用具体的事实替代空泛的评价性语言'
            ))
    
    def _check_content_repetition(self, content: str):
        """检测内容重复"""
        paragraphs = [p.strip() for p in content.split('\n\n') if len(p.strip()) > 30]
        
        # 检查段落级重复
        for i, p1 in enumerate(paragraphs):
            for p2 in paragraphs[i+1:]:
                similarity = self._calculate_similarity(p1, p2)
                if similarity > 0.7:  # 70%相似度
                    self.issues.append(QualityIssue(
                        type='内容重复',
                        description=f"发现高度相似的段落（相似度{similarity:.0%}）",
                        severity='medium',
                        suggestion='删除重复内容，保持叙述简洁'
                    ))
                    return
        
        # 检查句子级重复
        sentences = re.split(r'[。！？]', content)
        seen = set()
        duplicates = []
        
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 15:
                continue
            
            # 简化句子指纹
            fingerprint = re.sub(r'[的了吗呢啊]', '', sent[:15])
            if fingerprint in seen:
                duplicates.append(sent[:20])
            seen.add(fingerprint)
        
        if len(duplicates) >= 3:
            self.issues.append(QualityIssue(
                type='句子重复',
                description=f"发现{len(duplicates)}处重复或高度相似的句子",
                severity='low',
                suggestion='删除重复表达，使用不同的措辞'
            ))
    
    def _check_chapter_transitions(self, content: str):
        """检测章节衔接问题"""
        # 检查是否有"冰火两重天"问题（结尾悬念与开头平淡的脱节）
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        if len(paragraphs) < 2:
            return
        
        last_para = paragraphs[-1]
        first_para = paragraphs[0]
        
        # 如果结尾有悬念词，但开头是平淡的日常描写
        suspense_words = ['悬念', '等待', '未知', '即将', '将要', '风暴', '暗流']
        has_suspense = any(w in last_para for w in suspense_words)
        
        daily_words = ['晨光', '阳光', '起床', '喝茶', '坐在', '看着', '窗外']
        starts_with_daily = any(w in first_para[:50] for w in daily_words)
        
        if has_suspense and starts_with_daily:
            self.issues.append(QualityIssue(
                type='章节衔接脱节',
                description='章节结尾设置悬念但下一章开头平淡，存在"冰火两重天"问题',
                severity='medium',
                suggestion='确保章节之间的情绪连贯，结尾的悬念要有呼应'
            ))
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        import difflib
        return difflib.SequenceMatcher(None, text1, text2).ratio()
    
    def _calculate_score(self, issue_count: int) -> float:
        """计算质量分数"""
        if issue_count == 0:
            return 100.0
        elif issue_count <= 2:
            return 85.0
        elif issue_count <= 5:
            return 70.0
        elif issue_count <= 10:
            return 50.0
        else:
            return 30.0


def check_directory(directory: Path, pattern: str = "*.md") -> List[QualityReport]:
    """检测目录下所有文件"""
    checker = ContentQualityChecker()
    reports = []
    
    for file_path in directory.glob(pattern):
        report = checker.check_file(file_path)
        reports.append(report)
    
    return reports


def print_report(report: QualityReport):
    """打印检测报告"""
    print(f"\n{'='*60}")
    print(f"文件: {report.file_path}")
    print(f"质量分数: {report.score}/100")
    print(f"问题总数: {report.total_issues} (高危: {report.high_severity}, 中危: {report.medium_severity}, 低危: {report.low_severity})")
    print(f"{'='*60}")
    
    if not report.issues:
        print("✅ 未发现问题")
        return
    
    for i, issue in enumerate(report.issues, 1):
        severity_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(issue.severity, '⚪')
        print(f"\n{i}. {severity_emoji} [{issue.type}] {issue.description}")
        if issue.suggestion:
            print(f"   💡 建议: {issue.suggestion}")


def save_report(report: QualityReport, output_path: Path):
    """保存检测报告为JSON"""
    data = {
        'file_path': report.file_path,
        'score': report.score,
        'total_issues': report.total_issues,
        'severity_counts': {
            'high': report.high_severity,
            'medium': report.medium_severity,
            'low': report.low_severity
        },
        'issues': [
            {
                'type': i.type,
                'description': i.description,
                'severity': i.severity,
                'suggestion': i.suggestion
            }
            for i in report.issues
        ]
    }
    
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python content_quality_checker.py <文件或目录路径>")
        print("示例: python content_quality_checker.py output/过河_陈国伟传/过河_陈国伟传.md")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    checker = ContentQualityChecker()
    
    if path.is_file():
        report = checker.check_file(path)
        print_report(report)
        
        # 保存报告
        report_path = path.parent / f"{path.stem}_quality_report.json"
        save_report(report, report_path)
        print(f"\n报告已保存到: {report_path}")
        
    elif path.is_dir():
        reports = check_directory(path)
        
        total_score = sum(r.score for r in reports) / len(reports) if reports else 0
        total_issues = sum(r.total_issues for r in reports)
        
        print(f"\n{'='*60}")
        print(f"目录检测结果汇总")
        print(f"{'='*60}")
        print(f"检测文件数: {len(reports)}")
        print(f"平均质量分: {total_score:.1f}/100")
        print(f"问题总数: {total_issues}")
        
        for report in reports:
            print_report(report)
    else:
        print(f"路径不存在: {path}")
