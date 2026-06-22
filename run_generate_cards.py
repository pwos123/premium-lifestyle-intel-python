#!/usr/bin/env python3
"""
成卡撰写 — 两步生成链路 (v3 体验策展版)
第一步: 事实提取 (deepseek-v4-flash)
第二步: 推荐卡撰写 (deepseek-v4-pro + v3 完整 prompt)
第三步: 本期看点 (deepseek-v4-pro, 全部卡片生成后)
输入: A/B 精选池文章
输出: 推荐卡 JSON + 本期看点 → 存回数据库
"""

import sys, json, logging, time, argparse, re as _re, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.filters import HARD_BLOCK_WORDS, HARD_BLOCK_PATTERNS, SOFT_FLAG_WORDS, SOFT_FLAG_PATTERNS, INTERNAL_PATTERN, PERSON_REF_PATTERN, check_field
from src.config import load_config, load_model_configs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cards")

from prompts.card_writer_v3 import FACT_EXTRACT_PROMPT, CARD_WRITER_PROMPT

# 重试压缩专用 prompt
COMPRESS_RETRY_PROMPT = """你刚才写的推荐卡中 {field} 超出了字数上限（当前{current_len}字，上限{max_len}字）。
请重写 **只改写 {field} 字段**，压缩至 {max_len} 字以内。

压缩规则：
- 保留信息量最高的 2-3 个核心洞察或关键细节，删去次要铺陈
- 每句话检查：删掉它会不会丢失关键信息？会→保留，不会→删
- 禁止简单截断结尾——截断会丢掉最重要的结论
- 禁止填充「综上所述」「总的来说」等套话
- 输出完整 JSON，{field} 外的字段保持原值不变"""

# 输入脱敏：替换上游字段中的敏感称谓
_SANITIZE_REPLACEMENTS = [
    ("DJ", "读者"),
    ("服务对象", "读者"),
    ("他空间", "读者偏好的空间"),
    ("他的空间", "读者偏好的空间"),
]

# ============================================================
# 违禁词清单 (v3 第五节)
# ============================================================
# 硬拦级: 命中→重试一次→再命中转人工
EXAMPLE_TEXTS = [
    "这个展最大的看头不是成品,是过程",
    "从配土、拉坯、上釉到三天三夜的柴窑烧成全程参与",
    "把后厨直接搬进了餐位",
]
EXAMPLE_SIMILARITY_THRESHOLD = 15
YEAR_PATTERN = _re.compile(r"(?<!\d)20(?:2[0-9]|3[0-5])(?!\d)")

EDITOR_NOTE_PROMPT = """你刚才为读者的本周体验菜单生成了全部推荐卡。现在请通读所有卡片,写一段「本期看点」。\n\n【重要】必须以内容名称指代各篇文章(如标题关键词)，严禁使用任何编号(如"卡片1""第一篇""第1张")指代。

规则:
- 用 2-3 句点出本期最值得勾选的 1-2 条及理由(理由要具体到"门道",禁止"精彩纷呈""不容错过"等空话)
- 如本期条目间存在有趣的暗线(如多条都与"过程可见"有关),可点一句
- 总长不超过 100 字,克制、不吆喝
- 只引用输入卡片中明确出现的实体与名称，禁止编造不存在的内容或地点
- 只输出纯文本,不要 JSON,不要标题"""

def _sanitize_text(text: str) -> str:
    """替换上游字段中的敏感称谓，杜绝人称泄漏源头。"""
    if not text:
        return ""
    for old, new in _SANITIZE_REPLACEMENTS:
        text = text.replace(old, new)
    return text



def build_fact_extract_prompt(article: dict) -> str:
    content = (article.get("translated_content") or article.get("content") or "")
    if len(content) > 3000:
        content = content[:3000] + "..."
    return f"""原文标题: {article.get('title', '')}

原文内容:
{content}

请按照系统提示提取事实,只输出 JSON。"""




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


