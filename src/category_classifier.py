"""Conservative category correction for newly crawled articles."""

from __future__ import annotations

import re

STANDARD_CATEGORIES = [
    "精品酒店与度假",
    "旅行与探索",
    "美食与美酒",
    "艺术与文化",
    "建筑与空间",
    "产品与设计",
    "时尚与风格",
    "珠宝与腕表",
    "汽车与出行",
    "科技与生活",
    "健康与养生",
    "音乐与演出",
]

STRONG_HINT_CATEGORIES = {
    "精品酒店与度假",
    "旅行与探索",
    "美食与美酒",
    "时尚与风格",
    "珠宝与腕表",
    "汽车与出行",
    "健康与养生",
    "音乐与演出",
}

SOURCE_DEFAULTS = {
    "artsy": "艺术与文化",
    "artnet": "艺术与文化",
    "colossal": "艺术与文化",
    "my modern met": "艺术与文化",
    "google arts": "艺术与文化",
    "pitchfork": "音乐与演出",
    "the quietus": "音乐与演出",
    "resident advisor": "音乐与演出",
    "fader": "音乐与演出",
    "eater": "美食与美酒",
    "punch": "美食与美酒",
    "whisky advocate": "美食与美酒",
}

CATEGORY_RULES = [
    ("音乐与演出", ["album", "song", "single", "concert", "festival", "composer", "orchestra", "opera", "dj", "专辑", "单曲", "音乐节", "演出", "作曲", "歌剧"]),
    ("美食与美酒", ["restaurant", "chef", "menu", "wine", "whisky", "cocktail", "bar", "dining", "餐厅", "主厨", "菜单", "葡萄酒", "威士忌", "鸡尾酒"]),
    ("精品酒店与度假", ["hotel", "resort", "suite", "villa", "lodge", "retreat", "ryokan", "酒店", "度假村", "套房", "旅馆", "温泉旅馆"]),
    ("珠宝与腕表", ["jewelry", "jewellery", "watch", "timepiece", "diamond", "bracelet", "necklace", "珠宝", "腕表", "手表", "钻石", "项链"]),
    ("汽车与出行", ["car", "automotive", "supercar", "suv", "ev", "yacht", "motorcycle", "汽车", "跑车", "游艇", "摩托"]),
    ("时尚与风格", ["fashion", "couture", "runway", "sneaker", "bag", "时装", "时尚", "高定", "秀场", "手袋", "球鞋"]),
    ("健康与养生", ["wellness", "spa", "fitness", "longevity", "meditation", "health", "水疗", "健身", "冥想", "长寿", "养生"]),
    ("旅行与探索", ["travel", "destination", "itinerary", "flight", "airline", "journey", "旅行", "目的地", "航班", "航空", "行程"]),
    ("科技与生活", ["ai", "robot", "device", "gadget", "app", "smart home", "wearable", "科技", "机器人", "智能家居", "可穿戴"]),
    ("产品与设计", ["product design", "industrial design", "furniture", "chair", "table", "lamp", "lighting", "ceramic", "object", "appliance", "产品设计", "工业设计", "家具", "椅", "桌", "灯具", "陶瓷", "器物"]),
    ("建筑与空间", ["architecture", "architect", "house", "residence", "interior", "pavilion", "building", "住宅", "建筑", "室内", "展亭", "空间"]),
    ("艺术与文化", ["artist", "artwork", "painting", "sculpture", "gallery", "museum", "exhibition", "biennale", "auction", "艺术家", "绘画", "雕塑", "画廊", "博物馆", "展览", "双年展", "拍卖"]),
]


def normalize_category(category: str | None) -> str:
    category = (category or "").strip()
    if category in STANDARD_CATEGORIES:
        return category
    lowered = category.lower()
    for standard in STANDARD_CATEGORIES:
        if standard.lower() == lowered:
            return standard
    return ""


def correct_category(
    *,
    title: str,
    content: str,
    source: str = "",
    category_hint: str = "",
    ai_category: str = "",
) -> tuple[str, str]:
    """Return final category and a short reason.

    Priority:
    1. high-confidence title/content keyword correction
    2. source-specific default for strong vertical sources
    3. strong configured site hint
    4. AI category
    5. configured site hint
    """
    hint = normalize_category(category_hint)
    ai = normalize_category(ai_category)
    source_lower = (source or "").lower()
    text = f"{title or ''}\n{(content or '')[:1200]}".lower()

    for category, terms in CATEGORY_RULES:
        if _has_any_term(text, terms):
            return category, "keyword_rule"

    for source_key, category in SOURCE_DEFAULTS.items():
        if source_key in source_lower:
            return category, "source_default"

    if hint in STRONG_HINT_CATEGORIES:
        return hint, "strong_site_hint"

    if ai:
        return ai, "ai_category"

    if hint:
        return hint, "site_hint"

    return "艺术与文化", "fallback"


def _has_any_term(text: str, terms: list[str]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _contains_term(text: str, term: str) -> bool:
    term = term.lower()
    if term.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text
