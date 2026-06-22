"""Lightweight article-level AI actions for the admin detail modal."""

from src.config import load_config, load_model_configs
from src.models import LLMCaller, ModelConfig
from web.state import db


SUMMARY_SYSTEM_PROMPT = """你是一位专业中文编辑。请根据原文为文章生成中文事实摘要。

要求:
- 100字以内。
- 只陈述事实:谁、做了什么、在哪、何时、规模数字。
- 不评价、不推荐、不展望。
- 禁用词:不可错过、文化盛事、极致、奢华、彰显品味、引领潮流、匠心独运、完美诠释、深度探访、值得拥有、读者、人群、爱好者、品鉴、探访、高端人士。
- 只输出 JSON: {"summary":"摘要文本"}"""

TRANSLATION_SYSTEM_PROMPT = """你是一位忠实克制的中文译者。请把英文原文整理为中文详译。

要求:
- 只翻译/整理原文事实，不新增评价和推荐。
- 保留关键名称、地点、时间、数字、材料、作者、机构和项目细节。
- 原文很长时压缩到 800-1400 字；原文较短时尽量完整。
- 语言自然，不写营销腔。
- 只输出 JSON: {"translated_content":"中文详译文本"}"""

BANNED_SUMMARY_WORDS = [
    "不可错过",
    "文化盛事",
    "极致",
    "奢华",
    "彰显品味",
    "引领潮流",
    "匠心独运",
    "完美诠释",
    "深度探访",
    "值得拥有",
    "读者",
    "人群",
    "爱好者",
    "品鉴",
    "探访",
    "高端人士",
]


def _qwen_caller(model_override: str | None = None) -> LLMCaller:
    config = load_config()
    model_configs = load_model_configs(config)
    qwen_cfg = model_configs.get("qwen")
    if not qwen_cfg:
        raise RuntimeError("qwen 未配置")
    cfg = qwen_cfg
    if model_override:
        cfg = ModelConfig(
            name="qwen",
            api_key=qwen_cfg.api_key,
            base_url=qwen_cfg.base_url,
            model=model_override,
            weight=qwen_cfg.weight,
        )
    return LLMCaller({"qwen": cfg})


def _article_prompt(article: dict, max_chars: int) -> str:
    content = (article.get("content") or "")[:max_chars]
    return (
        f"article_id: {article.get('id')}\n"
        f"标题: {article.get('title', '')}\n"
        f"信源: {article.get('source', '')}\n"
        f"频道: {article.get('category', '')}\n"
        f"正文:\n{content}"
    )


def _validate_summary(summary: str) -> str | None:
    if not summary.strip():
        return "摘要为空"
    if len(summary) > 120:
        return f"摘要超长({len(summary)}字)"
    hit = [word for word in BANNED_SUMMARY_WORDS if word in summary]
    if hit:
        return "禁用词:" + ",".join(hit)
    return None


def rerun_article_summary(article_id: int) -> dict:
    article = db.get_article(article_id)
    if not article:
        return {"ok": False, "error": "文章不存在"}
    if not (article.get("content") or "").strip():
        return {"ok": False, "error": "文章正文为空，无法重跑摘要"}

    caller = _qwen_caller("qwen-flash")
    result = caller.call_model(
        "qwen",
        SUMMARY_SYSTEM_PROMPT,
        _article_prompt(article, 3000),
        temperature=0.2,
        max_tokens=500,
        timeout=30,
    )
    if not result.success or not result.data:
        return {"ok": False, "error": result.error or "模型未返回有效摘要"}

    summary = (result.data.get("summary") or "").strip()
    invalid = _validate_summary(summary)
    if invalid:
        return {"ok": False, "error": invalid}

    db.update_article(article_id, {"summary": summary, "summary_flagged": 0})
    return {"ok": True, "summary": summary}


def translate_article_content(article_id: int) -> dict:
    article = db.get_article(article_id)
    if not article:
        return {"ok": False, "error": "文章不存在"}
    if not (article.get("content") or "").strip():
        return {"ok": False, "error": "文章正文为空，无法补全文翻译"}

    caller = _qwen_caller()
    result = caller.call_model(
        "qwen",
        TRANSLATION_SYSTEM_PROMPT,
        _article_prompt(article, 6000),
        temperature=0.2,
        max_tokens=2200,
        timeout=60,
    )
    if not result.success or not result.data:
        return {"ok": False, "error": result.error or "模型未返回有效译文"}

    translated_content = (result.data.get("translated_content") or "").strip()
    if len(translated_content) < 40:
        return {"ok": False, "error": "译文过短，未写入"}

    db.update_article(article_id, {"translated_content": translated_content})
    return {"ok": True, "translated_content": translated_content}
