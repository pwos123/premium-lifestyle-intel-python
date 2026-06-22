"""
快速分析器 — 单模型，用于抓取阶段的初步筛选
只判断相关性 + 简单分类 + 一句话推荐理由
不烧三个模型的钱
"""

import logging
import re
from .models import LLMCaller, ModelConfig

logger = logging.getLogger(__name__)

QUICK_PROMPT = """你是一位高端生活方式内容分析师。请快速判断以下文章是否值得推荐给关注设计、艺术、旅行、美食的高端读者。

请严格按 JSON 格式输出：
{
  "is_relevant": true/false,
  "translated_title": "中文标题，准确翻译原题并适合卡片展示，30字以内",
  "translated_content": "英文原文的完整中文翻译，一字不漏，忠实还原原文所有信息和细节，保留专有名词",
  "category": "从以下选一个：精品酒店与度假/旅行与探索/美食与美酒/艺术与文化/建筑与空间/产品与设计/时尚与风格/珠宝与腕表/汽车与出行/科技与生活/健康与养生/音乐与演出",
  "quick_score": 0-100的整数（粗略评分）,
  "quick_reason": "中文摘要/推荐理由，100-180字，涵盖核心事实与亮点，说明内容是什么以及为什么值得关注"
}

判断标准：
- 与高端生活方式（设计、艺术、旅行、美食、时尚、建筑、音乐）相关 → true
- 以下类型 → is_relevant=false，quick_score≤30：
  · 纯产品目录/商品页（只有价格、规格、购买链接，无深度内容）
  · 政治新闻、战争、社会运动等非生活方式话题
  · 杂志目录页、活动日程列表
  · 纯广告/软文，无实质信息
  · 学校、幼儿园、大学、工厂、仓库、普通办公楼、产业园、基础设施、市政工程、普通住宅楼（除非有酒店/餐厅/美术馆/文化空间等高价值例外）
- is_relevant=true 时 quick_score 参考：
  · 80-100：有独特视角、深度分析、精美视觉、稀缺信息
  · 60-79：内容扎实，值得一读
  · 40-59：内容一般，相关性弱
  · 40以下：基本不相关"""

LOW_LIFESTYLE_TERMS = [
    "school", "campus", "kindergarten", "university", "factory", "warehouse",
    "plant", "office", "headquarters", "industrial park", "infrastructure",
    "学校", "校园", "幼儿园", "大学", "工厂", "仓库", "厂房", "办公楼", "总部",
    "产业园", "基础设施", "市政",
]

LIFESTYLE_EXCEPTIONS = [
    "hotel", "resort", "restaurant", "villa", "residence", "home", "house",
    "museum", "gallery", "spa", "retreat", "wellness",
    "酒店", "度假", "餐厅", "别墅", "住宅", "家居", "博物馆", "画廊",
    "水疗", "静修", "健康",
]


class QuickAnalyzer:
    """快速分析器 — 仅用第一个可用模型"""

    def __init__(self, configs: dict[str, ModelConfig]):
        self.llm = LLMCaller(configs)
        if self.llm.available_models:
            self.model_name = self.llm.available_models[0]
            logger.info(f"快速分析器使用模型: {self.model_name}")
        else:
            self.model_name = None
            logger.warning("没有可用的模型")

    def analyze(self, title: str, content: str, source: str = "") -> dict:
        """快速分析，返回简化结果"""
        looks_low_lifestyle = self._looks_low_lifestyle(title, content)
        if not self.model_name:
            return self._fallback(looks_low_lifestyle)

        # 截断内容，快速分析不需要全文
        content = content[:8000] if len(content) > 8000 else content

        user_prompt = f"来源：{source}\n标题：{title}\n\n内容：\n{content}"

        result = self.llm.call_model(
            self.model_name, QUICK_PROMPT, user_prompt,
            temperature=0.2, max_tokens=3000, timeout=60,
        )

        if result.success and result.data:
            data = result.data
            if looks_low_lifestyle:
                data["is_relevant"] = False
                data["quick_score"] = min(int(data.get("quick_score", 0) or 0), 55)
            return data
        return self._fallback(looks_low_lifestyle)

    @staticmethod
    def _fallback(looks_low_lifestyle: bool) -> dict:
        if looks_low_lifestyle:
            return {
                "is_relevant": False,
                "translated_title": "",
                "translated_content": "",
                "category": "",
                "quick_score": 45,
                "quick_reason": "包含学校、工厂、仓储、普通办公或市政基础设施等低生活方式相关主题，暂不进入精选。",
            }
        return {
            "is_relevant": True,
            "translated_title": "",
            "translated_content": "",
            "category": "",
            "quick_score": 50,
            "quick_reason": "待人工判断",
        }

    @staticmethod
    def _looks_low_lifestyle(title: str, content: str) -> bool:
        text = f"{title} {content[:800]}".lower()
        has_low_term = any(_contains_term(text, term) for term in LOW_LIFESTYLE_TERMS)
        has_exception = any(_contains_term(text, term) for term in LIFESTYLE_EXCEPTIONS)
        return has_low_term and not has_exception


def _contains_term(text: str, term: str) -> bool:
    term = term.lower()
    if term.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text
