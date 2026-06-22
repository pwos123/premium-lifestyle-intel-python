#!/usr/bin/env python3
"""
第三关:小组赛排位(比较制,代替打分)
按频道分组,组内比较选出2-3条,落选即淘汰
模型:强模型,只跑A/B档
"""

import sys, json, logging, time, argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.config import load_config, load_model_configs
from prompts.gate3_group_match import GATE3_SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gate3")




def build_group_prompt(candidates: list[dict]) -> str:
    lines = [f"同一频道的 {len(candidates)} 条候选内容,请选出最值得进入本周菜单的2-3条:\n"]
    for i, c in enumerate(candidates):
        lines.append(f"--- 候选 {i+1} ---")
        lines.append(f"article_id: {c['id']}")
        lines.append(f"标题: {c.get('title', '')}")
        lines.append(f"一句话钩子: {c.get('gate2_one_line', '')}")
        lines.append(f"兴奋点标签: {json.dumps(c.get('gate2_fit_reasons', []), ensure_ascii=False)}")
        lines.append(f"摘要: {(c.get('summary', '') or '')[:200]}")
        lines.append(f"频道: {c.get('category', '')}")
        lines.append(f"信源: {c.get('source', '')}")
        lines.append("")
    return "\n".join(lines)



def _handle_regroup(db, article, config, dry_run, stats, logger):
    """重赛计数与上限检查: 达到上限后转入沉库"""
    regroup_limit = config.get("throttle", {}).get("regroup_limit", 1)
    current_count = (article.get("regroup_count") or 0) + 1
    if not dry_run:
        db.update_article(article["id"], {"regroup_count": current_count})
    
    if current_count > regroup_limit:
        logger.info(f"  💤 重赛{current_count}次(上限{regroup_limit}), 转入沉库")
        if not dry_run:
            db.auto_archive(article["id"], "小组赛两败", archive_type="sunk")
        stats.setdefault("sunk", 0)
        stats["sunk"] += 1


