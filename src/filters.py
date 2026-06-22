"""过滤规则常量 — 单一来源, run_generate_cards 和 report_generator 均从此导入"""
import re as _re

HARD_BLOCK_WORDS = [
    # 空洞形容
    "引领潮流", "彰显品味", "极致奢华", "不容错过", "匠心独运", "完美诠释",
    "为…注入新活力", "奏响…乐章",
    # 万能开头
    "众所周知",
    # 说破后台
    "根据您的喜好", "为您精选", "考虑到您", "专属定制",
    # 导购口吻
    "值得拥有", "不二之选", "强烈推荐", "错过不再有", "手慢无",
    # 炫富口吻
    "豪掷", "天价", "身份象征", "顶级圈层",
    # 凑数句式
    "可能影响体验", "并非人人适合", "见仁见智", "交通成本较高",
    # 反效果叙事(作为卖点时)
    "匠人手作", "纯手工打造",
]

HARD_BLOCK_PATTERNS = [
    _re.compile(r'随着.{1,20}的发展'),
    _re.compile(r'在.{1,20}的今天'),
    _re.compile(r'近年来'),
]
# 软标级: 命中→标记待人工复核, 但卡片仍可入报(人裁决语境)

SOFT_FLAG_WORDS = [
    "手工精制", "手雕", "匠造", "限量发售", "全球限量",
]

SOFT_FLAG_PATTERNS = [
    _re.compile(r'限量\s*\d+'),
]

# 内部编号模式

INTERNAL_PATTERN = _re.compile(
    r'(候选\d+|article[_\-]?id|#\d+|[ABCD]档|兴奋\d|落地\d|密度\d|卡片\s*\d+|第\s*\d+\s*[张篇个]|\bcard\s*\d+|编号\s*\d+)',
    _re.IGNORECASE
)


def _lcs_len(s1: str, s2: str) -> int:
    if not s1 or not s2: return 0
    m, n = len(s1), len(s2)
    dp = [[0]*(n+1) for _ in range(m+1)]
    mx = 0
    for i in range(1, m+1):
        for j in range(1, n+1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
                if dp[i][j] > mx: mx = dp[i][j]
    return mx


def check_forbidden(text: str):
    """两级过滤. 返回 (hard_hits, soft_hits)"""
    hard, soft = [], []
    for w in HARD_BLOCK_WORDS:
        if w in text: hard.append(w)
    for p in HARD_BLOCK_PATTERNS:
        m = p.search(text)
        if m: hard.append(m.group())
    for w in SOFT_FLAG_WORDS:
        if w in text: soft.append(w)
    for p in SOFT_FLAG_PATTERNS:
        m = p.search(text)
        if m: soft.append(m.group())
    return hard, soft


def build_fact_extract_prompt(article: dict) -> str:
    content = (article.get("translated_content") or article.get("content") or "")
    if len(content) > 3000:
        content = content[:3000] + "..."
    return f"""原文标题: {article.get('title', '')}

原文内容:
{content}

请按照系统提示提取事实,只输出 JSON。"""


def _sanitize_text(text: str) -> str:
    """替换上游字段中的敏感称谓，杜绝人称泄漏源头。"""
    if not text:
        return ""
    for old, new in _SANITIZE_REPLACEMENTS:
        text = text.replace(old, new)
    return text

def build_card_prompt(article: dict, facts: dict) -> str:
    title = article.get("title", "")
    content = (article.get("translated_content") or article.get("content") or "")
    if len(content) > 3000:
        content = content[:3000] + "..."

    fit_reasons = article.get("gate2_fit_reasons", [])
    if isinstance(fit_reasons, str):
        try: fit_reasons = json.loads(fit_reasons)
        except: fit_reasons = []
    fit_reasons_str = _sanitize_text(json.dumps(fit_reasons, ensure_ascii=False))
    one_line = _sanitize_text(article.get("gate2_one_line", ""))
    rationale = _sanitize_text(article.get("gate3_rationale", ""))

    facts_str = json.dumps(facts, ensure_ascii=False, indent=2)

    return f"""请为以下内容撰写推荐卡:

=== 原文 ===
标题: {title}
正文: {content}

=== 事实提取结果 ===
{facts_str}

=== 上游筛选参考 ===
命中兴奋点: {fit_reasons_str}
一句话钩子: {one_line}
小组赛胜出理由: {rationale}

注意:
- 推荐语必须基于原文事实重新写,禁止直接照抄 one_line
- 禁止把 fit_reasons 的内部表述(如"命中艺术坐标")带进文案
- 若发现原文事实与上游字段矛盾,以原文为准,editor_confidence 置为 low
- 只输出 JSON,不要输出其他文字"""

PERSON_REF_PATTERN = _re.compile(r'(他空间|他的空间|您|阁下|服务对象)', _re.IGNORECASE)


def check_field(text: str) -> dict:
    """两级过滤. 返回 {"hard": [...], "soft": [...]}"""
    result = {"hard": [], "soft": []}
    m = INTERNAL_PATTERN.search(text)
    if m: result["hard"].append(f"内部编号:{m.group()}")
    m = PERSON_REF_PATTERN.search(text)
    if m: result["hard"].append(f"人称泄漏:{m.group()}")
    for w in HARD_BLOCK_WORDS:
        if w in text: result["hard"].append(f"禁词:{w}")
    for p in HARD_BLOCK_PATTERNS:
        m = p.search(text)
        if m: result["hard"].append(f"禁句:{m.group()}")
    for w in SOFT_FLAG_WORDS:
        if w in text: result["soft"].append(f"工艺词:{w}")
    for p in SOFT_FLAG_PATTERNS:
        m = p.search(text)
        if m: result["soft"].append(f"限量句:{m.group()}")
    return result