def _card_all_text(card: dict) -> str:
    return " ".join([
        card.get("body", ""),
        card.get("arrangement", ""),
        card.get("headline", ""),
        card.get("deep_dive", ""),
        " ".join(card.get("cautions", [])),
    ])


def _extract_years(text: str) -> set[str]:
    return set(YEAR_PATTERN.findall(text or ""))


def _article_date_text(article: dict, facts: dict | None = None) -> str:
    fields = [
        article.get("title", ""),
        article.get("translated_title", ""),
        article.get("summary", ""),
        article.get("content", ""),
        article.get("translated_content", ""),
        article.get("gate2_one_line", ""),
        article.get("gate3_rationale", ""),
    ]
    if facts:
        fields.append(json.dumps(facts, ensure_ascii=False))
    return "\n".join(str(v) for v in fields if v)


def check_card_date_risk(article: dict, card: dict, facts: dict | None = None) -> tuple[bool, str]:
    """Flag card years that are absent from source/facts; this catches 2026->2025 style hallucinations."""
    source_years = _extract_years(_article_date_text(article, facts))
    if not source_years:
        return False, ""
    card_years = _extract_years(json.dumps(card, ensure_ascii=False))
    invented_years = sorted(card_years - source_years)
    if not invented_years:
        return False, ""
    return True, f"date_year_mismatch:source={','.join(sorted(source_years))};card_extra={','.join(invented_years)}"