def run_gate3(limit: int = 100, dry_run: bool = False):
    config = load_config()

    # GATE3_PASSTHROUGH: A/B 直通, 不淘汰不沉库
    gate3_passthrough = config.get("throttle", {}).get("gate3_passthrough", False)
    if gate3_passthrough:
        logger.info("GATE3_PASSTHROUGH=ON — A/B 全部直通 candidate, 不淘汰不沉库")
        db = Database(config["database"]["path"])
        candidates = db.get_gate3_candidates(limit=limit)
        logger.info(f"Gate3 候选: {len(candidates)} 篇 (A/B档) — 全部直通")
        passed = 0
        for c in candidates:
            if not dry_run:
                db.set_gate3_result(
                    c["id"], 1, "直通模式,自动入选",
                    c.get("category") or "未分类", True, "selected"
                )
                db.update_article(c["id"], {"regroup_count": 0})
            passed += 1
        if not dry_run:
            pass  # Database has no close(), conns are per-operation
        logger.info(f"Gate3 直通完成: passed={passed} eliminated=0 sunk=0")
        return {"selected": passed, "eliminated": 0, "eliminated_notable": 0, "sunk": 0, "error": 0}

    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    gate_cfg = config.get("gate_models", {}).get("gate3", {})
    provider = gate_cfg.get("provider", "deepseek")
    model_override = gate_cfg.get("model_override")

    if provider not in model_configs:
        logger.error(f"Gate3 provider '{provider}' 未配置 API Key")
        return

    mc = model_configs[provider]
    if model_override:
        mc = ModelConfig(name=mc.name, api_key=mc.api_key, base_url=mc.base_url, model=model_override, weight=mc.weight)

    caller = LLMCaller({provider: mc})
    if not caller.available_models:
        logger.error(f"Gate3 模型 {provider}/{mc.model} 不可用")
        return

    candidates = db.get_gate3_candidates(limit=limit)
    logger.info(f"Gate3 候选: {len(candidates)} 篇 (A/B档)")

    # 按频道分组,A档优先
    gate3_cfg = config.get("gates", {}).get("gate3", {})
    max_per_group = gate3_cfg.get("candidates_per_group", 10)

    groups: dict[str, list[dict]] = defaultdict(list)
    # 先放A档
    for c in sorted(candidates, key=lambda x: (x.get("gate2_tier", "Z"), -(x.get("score") or 0))):
        cat = c.get("category") or "未分类"
        if len(groups[cat]) < max_per_group:
            groups[cat].append(c)

    logger.info(f"分组: {len(groups)} 个频道")
    for cat, g in groups.items():
        logger.info(f"  {cat}: {len(g)} 条")

    stats = {"selected": 0, "eliminated": 0, "eliminated_notable": 0, "sunk": 0, "error": 0}

    for cat, group in groups.items():
        if len(group) < 2:
            # 单条自动入选
            c = group[0]
            if not dry_run:
                db.set_gate3_result(c["id"], 1, "组内唯一候选,自动入选", cat, True, "selected")
                db.update_article(c["id"], {"regroup_count": 0})
            stats["selected"] += 1
            logger.info(f"  [{cat}] 仅1条,自动入选: {(c.get('title') or '')[:40]}")
            continue

        logger.info(f"\n=== {cat} 小组赛 ({len(group)} 条) ===")

        try:
            prompt = build_group_prompt(group)
            result = caller.call_model(provider, GATE3_SYSTEM_PROMPT, prompt, temperature=0.3, max_tokens=4000, timeout=120)

            if not result.success or not result.data:
                logger.warning(f"  Gate3 调用失败: {result.error}, 全组保留为候补")
                for c in group:
                    if not dry_run:
                        db.set_gate3_result(c["id"], 0, "小组赛调用失败,保留候补", cat, False, "eliminated_notable")
                stats["error"] += len(group)
                continue

            data = result.data
            selected = data.get("selected", [])
            eliminated_notable = data.get("eliminated_notable", [])

            selected_ids = {str(s["article_id"]) for s in selected}
            notable_ids = {str(e["article_id"]) for e in eliminated_notable}

            for c in group:
                aid = str(c["id"])
                if aid in selected_ids:
                    sel = next(s for s in selected if str(s["article_id"]) == aid)
                    if not dry_run:
                        # 入选时重置 regroup_count
                        db.set_gate3_result(c["id"], sel.get("rank", 1), sel.get("rationale", ""), cat, True, "selected")
                        db.update_article(c["id"], {"regroup_count": 0})
                    # 过滤: rationale 含内部编号则标记待人工
                    r_text = sel.get("rationale", "")
                    import re as _re
                    if _re.search(r'(候选\d+|article[_\-]?id|#\d+|[ABCD]档)', r_text, _re.IGNORECASE):
                        logger.warning(f"  ⚠️ rationale含内部编号, 标记待人工: {r_text[:60]}")
                        if not dry_run:
                            db.update_article(c["id"], {"pending_human": 1})
                    
                    stats["selected"] += 1
                    logger.info(f"  ⭐ 入选 #{sel.get('rank',1)}: {(c.get('title') or '')[:40]}")
                elif aid in notable_ids:
                    ent = next(e for e in eliminated_notable if str(e["article_id"]) == aid)
                    if not dry_run:
                        db.set_gate3_result(c["id"], 0, ent.get("reason", ""), cat, False, "eliminated_notable")
                    # 重赛计数与上限检查
                    _handle_regroup(db, c, config, dry_run, stats, logger)
                    stats["eliminated_notable"] += 1
                    logger.info(f"  📌 差一点: {(c.get('title') or '')[:40]}")
                else:
                    if not dry_run:
                        db.set_gate3_result(c["id"], 0, "小组赛淘汰", cat, False, "eliminated")
                    # 重赛计数与上限检查
                    _handle_regroup(db, c, config, dry_run, stats, logger)
                    stats["eliminated"] += 1

        except Exception as e:
            logger.error(f"  EXCEPTION: {e}")
            stats["error"] += len(group)

        time.sleep(1)

    logger.info(f"\nGate3 完成: selected={stats['selected']} eliminated={stats['eliminated']} eliminated_notable={stats['eliminated_notable']} sunk={stats.get('sunk',0)} error={stats['error']}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="第三关:小组赛排位")
    parser.add_argument("--limit", type=int, default=100, help="最大候选数")
    parser.add_argument("--dry-run", action="store_true", help="仅测试不写库")
    args = parser.parse_args()
    run_gate3(limit=args.limit, dry_run=args.dry_run)
