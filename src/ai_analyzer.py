"""
AI 分析器 — 三模型交叉验证主流程
"""

import logging
from typing import Optional

from .models import LLMCaller, ModelConfig
from .aggregator import aggregate_results
from prompts.summary_generation import SUMMARY_PROMPT_CONSTRAINT

logger = logging.getLogger(__name__)

# 读者画像（用于 AI 筛选）
READER_PROFILE = """
目标读者画像:
- 高端中文读者，关注全球精品生活方式
- 主要兴趣领域：建筑设计、室内设计、艺术收藏、精品酒店、高端旅行
- 偏好：东方美学、侘寂美学、极简主义、自然与人文结合
- 阅读风格：注重品质而非数量，喜欢有深度的内容，关注独特体验
- 年龄层：40-55岁成功人士
- 语言：以中文为主，接受英文内容但需提供中文摘要
"""

SYSTEM_PROMPT = f"""你是一位高端生活方式内容分析师。你的任务是分析一篇文章是否符合目标读者的需求。

{READER_PROFILE}

请严格按照以下 JSON 格式输出分析结果，不要输出其他内容：

{{
  "is_relevant": true/false,
  "translated_title": "中文标题，准确翻译/改写原题，适合周报卡片展示，30字以内",
  "translated_content": "英文原文的中文译文/详译版，800-1400字，保留关键事实、名称、地点、设计细节和体验描述；如原文较短则尽量完整翻译",
  "category": "分类名（从以下选择：精品酒店与度假/旅行与探索/美食与美酒/艺术与文化/建筑与空间/产品与设计/时尚与风格/珠宝与腕表/汽车与出行/科技与生活/健康与养生/音乐与演出）",
  "score": 0-100的整数评分,
  "summary": "中文图文内容整理，100字以内。只陈述事实:谁、做了什么、在哪、何时、规模数字。禁用词:不可错过、文化盛事、极致、奢华、彰显品味、引领潮流、匠心独运、完美诠释、深度探访、值得拥有。禁止'适合……的读者/爱好者/人群'句式。禁止评价性收尾,以事实句结束",
  "tags": ["标签1", "标签2", "标签3"],
  "recommend_reason": "80-140字推荐理由，说明为什么值得关注，要有判断、有取舍，不要空泛",
  "scenario": "120-180字实用分析，聚焦这条内容本身的价值：可以怎么用、解决什么问题、适合什么场景落地、能带来什么启发或行动。不要出现任何人名或特定读者代称，不要说"可以收藏/转发"之类的废话，要写出对这条内容能做什么的具体判断",
  "pros": ["实现优点1", "实现优点2", "实现优点3", "实现优点4"],
  "cons": ["实现缺点或风险1", "实现缺点或风险2", "实现缺点或风险3"],
  "recommend_level": "必看/推荐/了解"
}}

评分标准：
- 90-100: 极度契合读者画像，独一无二的体验或内容
- 80-89: 高度相关，高品质内容
- 70-79: 值得关注，有一定独特性
- 60-69: 一般相关，可以了解
- 60以下: 不太相关

注意：
1. 如果文章内容与高端生活方式无关，is_relevant 设为 false
   - 学校、幼儿园、大学、工厂、仓库、普通办公楼、产业园、基础设施、市政工程、普通住宅楼等项目，除非明确具备高端生活体验、精品酒店、艺术文化、餐饮、度假、收藏或高端私人生活方式价值，否则设为 false 且评分低于55
2. 所有文本输出请使用中文
3. pros 和 cons 聚焦可实现性、体验价值、成本门槛、审美风险、时间成本等维度，每条不超过28字
4. tags 提供 4-8 个关键词标签
5. 内容要像给高端读者看的生活体验周报，克制、具体、可判断
6. scenario 字段不要出现任何人名、"董事长"、"DJ"等特定称呼，只写内容本身的实用价值"""


def build_user_prompt(title: str, content: str, source: str, category_hint: str = "") -> str:
    """构建用户提示词"""
    # 截断过长的内容
    max_content_len = 3000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "..."

    prompt = f"""请分析以下文章：

来源网站：{source}
分类提示：{category_hint or '无'}
文章标题：{title}

文章内容：
{content}

请按照系统提示中的 JSON 格式输出分析结果。"""
    return prompt


class AIAnalyzer:
    """三模型交叉验证 AI 分析器"""

    def __init__(self, configs: dict[str, ModelConfig], weights: Optional[dict[str, float]] = None):
        self.llm = LLMCaller(configs)
        self.weights = weights or {"deepseek": 1.0, "qwen": 1.0, "kimi": 1.0}
        logger.info(f"AI 分析器初始化完成，可用模型: {self.llm.available_models}")

    def analyze_article(
        self,
        title: str,
        content: str,
        source: str = "",
        category_hint: str = "",
    ) -> dict:
        """
        分析单篇文章，调用所有可用模型并聚合结果

        Returns:
            聚合后的分析结果字典
        """
        user_prompt = build_user_prompt(title, content, source, category_hint)

        logger.info(f"开始三模型分析: {title[:50]}...")
        results = self.llm.call_all_models(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=3200,
            timeout=60,
        )

        # 统计结果
        success_count = sum(1 for r in results.values() if r.success)
        logger.info(f"模型调用完成: {success_count}/{len(results)} 成功")

        # 聚合结果
        aggregated = aggregate_results(results, self.weights)
        logger.info(
            f"分析完成: 分类={aggregated['category']}, "
            f"评分={aggregated['score']}, "
            f"等级={aggregated['recommend_level']}"
        )

        return aggregated

    def quick_analyze(self, title: str, content: str, source: str = "") -> dict:
        """
        快速分析（仅用第一个可用模型），用于初步筛选
        """
        if not self.llm.available_models:
            return {"is_relevant": False, "score": 0}

        model_name = self.llm.available_models[0]
        user_prompt = build_user_prompt(title, content, source)
        result = self.llm.call_model(model_name, SYSTEM_PROMPT, user_prompt)

        if result.success and result.data:
            return result.data
        return {"is_relevant": False, "score": 0}
