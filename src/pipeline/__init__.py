"""核心流水线"""
import asyncio
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..storage.project import Project, ProjectStorage
from ..storage.git import GitManager
from ..llm.client import LLMClient, LLMConfig
from ..llm import prompts


class BiographyPipeline:
    """传记生成流水线"""
    
    def __init__(self, project: Project, storage: ProjectStorage):
        self.project = project
        self.storage = storage
        self.llm = LLMClient()
        
        # 加载大纲和素材
        self.outline = None
        self.characters = None
        self.material = None
        
        # Git 管理
        self.git = GitManager(storage.base_dir)
        
        # 配置
        self.config = self._load_config()
    
    async def run(self):
        """运行完整流程"""
        try:
            # 1. 加载素材
            await self._load_material()
            
            # 2. 阶段1: 生成大纲 + 人物小传
            if self.project.current_phase == "init":
                await self._generate_outline()
                self.project.current_phase = "outline"
                self.storage.save_project(self.project)
            
            # 3. 阶段2: 生成逐章要点
            if self.project.current_phase == "outline":
                await self._generate_chapter_notes()
                self.project.current_phase = "chapters"
                self.storage.save_project(self.project)
            
            # 4. 阶段3: 逐章生成
            if self.project.current_phase == "chapters":
                await self._generate_chapters()
            
            # 5. 全文终审（只有在成功生成章节后才执行）
            if len(self.project.completed_chapters) > 0:
                print(f"\n📚 阶段4: 全文终审...")
                await self._final_whole_book_review()
            else:
                print(f"\n⚠️ 警告：没有生成任何章节，跳过全文终审")
            
            # 6. 完成
            self.project.current_phase = "final"
            self.storage.save_project(self.project)
            
            print(f"\n🎉 传记生成完成！")
            print(f"   总章节: {len(self.project.completed_chapters)}")
            
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            self.storage.save_project(self.project)
            raise
    
    async def _load_material(self):
        """加载采访素材"""
        material_path = Path(self.project.material_path)
        
        if material_path.exists():
            with open(material_path, 'r', encoding='utf-8') as f:
                self.material = f.read()
            print(f"✅ 加载素材: {len(self.material)} 字")
        
        # 从项目目录加载已生成的大纲
        outline_file = self.storage.base_dir / "outline.json"
        if outline_file.exists():
            with open(outline_file, 'r', encoding='utf-8') as f:
                self.outline = json.load(f)
            print(f"✅ 加载已有大纲: {self.outline.get('total_chapters', 0)} 章")
        
        # 加载人物小传
        bio_file = self.storage.base_dir / "character_bio.json"
        if bio_file.exists():
            with open(bio_file, 'r', encoding='utf-8') as f:
                self.characters = json.load(f)
            print(f"✅ 加载人物小传")
    
    async def _generate_outline(self):
        """生成大纲 + 人物小传"""
        print("\n📝 阶段1: 生成大纲和人物小传...")
        
        if self.outline:
            print("   使用已有大纲")
            return
        
        # 生成大纲
        # 默认使用"普通劳动者/平民"风格
        style_prompt = prompts.get_style_prompt("ordinary")
        
        prompt = prompts.OUTLINE_PROMPT.format(
            subject_info="陈国伟，1965年生，广东佛山人",
            material=self.material[:50000] if self.material else "",
            style_prompt=style_prompt,
            total_chapters=25,
            words_per_chapter=4000,
            start_year=1965,
            end_year=2025
        )
        
        thinking, response = await self.llm.complete_with_thinking([
            {"role": "user", "content": prompt}
        ])
        
        # 解析 JSON（增强版，更容错）
        import re
        try:
            # 方法1: 提取markdown代码块中的JSON
            code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
            if code_block_match:
                json_str = code_block_match.group(1)
            else:
                # 方法2: 提取纯JSON对象
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    json_str = json_match.group()
                else:
                    raise ValueError("未找到有效的JSON")
            
            # 尝试解析
            try:
                self.outline = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"   ⚠️ 初次解析失败: {e}")
                print(f"   尝试修复JSON...")
                
                # 修复常见的JSON错误
                fixed_json = json_str
                
                # 移除尾部逗号
                fixed_json = re.sub(r',\s*([}\]])', r'\1', fixed_json)
                
                # 修复缺少引号的键
                fixed_json = re.sub(r'(\w+)(?=\s*:)', r'"\1"', fixed_json)
                
                # 修复单引号改为双引号
                fixed_json = fixed_json.replace("'", '"')
                
                self.outline = json.loads(fixed_json)
                print(f"   ✅ JSON修复成功")
                
        except Exception as e:
            print(f"   ⚠️ 大纲JSON解析失败: {e}")
            print(f"   📝 响应片段: {response[:500]}...")
            
            # 使用已有的旧大纲
            old_outline = Path(__file__).parent.parent.parent / ".cache" / "1e2bfb51acfc8635_outline.json"
            if old_outline.exists():
                with open(old_outline, 'r', encoding='utf-8') as f:
                    self.outline = json.load(f)
                print(f"   ✅ 使用缓存大纲")
            else:
                print(f"   ❌ 大纲生成失败且没有缓存大纲")
                raise Exception(f"大纲生成失败: {e}")
        
        # 验证大纲有效性
        if not self.outline.get("chapters") or len(self.outline.get("chapters", [])) == 0:
            print(f"   ❌ 大纲无效：章节列表为空")
            raise Exception("大纲生成失败：章节列表为空")
        
        print(f"   ✅ 大纲生成完成: {self.outline.get('total_chapters', 25)} 章")
        
        # 保存大纲
        outline_file = self.storage.base_dir / "outline.json"
        with open(outline_file, 'w', encoding='utf-8') as f:
            json.dump(self.outline, f, ensure_ascii=False, indent=2)
    
    async def _generate_chapter_notes(self):
        """生成逐章要点"""
        print("\n📋 阶段2: 生成逐章要点...")
        print("   跳过（使用大纲中的信息）")
    
    async def _generate_chapters(self):
        """逐章生成"""
        print("\n✍️ 阶段3: 逐章生成...")
        
        chapters = self.outline.get("chapters", []) if self.outline else []
        
        if not chapters:
            # 使用旧大纲
            old_outline = Path(__file__).parent.parent.parent / ".cache" / "1e2bfb51acfc8635_outline.json"
            if old_outline.exists():
                with open(old_outline, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
                    chapters = old_data.get("chapters", [])
        
        start_chapter = self.project.current_chapter
        
        for i, chapter_outline in enumerate(chapters[start_chapter:], start=start_chapter + 1):
            print(f"\n📖 第 {i}/{len(chapters)} 章: {chapter_outline.get('title', '')}")
            
            # 生成章节
            content = await self._generate_chapter(i, chapter_outline)
            
            # 审核
            score = await self._review_chapter(content, chapter_outline, i)
            
            # 重生成循环（必须通过才能继续）
            retry_count = 0
            max_retries = 10  # 最多重试10次
            while not score.get("passed", False) and retry_count < max_retries:
                overall = score.get("overall_score", 0)
                print(f"   ⚠️ 审核未通过（分数: {overall}），重生成 ({retry_count + 1}/{max_retries})")
                issues_preview = score.get('issues', [])[:2]
                print(f"   问题: {', '.join(issues_preview)}...")
                
                content = await self._regenerate_chapter(i, chapter_outline, score.get("issues", []))
                score = await self._review_chapter(content, chapter_outline, i)
                retry_count += 1
            
            # 只有通过审核才保存，否则停止流程
            if not score.get("passed", False):
                print(f"\n❌ 第 {i} 章审核失败，已重试 {max_retries} 次")
                print(f"   最后分数: {score.get('overall_score', 0)}")
                print(f"   问题: {score.get('issues', [])}")
                print(f"\n⚠️ 系统停止，请人工检查")
                raise Exception(f"第{i}章审核失败，重试{max_retries}次仍未通过")
            
            # 保存章节
            self.storage.save_chapter(i, content)
            
            # 生成并保存结构化摘要
            print(f"      生成章节摘要...")
            chapter_summary = await self._generate_chapter_summary(content, chapter_outline)
            self.storage.save_chapter_summary(i, chapter_summary)
            
            # 保存审核记录
            self.storage.save_review(i, score)
            
            self.project.completed_chapters.append(i)
            self.project.current_chapter = i
            self.storage.save_project(self.project)
            
            # Git 提交
            try:
                self.git.commit(f"第{i}章: {chapter_outline.get('title', '')}")
            except:
                pass
            
            print(f"   ✅ 完成")
    
    async def _generate_chapter_summary(self, chapter_content: str, chapter_outline: dict) -> str:
        """使用大模型生成章节结构化摘要"""
        prompt = f"""请对以下章节内容进行总结，提取关键信息，生成结构化摘要（不超过500字）。

【章节信息】
标题: {chapter_outline.get('title', '未知')}
时间跨度: {chapter_outline.get('time_period', '未知')}

【章节内容】
{chapter_content[:8000]}

【摘要要求】
请按以下格式输出：
1. **核心事件**: 本章描写的1-3个主要事件（用一句话概括每个事件）
2. **关键人物**: 出场的主要人物及其与传主的关系
3. **时间节点**: 具体年份或年龄段
4. **地点**: 主要场景地点
5. **情节进展**: 传主本章的成长/转变
6. **伏笔/悬念**: 为后续章节埋下的线索（如有）

注意：
- 摘要要客观、准确，便于后续章节参考避免重复
- 明确指出本章"已写"的核心事件，防止后续章节重复描写
- 不超过500字
"""
        try:
            response = await self.llm.complete([
                {"role": "user", "content": prompt}
            ], temperature=0.3, max_tokens=1000)
            return response.strip()
        except Exception as e:
            print(f"   ⚠️ 生成摘要失败: {e}, 使用截取摘要")
            return chapter_content[:500] + "..."

    async def _generate_chapter(self, order: int, outline: dict) -> str:
        """生成单章"""
        # 获取前文结构化摘要（使用模型生成的摘要）
        previous_summary = ""
        if self.project.completed_chapters:
            for ch_order in self.project.completed_chapters[-3:]:
                # 尝试加载模型生成的摘要
                summary = self.storage.load_chapter_summary(ch_order)
                if summary:
                    previous_summary += f"===== 第{ch_order}章摘要 =====\n{summary}\n\n"
        
        # 添加时间线信息
        timeline_info = self._build_timeline()
        
        # 添加人物关系信息
        character_info = self._build_character_relationships()
        
        # 组装增强版提示词
        enhanced_prompt = f"""请根据以下信息，生成传记的第 {order} 章。

【章节大纲 - 最高优先级】
{json.dumps(outline, ensure_ascii=False, indent=2)}

⚠️ **强制要求**：
- 时间_period、地点 location、关键事件 key_events 必须 **完全一致** 于上述大纲
- 如果大纲时间_period 是 1989-1991年，章节内容必须发生在 1989-1991年，不得跳到其他年份
- 如果大纲地点是"深圳沙头角"，章节内容必须发生在深圳沙头角，不得发生在其他地点

🚫 **绝对禁止 - 重复描写禁令**：
1. **同一事件只能写一次**：如果前文摘要中已提到某个事件（如"偷甘蔗被抓"），本章**绝对禁止**再写该事件，即使时间线重叠也不行
2. **禁止同一事件换时间重写**：不能把1976年的事件改到1973年重新写一遍
3. **禁止同一事件换视角重写**：不能在本章重写前文已写的事件，即使细节不同
4. **如有疑问，宁可省略，不要重复**：如果不确定某个事件是否写过，**选择不写**，或简要提及"此事已在X章详述"
5. **时间线必须严格分开**：本章的时间段内发生的事件，不得与之前章节的时间段重叠写同一事件

【人物小传】
{self.characters.get("陈国伟", "") if self.characters else ""}

【采访素材 - 仅作为参考，不得偏离大纲】
{self.material[:20000] if self.material else ""}

【已生成章节摘要 - 重点查看避免重复】
{previous_summary}
⚠️ **重要**：仔细阅读上文摘要，确保本章不写已在前文写过的事件！

【时间线参考】
{timeline_info}

【人物关系】
{character_info}

---

**【写作前的自我检查清单】**

作为专业传记作家，在开始写作前，请**主动思考**以下问题：

### 一、真实性问题（最重要！）

**问自己：这段描写在真实生活中可能吗？**

1. **年龄与行为匹配吗？**
   - 如果传主在本章时间段内的年龄是 X 岁，他对事件的反应真实吗？
   - **参考认知发展规律**：
     * 0-2岁：只会哭、笑、吃、睡，无复杂认知
     * 3-4岁：刚学会说话，词汇有限，遇到问题只会本能反应（哭、害怕），**不可能**理解"成分"、"阶级"等概念
     * 5-6岁：开始有自我意识，但仍以本能反应为主
     * 7-10岁：可以有简单社会认知，但仍以儿童视角理解世界
     * 11岁以上：才可能真正理解社会复杂性
   - **常见错误示例**：
     * ❌ 3岁孩子问"什么是地主崽子" → 太超前
     * ✅ 3岁孩子被排斥时只会哭，说不出原因
     * ❌ 5岁孩子理解"成分不好"的含义 → 太超前
     * ✅ 5岁孩子只知道"别人不跟我玩"，不理解原因

2. **时代背景准确吗？**
   - 这个年代的人穿什么？说什么？怎么想？
   - 有没有把现代人的思维方式、语言习惯强加给那个时代？
   - 有没有出现不该出现的物品？（如1980年代出现智能手机、网络用语）

3. **地理环境正确吗？**
   - 南方水乡应该是什么样子？（气候、植被、建筑、饮食）
   - 有没有把北方特征写在南方，或反之？

4. **社会制度细节对吗？**
   - 集体分配时代：粮食怎么分？工分怎么算？出工怎么记？
   - 这些细节是否符合当时的真实情况？

5. **心理反应真实吗？**
   - 一个被歧视的孩子，真实的心理反应是什么？
   - 一个刚失去亲人的人，真实的反应是什么？
   - 有没有过度戏剧化或过度理性化？

### 二、逻辑一致性问题

**问自己：这些内容在逻辑上自洽吗？**

1. **时间线自洽吗？**
   - 大纲要求的时间段是 {outline.get('time_period', '未知')}，我写的内容真的发生在这个时间段吗？
   - **严禁**：大纲是1974-1976年，却写1971年的事
   - 事件的时间顺序合理吗？会不会出现"还没出生就已经记事"的矛盾？

2. **人物设定完整吗？**
   - 素材中明确提到的家庭成员，我都写进去了吗？
   - 示例：如果素材说"排行老三，上面两个姐姐"，那吃饭场景应该有：父母+2个姐姐+传主 = 5个人
   - 如果只写了"三个碗"，就严重违背事实

3. **物理环境连贯吗？**
   - 前面说下雨，后面说晒谷，矛盾吗？
   - 早上说米缸空了，晚上突然有大餐，合理吗？

### 三、素材一致性问题

**问自己：内容和素材吻合吗？**

1. **重要事件遗漏了吗？**
   - 素材明确提到的关键事件，本章是否遗漏？

2. **事实被篡改了吗？**
   - 素材说"队长抓"，为什么写成"看田老头抓"？
   - 这些改动是否改变了事件本质？

3. **虚构合理吗？**
   - 添加了素材中没有的内容，这些虚构符合逻辑吗？
   - 有没有过度虚构，偏离素材核心？

### 四、跨章节重复检查（最重要！）

**问自己：本章内容是否与前文重复？**

1. **事件重复检查**：
   - 本章写的核心事件，是否已在之前章节写过？
   - 查看前文摘要，确认没有重复描写同一事件
   - **常见错误**：偷甘蔗、初恋、创业等关键事件被写两遍

2. **时间重叠检查**：
   - 本章的时间段是否与前文写同一事件的时间重叠？
   - 如果重叠，是否是在写不同的事（而非同一事件）？

3. **情节重复检查**：
   - 本章的情节推进是否与前文雷同？
   - 是否只是换了时间地点，但写的事本质上一样？

4. **如果发现可能重复**：
   - **立即停止**，查看前文摘要确认
   - **宁可不写，不要重复**
   - 如果必须提及已写事件，用一句话带过"此事详见第X章"

### 四、文学性问题

**问自己：文字质量达标吗？**

1. **有陈词滥调吗？**
   - 避免："时光荏苒"、"岁月如梭"、"光阴似箭"、"尘埃在光柱中飞舞"
   - 用具体细节替代空洞表达

2. **细节描写生动吗？**
   - ❌ "他很饿" → 只有形容词
   - ✅ "他盯着锅台，喉咙里发出咕噜声" → 具体细节

3. **对话真实吗？**
   - 人物说话方式符合其身份、年龄、教育背景吗？
   - 农村老实父亲，会用知识分子式的语言吗？

---

【输出要求】
1. 全文约 4000 字
2. 采用文学性叙述，非流水账
3. 包含细节描写（场景、对话、心理活动）
4. **时间线必须严格遵循大纲**
5. **年龄认知必须符合儿童发展规律**
6. **人物设定必须与素材一致**
7. **时代背景必须准确**
8. **地理环境必须正确**

【输出格式】
直接输出章节内容，不需要 JSON 包装。标题使用一级标题格式：# 章节标题
"""
        
        thinking, content = await self.llm.complete_with_thinking([
            {"role": "user", "content": enhanced_prompt}
        ], max_tokens=8000)
        
        return content
    
    async def _regenerate_chapter(self, order: int, outline: dict, issues: list) -> str:
        """重生成章节"""
        prompt = f"""之前生成的第{order}章存在以下问题：
{chr(10).join(f"- {issue}" for issue in issues)}

请根据以下大纲重新生成：
{json.dumps(outline, ensure_ascii=False, indent=2)}

要求：解决上述问题，保持文学性，约4000字。"""

        thinking, content = await self.llm.complete_with_thinking([
            {"role": "user", "content": prompt}
        ], max_tokens=8000)
        
        return content
    
    async def _final_whole_book_review(self):
        """全文终审：整书对照采访稿进行审核"""
        print("\n   开始全文终审（对照采访稿检查全书）...")
        
        # 加载所有章节内容
        all_chapters_content = []
        for ch_order in self.project.completed_chapters:
            content = self.storage.load_chapter(ch_order)
            if content:
                all_chapters_content.append(f"=== 第{ch_order}章 ===\n{content[:3000]}...")
        
        full_book = "\n\n".join(all_chapters_content)
        
        # 终审提示词
        prompt = f"""你是一位极其严格的传记总编。请对照原始采访素材，对整本传记进行全面审核，找出所有问题。

【原始采访素材】
{self.material}

【生成的传记全文】
{full_book[:15000]}...
（全书共{len(self.project.completed_chapters)}章，以上为各章节选）

【终审检查清单】

### 1. 跨章节事件重复（最严重）
- 同一事件是否在多章重复描写？
- 是否把同一事件改时间/改视角写了两遍？
- 发现重复：指出哪几章重复，建议合并或删除

### 2. 时间线逻辑错误
- 事件顺序是否符合时间先后？
- 是否有"还没发生就已经写了后续"的悖论？
- 年龄与事件是否匹配？

### 3. 与素材不符
- 传记内容是否与采访素材矛盾？
- 是否篡改了关键事实（如把人名、地点、时间改错）？
- 是否添加了素材中没有的重大虚构？

### 4. 人物设定不一致
- 人物性格是否前后矛盾？
- 人物关系是否前后不一致？

### 5. 文学性问题
- 是否有章节明显质量低于其他章节？
- 是否有明显的AI痕迹或套话？
- 整体风格是否统一？

【输出格式】
```
===终审结果===
passed: true/false
总体评价: 简要评价全书质量

===严重问题（如有则必须修订）===
1. 【跨章重复】第X章和第Y章都写了"偷甘蔗"事件，建议删除Y章相关内容
2. 【时间错误】第X章写1976年上小学，但第Y章写1974年已上初中，矛盾
...

===建议优化（可选）===
1. 第X章可以增加更多细节描写
2. 第Y章结尾可以更自然
...
```

请严格审查，宁严勿宽。如有严重问题，必须指出并建议如何修改。"""
        
        try:
            response = await self.llm.complete([
                {"role": "user", "content": prompt}
            ], temperature=0.3, max_tokens=8000, timeout=300)
            
            # 保存终审报告
            review_file = self.storage.base_dir / "final" / "whole_book_review.txt"
            review_file.parent.mkdir(exist_ok=True)
            with open(review_file, 'w', encoding='utf-8') as f:
                f.write(response)
            
            print(f"   ✅ 终审完成，报告已保存")
            
            # 简单解析结果
            if "passed: false" in response.lower() or "严重问题" in response:
                print(f"   ⚠️  终审发现严重问题，请查看报告: {review_file}")
                # 这里可以添加自动修订逻辑
            else:
                print(f"   ✅ 终审通过")
                
        except Exception as e:
            print(f"   ⚠️  终审过程出错: {e}")
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}
    
    def _get_previous_count(self, chapter_order: int, review_config: dict) -> int:
        """根据章节位置动态确定前文数量"""
        strategy = review_config.get('context_strategy', {})
        
        for key, config in strategy.items():
            range_config = config.get('range', [1, 999])
            if range_config[0] <= chapter_order <= range_config[1]:
                return config.get('previous_count', 3)
        
        return 3
    
    async def _build_previous_context(self, chapter_order: int, count: int) -> str:
        """组装前文摘要"""
        if not self.project.completed_chapters:
            return "无"
        
        recent_chapters = self.project.completed_chapters[-count:]
        context_parts = []
        
        for ch_order in recent_chapters:
            content = self.storage.load_chapter(ch_order)
            if content:
                # 智能提取摘要（前 500 字）
                context_parts.append(f"第{ch_order}章摘要:\n{content[:500]}...\n")
        
        return "\n".join(context_parts) if context_parts else "无"
    
    def _build_timeline(self) -> str:
        """组装时间线"""
        if not self.outline:
            return "无"
        
        timeline_parts = []
        chapters = self.outline.get("chapters", [])
        for ch in chapters[:10]:  # 前10章的时间线
            time_period = ch.get("time_period", "")
            title = ch.get("title", "")
            if time_period:
                timeline_parts.append(f"- {time_period}: {title}")
        
        return "\n".join(timeline_parts) if timeline_parts else "无"
    
    def _build_character_relationships(self) -> str:
        """组装人物关系"""
        if not self.characters:
            return "无"
        
        # 简化版：直接返回人物小传前 500 字
        parts = []
        for name, bio in self.characters.items():
            parts.append(f"【{name}】\n{bio[:500]}...")
        
        return "\n\n".join(parts) if parts else "无"
    
    def _parse_review_response(self, response: str) -> dict:
        """解析审核响应 - 简化文本格式解析"""
        import re
        result = {
            "time_coherence_score": 70,
            "fact_accuracy_score": 70,
            "literary_quality_score": 70,
            "logic_consistency_score": 70,
            "overall_score": 70,
            "passed": False,
            "issues": [],
            "highlights": [],
            "suggestions": []
        }
        
        try:
            # 解析分数
            scores_match = re.search(r'===SCORES===\s*(.*?)\s*===', response, re.DOTALL)
            if scores_match:
                scores_text = scores_match.group(1)
                for line in scores_text.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        if key == 'time_coherence':
                            result['time_coherence_score'] = int(re.search(r'\d+', value).group())
                        elif key == 'fact_accuracy':
                            result['fact_accuracy_score'] = int(re.search(r'\d+', value).group())
                        elif key == 'literary_quality':
                            result['literary_quality_score'] = int(re.search(r'\d+', value).group())
                        elif key == 'logic_consistency':
                            result['logic_consistency_score'] = int(re.search(r'\d+', value).group())
                        elif key == 'overall':
                            result['overall_score'] = int(re.search(r'\d+', value).group())
                        elif key == 'passed':
                            result['passed'] = value.lower() == 'true'
            
            # 解析问题
            issues_match = re.search(r'===ISSUES===\s*(.*?)\s*===', response, re.DOTALL)
            if issues_match:
                issues_text = issues_match.group(1).strip()
                result['issues'] = [line.strip() for line in issues_text.split('\n') if line.strip()]
            
            # 解析亮点
            highlights_match = re.search(r'===HIGHLIGHTS===\s*(.*?)\s*===', response, re.DOTALL)
            if highlights_match:
                highlights_text = highlights_match.group(1).strip()
                result['highlights'] = [line.strip() for line in highlights_text.split('\n') if line.strip()]
            
            # 解析建议
            suggestions_match = re.search(r'===SUGGESTIONS===\s*(.*?)$', response, re.DOTALL)
            if suggestions_match:
                suggestions_text = suggestions_match.group(1).strip()
                # 移除可能的结束标记
                suggestions_text = re.sub(r'===.*?===.*$', '', suggestions_text, flags=re.DOTALL).strip()
                result['suggestions'] = [line.strip() for line in suggestions_text.split('\n') if line.strip()]
                
        except Exception as e:
            print(f"   ⚠️ 审核结果解析失败: {e}")
            print(f"   📝 响应片段: {response[:300]}...")
            result["issues"] = [f"审核结果解析失败: {str(e)}"]
        
        # 确保passed状态正确
        if result['overall_score'] >= 90 and not any('【严重】' in issue for issue in result['issues']):
            result['passed'] = True
        
        return result
    
    async def _review_chapter(self, content: str, outline: dict, chapter_order: int = 1) -> dict:
        """审核章节 - 使用思考模式 + 完整上下文"""
        
        # 1. 读取配置
        review_config = self.config.get('iterative_review', {})
        pass_threshold = review_config.get('pass_threshold', 70)
        
        # 2. 动态确定前文数量
        previous_count = self._get_previous_count(chapter_order, review_config)
        
        # 3. 组装前文摘要
        previous_context = await self._build_previous_context(chapter_order, previous_count)
        
        # 4. 组装时间线和人物关系
        timeline = self._build_timeline()
        character_relationships = self._build_character_relationships()
        
        # 5. 组装提示词
        prompt = prompts.REVIEW_PROMPT.format(
            previous_context=previous_context,
            timeline=timeline,
            character_relationships=character_relationships,
            chapter_content=content,  # 不截断
            material_excerpt=self.material[:5000] if self.material else ""
        )
        
        # 6. 使用思考模式审核
        thinking, response = await self.llm.complete_with_thinking([
            {"role": "user", "content": prompt}
        ], temperature=0.3, max_tokens=8000, timeout=300)
        
        # 7. 解析 JSON
        result = self._parse_review_response(response)
        
        # 8. 应用阈值
        result["passed"] = result.get("overall_score", 0) >= pass_threshold
        
        # 打印审核结果
        print(f"   📊 审核: 总分={result.get('overall_score', '?')}")
        if not result["passed"]:
            print(f"   ⚠️ 问题: {', '.join(result.get('issues', [])[:2])}")
        
        return result