def _clamp_text_at_boundary(text: str, max_len: int, min_len: int = 40) -> str:
    """Shorten text at a natural sentence or clause boundary instead of a raw cut."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text

    strong_boundaries = "。！？!?；;"
    weak_boundaries = "，,、：:"
    window = text[:max_len + 1]

    for boundaries in (strong_boundaries, weak_boundaries):
        positions = [window.rfind(ch) for ch in boundaries]
        cut = max(positions)
        if cut >= min_len:
            return window[: cut + 1].strip()

    fallback = text[: max_len - 1].rstrip("，,、：:；; ")
    return (fallback + "…").strip()




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




def _make_model_caller(config: dict, model_configs: dict, role: str) -> LLMCaller | None:
    """从 settings.yaml gate_models 读取模型配置并创建 caller"""
    gate_cfg = config.get("gate_models", {}).get(role, {})
    provider = gate_cfg.get("provider", "deepseek")
    model_name = gate_cfg.get("model_override", "deepseek-chat")

    cfg = model_configs.get(provider)
    if not cfg:
        logger.error(f"Provider {provider} 未配置")
        return None

    model = ModelConfig(
        name=provider, api_key=cfg.api_key, base_url=cfg.base_url,
        model=model_name, weight=1.0
    )
    return LLMCaller({provider: model})

def run_card_generation(
    limit: int = 35,
    dry_run: bool = False,
    force: bool = False,
    workers: int = 1,
    progress_callback=None,
    article_ids: list[int] | None = None,
    generate_editor_note: bool = True,
):
    config = load_config()
    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    # ======== Fact extractor caller ========
    fact_caller = _make_model_caller(config, model_configs, "fact_extractor")
    if not fact_caller:
        return

    # ======== Card writer caller ========
    card_caller = _make_model_caller(config, model_configs, "card_writer")
    if not card_caller:
        return

    # ======== Editor note caller ========
    editor_caller = _make_model_caller(config, model_configs, "editor_note")
    if not editor_caller:
        logger.warning("editor_note 模型未配置,将跳过本期看点生成")
        editor_caller = None

    fact_provider = config.get("gate_models", {}).get("fact_extractor", {}).get("provider", "deepseek")
    card_provider = config.get("gate_models", {}).get("card_writer", {}).get("provider", "deepseek")
    editor_provider = config.get("gate_models", {}).get("editor_note", {}).get("provider", "deepseek")

    # Get articles to process. When issue article IDs are provided, keep the
    # card-writing scope pinned to that issue instead of scanning the global pool.
    if article_ids is not None:
        articles = db.get_articles_by_ids(article_ids)[:limit]
    else:
        articles = db.get_gate3_selected(limit=limit)
    if not articles and article_ids is None:
        logger.warning("A/B 精选池为空")

    if not articles:
        logger.error("没有候选文章")
        return

    scope_msg = "指定文章" if article_ids is not None else "A/B精选池"
    logger.info(f"成卡撰写({scope_msg}): {len(articles)} 篇 | fact={fact_provider} card={card_provider} editor={editor_provider}")
    stats = {"success": 0, "fact_fail": 0, "card_fail": 0, "cached": 0, "forbidden_hit": 0, "pending_human": 0, "needs_rewrite": 0}
    all_cards = []  # 收集所有成功卡片供本期看点

    # 并发处理
    def _process_one(idx: int, a: dict, total: int, db: Database):
        """处理单篇文章(仅API调用,不写DB)。返回 (card, local_stats, card_status, reason)."""
        local_stats = {"success": 0, "fact_fail": 0, "card_fail": 0, "cached": 0, "forbidden_hit": 0, "pending_human": 0, "needs_rewrite": 0}
        article_id = a["id"]
        title = (a.get("title") or "")[:60]
        logger.info(f"[{idx+1}/{total}] {title}...")

        # Cache check: skip if already has card_json (unless --force)
        existing_card = a.get("card_json")
        if existing_card and not force:
            local_stats["cached"] += 1
            if existing_card:
                try:
                    card = json.loads(existing_card) if isinstance(existing_card, str) else existing_card
                    date_risk, date_reason = check_card_date_risk(a, card)
                    if date_risk:
                        local_stats["needs_rewrite"] += 1
                        return card, local_stats, "date_risk", date_reason
                    if isinstance(card, dict) and card.get("editor_confidence") == "low":
                        local_stats["needs_rewrite"] += 1
                        return card, local_stats, "needs_rewrite", "editor_confidence_low"
                    return card, local_stats, "ready", ""
                except:
                    pass
            return None, local_stats, "none", "missing_card"

        # Step 1: Fact extraction
        facts = {}
        if fact_caller:
            fact_prompt = build_fact_extract_prompt(a)
            try:
                fact_result = fact_caller.call_model(
                    fact_provider, FACT_EXTRACT_PROMPT, fact_prompt,
                    temperature=0.2, max_tokens=1000, timeout=30
                )
                if fact_result.success and fact_result.data:
                    facts = fact_result.data
                else:
                    logger.warning(f"  事实提取失败: {fact_result.error}, 使用空事实继续")
            except Exception as e:
                logger.warning(f"  事实提取异常: {e}")
                local_stats["fact_fail"] += 1

        # Step 2: Card writing
        try:
            card_prompt = build_card_prompt(a, facts)
            card_result = card_caller.call_model(
                card_provider, CARD_WRITER_PROMPT, card_prompt,
                temperature=0.4, max_tokens=1500, timeout=60
            )

            if not card_result.success or not card_result.data:
                logger.error(f"  成卡撰写失败: {card_result.error}")
                local_stats["card_fail"] += 1
                return None, local_stats, "failed", "card_api_failed"

            card = card_result.data
            card_text = json.dumps(card, ensure_ascii=False)

            # === 输出过滤 1: 内部编号 ===
            internal_hit = INTERNAL_PATTERN.search(card_text)
            if internal_hit:
                logger.warning(f"  ⚠️ 含内部编号: {internal_hit.group()}, 标记卡片待重写")
                local_stats["needs_rewrite"] += 1
                return card, local_stats, "needs_rewrite", "internal_marker"

            # === 输出过滤 2: body长度 ===
            body_len = len(card.get("body", ""))
            if body_len > 150:
                logger.warning(f"  ⚠️ body超长{body_len}字,重试")
                db.log_task_run("card_compress_before", {"article_id": article_id, "field": "body", "before_len": body_len, "before_text": card.get("body", "")}, "")
                compress_instruction = COMPRESS_RETRY_PROMPT.format(field="body", current_len=body_len, max_len=120)
                retry_prompt = compress_instruction + "\n\n" + CARD_WRITER_PROMPT
                retry = card_caller.call_model(card_provider, retry_prompt, card_prompt, temperature=0.6, max_tokens=1500, timeout=60)
                if retry.success and retry.data:
                    card = retry.data
                    new_body_len = len(card.get("body", ""))
                    if new_body_len > 160:
                        card["body"] = _clamp_text_at_boundary(card.get("body", ""), 150, min_len=60)
                        logger.warning(f"  二次重试仍超长({new_body_len}字), 已按句子边界收口并接受")
                    # 成功接受，不转pending_human
                else:
                    logger.warning("  压缩重试API失败, 按句子边界收口原body兜底")
                    card["body"] = _clamp_text_at_boundary(card.get("body", ""), 150, min_len=60)

            dd_len = len(card.get("deep_dive", ""))
            if dd_len > 250:
                logger.warning(f"  ⚠️ deep_dive超长{dd_len}字,重试")
                db.log_task_run("card_compress_before", {"article_id": article_id, "field": "deep_dive", "before_len": dd_len, "before_text": card.get("deep_dive", "")}, "")
                compress_instruction = COMPRESS_RETRY_PROMPT.format(field="deep_dive", current_len=dd_len, max_len=250)
                retry_prompt = compress_instruction + "\n\n" + CARD_WRITER_PROMPT
                retry = card_caller.call_model(card_provider, retry_prompt, card_prompt, temperature=0.6, max_tokens=1500, timeout=60)
                if retry.success and retry.data:
                    card = retry.data
                    if len(card.get("deep_dive", "")) > 250:
                        card["deep_dive"] = _clamp_text_at_boundary(card.get("deep_dive", ""), 250, min_len=120)
                        logger.warning("deep_dive二次重试仍超长, 已按句子边界收口并接受")
                    if len(card.get("body", "")) > 150:
                        card["body"] = _clamp_text_at_boundary(card.get("body", ""), 150, min_len=60)
                        logger.warning("deep_dive重试后body超长, 已按句子边界收口并接受")
                else:
                    logger.warning("deep_dive重试失败, 按句子边界收口原deep_dive兜底")
                    card["deep_dive"] = _clamp_text_at_boundary(card.get("deep_dive", ""), 250, min_len=120)

            # === 示例套用检查 ===
            card_body = card.get("body", "")
            card_dd = card.get("deep_dive", "")
            is_gehry = "盖里" in card_body or "盖里" in card.get("headline", "")
            if not is_gehry:
                for ex in EXAMPLE_TEXTS:
                    lcs_len = _lcs_len(card_body + card_dd, ex)
                    if lcs_len > EXAMPLE_SIMILARITY_THRESHOLD:
                        logger.warning(f"  ⚠️ 疑似套用示例(LCS={lcs_len})")
                        card["editor_confidence"] = "low"
                        break

            # === 人称泄漏检查 ===
            all_text = _card_all_text(card)
            pr_hit = PERSON_REF_PATTERN.search(all_text)
            if pr_hit:
                logger.warning(f"  ⚠️ 人称泄漏: {pr_hit.group()}, 重试")
                pr_instruction = f"上一版中出现了禁用词「{pr_hit.group()}」。请用「读者」替换所有对服务对象的直接称呼。\n\n"
                retry = card_caller.call_model(card_provider, pr_instruction + CARD_WRITER_PROMPT, card_prompt, temperature=0.6, max_tokens=1500, timeout=60)
                if retry.success and retry.data:
                    card = retry.data
                    all_text2 = _card_all_text(card)
                    if PERSON_REF_PATTERN.search(all_text2):
                        logger.warning("重试仍有人称泄漏, 标记卡片待重写")
                        local_stats["needs_rewrite"] += 1
                        return card, local_stats, "needs_rewrite", "person_ref_leak"
                else:
                    local_stats["needs_rewrite"] += 1
                    return card, local_stats, "needs_rewrite", "person_ref_leak"

            # === 违禁词检查 ===
            all_text = _card_all_text(card)
            hard_hits, soft_hits = check_forbidden(all_text)
            if hard_hits:
                logger.warning(f"  ⚠️ 违禁词命中: {hard_hits}, 自动重试一次")
                retry_result = card_caller.call_model(
                    card_provider, CARD_WRITER_PROMPT, card_prompt,
                    temperature=0.6, max_tokens=1500, timeout=60
                )
                if retry_result.success and retry_result.data:
                    card2 = retry_result.data
                    all_text2 = _card_all_text(card2)
                    hard_hits2, soft_hits2 = check_forbidden(all_text2)
                    if soft_hits2:
                        card2["_soft_flags"] = soft_hits2
                    if hard_hits2:
                        logger.warning(f"  ⚠️ 重试仍命中: {hard_hits2}, 标记卡片待重写")
                        local_stats["forbidden_hit"] += 1
                        local_stats["needs_rewrite"] += 1
                        return card2, local_stats, "needs_rewrite", "forbidden_hit"
                    card = card2
                else:
                    logger.warning(f"  重试失败, 标记卡片待重写")
                    local_stats["needs_rewrite"] += 1
                    return card, local_stats, "needs_rewrite", "forbidden_hit"

            # === editor_confidence='low' → 人工复核 ===
            conf = card.get("editor_confidence", "medium")
            if conf == "low":
                logger.info(f"  ⚠️ editor_confidence=low, 标记卡片待重写")
                local_stats["needs_rewrite"] += 1
                return card, local_stats, "needs_rewrite", "editor_confidence_low"

            # === 日期/年份一致性检查 ===
            date_risk, date_reason = check_card_date_risk(a, card, facts)
            if date_risk:
                logger.warning(f"  ⚠️ 日期风险: {date_reason}, 标记卡片待重写")
                local_stats["needs_rewrite"] += 1
                return card, local_stats, "date_risk", date_reason

            # Success!
            local_stats["success"] += 1
            logger.info(f"  ✅ confidence={conf} headline={card.get('headline', '')[:50]}")
            return card, local_stats, "ready", ""

        except Exception as e:
            logger.error(f"  成卡异常: {e}")
            local_stats["card_fail"] += 1
            return None, local_stats, "failed", "card_exception"

        # ============================================================
    # 收集结果 + 串行写库
    # ============================================================
    stats = {"success": 0, "fact_fail": 0, "card_fail": 0, "cached": 0, "forbidden_hit": 0, "pending_human": 0, "needs_rewrite": 0}
    all_cards = []

    def _dispatch(executor, articles):
        """提交所有任务到线程池,按完成顺序收集结果并串行写DB."""
        nonlocal stats, all_cards
        futures = {executor.submit(_process_one, i, a, len(articles), db): i for i, a in enumerate(articles)}
        done_count = 0
        for future in as_completed(futures):
            result = future.result()
            if not result:
                continue
            done_count += 1
            card, ls, card_status, reason = result
            for k in stats:
                stats[k] += ls.get(k, 0)
            if not dry_run:
                _store_card(db, a_id_from_future(futures[future], articles), card, card_status=card_status, reason=reason)
            if card and card_status == "ready":
                all_cards.append(card)
            if progress_callback:
                progress_callback(done_count, len(articles))

    def a_id_from_future(idx, articles):
        return articles[idx]["id"]

    if workers > 1:
        logger.info(f"启动 {workers} 路并发处理 {len(articles)} 篇文章...")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Build future map with article_id for DB writes
            future_map = {}
            for i, a in enumerate(articles):
                future_map[executor.submit(_process_one, i, a, len(articles), db)] = (i, a["id"])
            done_count = 0
            for future in as_completed(future_map):
                result = future.result()
                if not result:
                    continue
                done_count += 1
                card, ls, card_status, reason = result
                for k in stats:
                    stats[k] += ls.get(k, 0)
                aid = future_map[future][1]
                if not dry_run:
                    _store_card(db, aid, card, card_status=card_status, reason=reason)
                if card and card_status == "ready":
                    all_cards.append(card)
                if progress_callback:
                    progress_callback(done_count, len(articles))
    else:
        for i, a in enumerate(articles):
            result = _process_one(i, a, len(articles), db)
            if not result:
                continue
            card, ls, card_status, reason = result
            for k in stats:
                stats[k] += ls.get(k, 0)
            if not dry_run:
                _store_card(db, a["id"], card, card_status=card_status, reason=reason)
            if card and card_status == "ready":
                all_cards.append(card)
            if progress_callback:
                progress_callback(i + 1, len(articles))

    # ============================================================
    # 第三步: 本期看点
    # ============================================================
    editor_note = ""
    if generate_editor_note and all_cards and editor_caller:
        logger.info(f"\n生成本期看点 ({len(all_cards)} 张卡片)...")
        cards_summary = "\n\n---\n\n".join([
            f"标题: {c.get('headline','')}\n推荐语: {c.get('body','')}"
            for j, c in enumerate(all_cards)
        ])
        try:
            note_result = editor_caller.call_model(
                editor_provider, "", 
                EDITOR_NOTE_PROMPT + "\n\n以下是本期全部推荐卡:\n\n" + cards_summary,
                temperature=0.3, max_tokens=300, timeout=30
            )
            if note_result.success and note_result.raw_text:
                editor_note = note_result.raw_text.strip()
                # Check forbidden words in editor note
                hard_fb, soft_fb = check_forbidden(editor_note)
                if hard_fb or soft_fb:
                    logger.warning(f"  本期看点违禁词: {hard_fb}, 重试一次")
                    retry = editor_caller.call_model(
                        editor_provider, "",
                        EDITOR_NOTE_PROMPT + "\n\n以下是本期全部推荐卡:\n\n" + cards_summary,
                        temperature=0.5, max_tokens=300, timeout=30
                    )
                    if retry.success and retry.raw_text:
                        hard_fb2, soft_fb2 = check_forbidden(retry.raw_text.strip())
                        if hard_fb2 or soft_fb2:
                            logger.warning(f"  本期看点重试仍命中: {hard_fb2}, 使用简化版")
                            editor_note = "本周精选全球优质生活体验,涵盖艺术、建筑、科技等多个方向。"
                        else:
                            editor_note = retry.raw_text.strip()
                logger.info(f"  ✅ 本期看点: {editor_note[:80]}...")
            else:
                logger.warning(f"  本期看点生成失败: {note_result.error}")
        except Exception as e:
            logger.error(f"  本期看点异常: {e}")

    # Log final stats
    logger.info(
        f"\n成卡完成: success={stats['success']} cached={stats['cached']} "
        f"fact_fail={stats['fact_fail']} card_fail={stats['card_fail']} "
        f"forbidden_hit={stats['forbidden_hit']} pending_human={stats['pending_human']} "
        f"needs_rewrite={stats['needs_rewrite']}"
    )
        # Save editor_note to sidecar file for report generator
    if generate_editor_note and editor_note:
        out_dir = Path(config.get("report", {}).get("output_dir", "output"))
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "editor_note.txt").write_text(editor_note, encoding="utf-8")
        logger.info(f"本期看点已保存到 {out_dir / 'editor_note.txt'}")

    return stats, editor_note, all_cards

def _store_card(db: Database, article_id: int, card: dict | None, card_status: str = "ready", reason: str = ""):
    """Store card JSON and related fields to DB"""
    facts_used = card.get("facts_used", []) if isinstance(card, dict) else []
    if not isinstance(facts_used, list):
        facts_used = []

    updates = {
        "card_status": card_status,
        "card_review_reason": reason or None,
        "card_updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "card_attempt_count": int((db.get_article(article_id) or {}).get("card_attempt_count") or 0) + (0 if card_status == "ready" and reason == "" else 1),
    }
    if isinstance(card, dict):
        updates.update({
            "card_json": json.dumps(card, ensure_ascii=False),
            "summary": card.get("body", ""),
            "scenario": card.get("arrangement", ""),
            "pros": json.dumps(card.get("cautions", []), ensure_ascii=False),
            "cons": json.dumps(card.get("fit_reasons", []), ensure_ascii=False),
            "recommend_reason": json.dumps(card, ensure_ascii=False),
            "recommend_level": card.get("editor_confidence", "medium"),
            "facts_used": json.dumps(facts_used, ensure_ascii=False),
        })

    db.update_article(article_id, updates)

def _run_editor_only(args):
    """Regenerate editor note only from existing card_json — does NOT touch any card."""
    import json as _json
    from pathlib import Path as _Path
    config = load_config()
    db = Database(config["database"]["path"])
    articles = db.get_gate3_selected(limit=args.limit)
    if not articles:
        logger.info("A/B featured pool is empty, nothing to do")
        return
    
    # Load existing card_json only
    all_cards = []
    skipped = 0
    for a in articles:
        cjs = a.get("card_json", "")
        card = {}
        if isinstance(cjs, str) and cjs:
            try: card = _json.loads(cjs)
            except: pass
        if card:
            all_cards.append(card)
        else:
            skipped += 1
    
    logger.info(f"Loaded {len(all_cards)} existing cards (skipped {skipped} without card_json)")
    if not all_cards:
        logger.info("No existing cards found")
        return
    
    # Generate editor note
    model_configs = load_model_configs(config)
    editor_caller = _make_model_caller(config, model_configs, "editor_note")
    if not editor_caller:
        logger.warning("editor_note model not configured, cannot generate")
        return
    
    editor_provider = config.get("gate_models", {}).get("editor_note", {}).get("provider", "deepseek")
    cards_summary = "\n\n---\n\n".join([
        f"标题: {c.get('headline','')}\n推荐语: {c.get('body','')}"
        for c in all_cards
    ])
    
    logger.info(f"Generating editor note with {editor_provider}...")
    try:
        note_result = editor_caller.call_model(
            editor_provider, "", 
            EDITOR_NOTE_PROMPT + "\n\n以下是本期全部推荐卡:\n\n" + cards_summary,
            temperature=0.3, max_tokens=300, timeout=30
        )
        if note_result.success and note_result.raw_text:
            editor_note = note_result.raw_text.strip()
            # Check forbidden + internal patterns
            hard_fb, soft_fb = check_forbidden(editor_note)
            if hard_fb or soft_fb:
                logger.warning(f"Editor note forbidden: {hard_fb}, retrying once")
                retry = editor_caller.call_model(
                    editor_provider, "",
                    EDITOR_NOTE_PROMPT + "\n\n以下是本期全部推荐卡:\n\n" + cards_summary,
                    temperature=0.5, max_tokens=300, timeout=30
                )
                if retry.success and retry.raw_text:
                    hard_fb2, soft_fb2 = check_forbidden(retry.raw_text.strip())
                    if hard_fb2 or soft_fb2:
                        logger.warning("Editor note retry still hits forbidden, using fallback")
                        editor_note = "本周精选全球优质生活体验，涵盖艺术、建筑、科技等多个方向。"
                    else:
                        editor_note = retry.raw_text.strip()
            
            logger.info(f"Editor note OK: {editor_note[:80]}...")
            
            # Save to sidecar file
            out_dir = _Path(config.get("report", {}).get("output_dir", "output"))
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "editor_note.txt").write_text(editor_note, encoding="utf-8")
            logger.info(f"Editor note saved to {out_dir / 'editor_note.txt'}")
        else:
            logger.error(f"Editor note generation failed: {note_result.error}")
    except Exception as e:
        logger.error(f"Editor note exception: {e}")
        import traceback
        traceback.print_exc()


def generate_editor_note_for_articles(articles: list[dict], config=None, issue_id: int = 0) -> str:
    """Generate editor note from a SPECIFIC set of articles (scoped to one issue).
    
    Unlike run_card_generation which queries the global featured pool,
    this takes an explicit article list — so the LLM only sees cards from the intended issue.
    Returns empty string on failure.
    """
    import json as _json
    from pathlib import Path as _Path
    
    if not articles:
        logger.warning("generate_editor_note_for_articles: no articles provided")
        return ""
    
    if config is None:
        config = load_config()
    
    model_configs = load_model_configs(config)
    editor_caller = _make_model_caller(config, model_configs, "editor_note")
    if not editor_caller:
        logger.warning("editor_note model not configured, cannot generate scoped note")
        return ""
    
    editor_provider = config.get("gate_models", {}).get("editor_note", {}).get("provider", "deepseek")
    
    # Build cards_summary from ONLY these articles' card_json
    all_cards = []
    skipped = 0
    for a in articles:
        cjs = a.get("card_json", "")
        card = {}
        if isinstance(cjs, str) and cjs:
            try:
                card = _json.loads(cjs)
            except:
                pass
        if card and card.get("body"):
            all_cards.append(card)
        else:
            skipped += 1
    
    if skipped:
        logger.info(f"  Scoped editor note: {skipped}/{len(articles)} articles lack card_json, using {len(all_cards)}")
    
    if not all_cards:
        logger.warning("Scoped editor note: no articles with valid card_json")
        return ""
    
    cards_summary = "\n\n---\n\n".join([
        f"标题: {c.get('headline','')}\n推荐语: {c.get('body','')}"
        for c in all_cards
    ])
    
    logger.info(f"Generating scoped editor note ({len(all_cards)} cards, issue_id={issue_id})...")
    try:
        note_result = editor_caller.call_model(
            editor_provider, "",
            EDITOR_NOTE_PROMPT + "\n\n以下是本期全部推荐卡:\n\n" + cards_summary,
            temperature=0.3, max_tokens=300, timeout=30
        )
        if note_result.success and note_result.raw_text:
            editor_note = note_result.raw_text.strip()
            hard_fb, soft_fb = check_forbidden(editor_note)
            if hard_fb or soft_fb:
                logger.warning(f"  Scoped editor note forbidden: {hard_fb}, retrying once")
                retry = editor_caller.call_model(
                    editor_provider, "",
                    EDITOR_NOTE_PROMPT + "\n\n以下是本期全部推荐卡:\n\n" + cards_summary,
                    temperature=0.5, max_tokens=300, timeout=30
                )
                if retry.success and retry.raw_text:
                    hard_fb2, soft_fb2 = check_forbidden(retry.raw_text.strip())
                    if hard_fb2 or soft_fb2:
                        logger.warning("Scoped editor note retry still hits forbidden, using fallback")
                        editor_note = "本周精选全球优质生活体验，涵盖艺术、建筑、科技等多个方向。"
                    else:
                        editor_note = retry.raw_text.strip()
            
            logger.info(f"  ✅ Scoped editor note: {editor_note[:80]}...")
            return editor_note
        else:
            logger.error(f"Scoped editor note generation failed: {note_result.error}")
            return ""
    except Exception as e:
        logger.error(f"Scoped editor note exception: {e}")
        return ""


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="成卡撰写 — 两步生成链路 v3")
    parser.add_argument("--limit", type=int, default=35, help="最大文章数")
    parser.add_argument("--dry-run", action="store_true", help="仅测试不写库")
    parser.add_argument("--force", action="store_true", help="强制重新生成(忽略缓存)")
    parser.add_argument("--editor-only", action="store_true", help="仅从已有卡片重新生成本期看点(不触碰card_json)")
    parser.add_argument("--workers", type=int, default=1, help="并发线程数(默认1)")
    parser.add_argument("--article-ids", type=str, default="", help="逗号分隔的文章ID列表；提供后只处理这些文章")
    args = parser.parse_args()
    if args.editor_only:
        _run_editor_only(args)
    else:
        article_ids = [int(x) for x in args.article_ids.split(",") if x.strip()] if args.article_ids else None
        run_card_generation(limit=args.limit, dry_run=args.dry_run, force=args.force, workers=args.workers, article_ids=article_ids)
