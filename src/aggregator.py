"""
三模型交叉验证结果聚合器
策略：多数投票、加权平均、并集合并
"""

import logging
from collections import Counter
from typing import Optional

from .models import ModelResponse

logger = logging.getLogger(__name__)

# 分类名到标准分类的映射（容忍模型输出变体）
CATEGORY_ALIASES = {
    "精品酒店与度假": ["精品酒店与度假", "酒店", "度假", "hotel", "resort", "精品酒店"],
    "旅行与探索": ["旅行与探索", "旅行", "探索", "travel", "旅行体验"],
    "美食与美酒": ["美食与美酒", "美食", "美酒", "food", "wine", "餐厅", "美食体验"],
    "艺术与文化": ["艺术与文化", "艺术", "文化", "art", "culture", "展览"],
    "产品与设计": ["产品设计", "工业设计", "家具", "灯具", "家居用品", "器物", "product design", "industrial design", "furniture", "lighting", "ceramic", "craft"],
    "建筑与空间": ["建筑与空间", "建筑", "architecture", "建筑", "design", "architecture", "室内设计"],
    "时尚与风格": ["时尚与风格", "时尚", "风格", "fashion", "style", "穿搭"],
    "珠宝与腕表": ["珠宝与腕表", "珠宝", "腕表", "jewelry", "watch", "手表"],
    "汽车与出行": ["汽车与出行", "汽车", "出行", "car", "automotive", "超跑"],
    "科技与生活": ["科技与生活", "科技", "生活", "tech", "technology", "智能"],
    "健康与养生": ["健康与养生", "健康", "养生", "wellness", "health", "健身"],
}

STANDARD_CATEGORIES = list(CATEGORY_ALIASES.keys())


def normalize_category(raw: str) -> str:
    """将模型输出的分类名标准化"""
    if not raw:
        return "建筑与空间"  # 默认分类
    raw_lower = raw.strip().lower()
    for standard, aliases in CATEGORY_ALIASES.items():
        for alias in aliases:
            if alias.lower() in raw_lower or raw_lower in alias.lower():
                return standard
    return raw.strip()  # 无法匹配则保留原样


def aggregate_results(
    results: dict[str, ModelResponse],
    weights: Optional[dict[str, float]] = None,
) -> dict:
    """
    聚合多模型结果

    Args:
        results: {"deepseek": ModelResponse, "qwen": ModelResponse, "kimi": ModelResponse}
        weights: {"deepseek": 1.0, "qwen": 1.0, "kimi": 1.0}

    Returns:
        聚合后的分析结果字典
    """
    if weights is None:
        weights = {"deepseek": 1.0, "qwen": 1.0, "kimi": 1.0}

    successful = {k: v for k, v in results.items() if v.success and v.data}
    if not successful:
        logger.error("所有模型分析失败")
        return _empty_result()

    # 构建 model_votes
    model_votes = {}
    for name, resp in results.items():
        model_votes[name] = {
            "success": resp.success,
            "category": resp.data.get("category", "") if resp.data else "",
            "score": resp.data.get("score", 0) if resp.data else 0,
            "error": resp.error,
        }

    # === 1. 分类：多数投票 ===
    categories = [
        normalize_category(d.data.get("category", ""))
        for d in successful.values()
    ]
    category_counts = Counter(categories)
    final_category = category_counts.most_common(1)[0][0]

    # === 2. 评分：加权平均 ===
    scores = []
    total_weight = 0
    for name, resp in successful.items():
        w = weights.get(name, 1.0)
        s = resp.data.get("score", 0)
        if isinstance(s, (int, float)) and 0 <= s <= 100:
            scores.append(s * w)
            total_weight += w
    final_score = round(sum(scores) / total_weight) if total_weight > 0 else 0

    # === 3. 推荐等级：基于平均分 ===
    if final_score >= 85:
        recommend_level = "必看"
    elif final_score >= 70:
        recommend_level = "推荐"
    elif final_score >= 60:
        recommend_level = "了解"
    else:
        recommend_level = "了解"

    # === 4. 摘要：取最长最详细的 ===
    translated_titles = [
        d.data.get("translated_title", "")
        for d in successful.values()
        if d.data.get("translated_title")
    ]
    final_translated_title = min(translated_titles, key=len) if translated_titles else ""

    translated_contents = [
        d.data.get("translated_content", "")
        for d in successful.values()
        if d.data.get("translated_content")
    ]
    final_translated_content = max(translated_contents, key=len) if translated_contents else ""

    # === 5. 摘要：取最长最详细的 ===
    summaries = [
        d.data.get("summary", "")
        for d in successful.values()
        if d.data.get("summary")
    ]
    final_summary = max(summaries, key=len) if summaries else ""

    # === 5. 场景分析：取最具体的 ===
    scenarios = [
        d.data.get("scenario", "")
        for d in successful.values()
        if d.data.get("scenario")
    ]
    final_scenario = max(scenarios, key=len) if scenarios else ""

    # === 6. 推荐理由：取最有说服力的 ===
    reasons = [
        d.data.get("recommend_reason", "")
        for d in successful.values()
        if d.data.get("recommend_reason")
    ]
    final_reason = max(reasons, key=len) if reasons else ""

    # === 7. 标签：取并集去重 ===
    all_tags = set()
    for d in successful.values():
        tags = d.data.get("tags", [])
        if isinstance(tags, list):
            all_tags.update(t.strip() for t in tags if t.strip())
    final_tags = sorted(all_tags)[:10]  # 最多10个标签

    # === 8. 优缺点：取并集去重 ===
    all_pros = []
    all_cons = []
    seen_pros = set()
    seen_cons = set()
    for d in successful.values():
        for p in d.data.get("pros", []):
            if p and p not in seen_pros:
                all_pros.append(p)
                seen_pros.add(p)
        for c in d.data.get("cons", []):
            if c and c not in seen_cons:
                all_cons.append(c)
                seen_cons.add(c)

    # === 9. 相关性判断：多数投票 ===
    relevance_votes = [d.data.get("is_relevant", True) for d in successful.values()]
    is_relevant = sum(relevance_votes) > len(relevance_votes) / 2

    return {
        "is_relevant": is_relevant,
        "translated_title": final_translated_title,
        "translated_content": final_translated_content,
        "category": final_category,
        "score": final_score,
        "summary": final_summary,
        "tags": final_tags,
        "recommend_reason": final_reason,
        "scenario": final_scenario,
        "pros": all_pros[:5],
        "cons": all_cons[:5],
        "recommend_level": recommend_level,
        "model_votes": model_votes,
    }


def _empty_result() -> dict:
    """所有模型失败时的空结果"""
    return {
        "is_relevant": False,
        "translated_title": "",
        "translated_content": "",
        "category": "建筑与空间",
        "score": 0,
        "summary": "AI 分析失败，请人工审核",
        "tags": [],
        "recommend_reason": "",
        "scenario": "",
        "pros": [],
        "cons": [],
        "recommend_level": "了解",
        "model_votes": {},
    }
