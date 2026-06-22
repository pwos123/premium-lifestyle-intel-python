#!/usr/bin/env python3
"""
第二关:DJ适配分级(A/B/C/D档)
跑第一关pass的~200条,中档模型
不输出0-100总分,改为分维度评级+总档位
"""

import sys, json, logging, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.config import load_config, load_model_configs
from prompts.gate2_dj_tier import GATE2_SYSTEM_PROMPT, check_fit_forbidden

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gate2")




def build_gate2_prompt(a: dict) -> str:
    content = a.get("content") or ""
    if len(content) > 1500:
        content = content[:1500] + "..."

    return f"""请分析以下内容:

article_id: {a['id']}
标题: {a.get('title', '')}
摘要: {a.get('summary', '')}
正文: {content}
频道: {a.get('category', '')}
信源: {a.get('source', '')}

请按照系统提示中的 JSON 格式输出分析结果。"""


def determine_tier(data: dict) -> str:
    """根据规则计算档位,同时也信任模型自己的判断"""
    d1 = data.get("dim_excitement", 0)
    d2 = data.get("dim_feasibility", 0)
    d3 = data.get("dim_density", 0)
    total = d1 + d2 + d3

    if total <= 2:
        return "D"
    if d1 >= 2 and total >= 7:
        return "A"
    if d1 >= 1 and total >= 5:
        return "B"
    return "C"


def run_gate2(limit: int = 300, dry_run: bool = False, retry_errors: bool = False, max_attempts: int = 3):
    config = load_config()
    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    gate_cfg = config.get("gate_models", {}).get("gate2", {})
    provider = gate_cfg.get("provider", "deepseek")
    model_override = gate_cfg.get("model_override")

    if provider not in model_configs:
        logger.error(f"Gate2 provider '{provider}' 未配置 API Key")
        return

    mc = model_configs[provider]
    if model_override:
        mc = ModelConfig(name=mc.name, api_key=mc.api_key, base_url=mc.base_url, model=model_override, weight=mc.weight)

    caller = LLMCaller({provider: mc})
    if not caller.available_models:
        logger.error(f"Gate2 模型 {provider}/{mc.model} 不可用")
        return

    if retry_errors:
        articles = db.get_gate2_error_candidates(limit=limit, max_attempts=max_attempts)
        logger.info(f"Gate2 错误重试: {len(articles)} 篇")
    else:
        articles = db.get_gate2_candidates(limit=limit)
        logger.info(f"Gate2 待分级: {len(articles)} 篇")

    stats = {"A": 0, "B": 0, "C": 0, "D": 0, "error": 0}

    for i, a in enumerate(articles):
        article_id = a["id"]
        title = (a.get("title") or "")[:50]
        logger.info(f"[{i+1}/{len(articles)}] {title}...")

        try:
            prompt = build_gate2_prompt(a)
            result = caller.call_model(provider, GATE2_SYSTEM_PROMPT, prompt, temperature=0.3, max_tokens=1200, timeout=60)

            if not result.success or not result.data:
                stats["error"] += 1
                err = result.error or "模型返回为空或 JSON 解析失败"
                logger.warning(f"  Gate2 调用失败: {err}")
                if not dry_run:
                    db.set_gate2_error(article_id, err)
                continue

            data = result.data
            if str(data.get("article_id")) != str(article_id):
                logger.warning(f"  article_id 不一致! 丢弃结果")
                stats["error"] += 1
                if not dry_run:
                    db.set_gate2_error(article_id, f"article_id 不一致: 输入={article_id} 回显={data.get('article_id')}")
                continue

            tier = data.get("tier", determine_tier(data))
            # 双重校验:模型可能把该给A的给了B
            computed_tier = determine_tier(data)
            if computed_tier != tier:
                logger.info(f"  档位修正: 模型={tier} 规则={computed_tier}")
                tier = computed_tier

            veto = data.get("veto") or ""
            dims = (data.get("dim_excitement", 0), data.get("dim_feasibility", 0), data.get("dim_density", 0))
            fit_reasons = data.get("fit_reasons", [])
            one_line = data.get("one_line", "")

            if not dry_run:
                db.set_gate2_result(article_id, tier, veto if veto != "null" else "", dims, fit_reasons, one_line)
                if tier == "D":
                    db.auto_archive(article_id, "D档淘汰", archive_type="archived")
                elif veto and veto.strip() and veto != "null":
                    db.auto_archive(article_id, f"否决: {veto[:50]}", archive_type="archived")

            # === fit_reasons 禁区词校验 ===
            hit_keywords = check_fit_forbidden(fit_reasons, a.get("category", ""))
            if hit_keywords:
                # fit_reasons 含禁区词 → 强制待人工,不自动进入第三关
                if not dry_run:
                    db.set_gate2_result(article_id, tier, f"fit_reasons含禁区词: {','.join(hit_keywords)}", dims, fit_reasons, one_line)
                    db.update_article(article_id, {
                        "fit_keywords_hit": json.dumps(hit_keywords, ensure_ascii=False),
                        "pending_human": 1,
                        "gate3_status": "pending_human",
                    })
                logger.warning(f"  ⚠️ fit_reasons含禁区词 {hit_keywords}, 强制待人工")
                continue
            
            stats[tier] = stats.get(tier, 0) + 1
            logger.info(f"  {tier}档 d1={dims[0]} d2={dims[1]} d3={dims[2]} veto={veto[:30] if veto else '-'}")

        except Exception as e:
            stats["error"] += 1
            logger.error(f"  EXCEPTION: {e}")
            if not dry_run:
                db.set_gate2_error(article_id, str(e))

        time.sleep(0.5)

    logger.info(f"Gate2 完成: A={stats['A']} B={stats['B']} C={stats['C']} D={stats['D']} error={stats['error']}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="第二关:DJ适配分级 A/B/C/D")
    parser.add_argument("--limit", type=int, default=300, help="最大处理数")
    parser.add_argument("--dry-run", action="store_true", help="仅测试不写库")
    parser.add_argument("--retry-errors", action="store_true", help="只重试 Gate2 JSON/调用失败残留")
    parser.add_argument("--max-attempts", type=int, default=3, help="错误残留最大尝试次数")
    args = parser.parse_args()
    run_gate2(limit=args.limit, dry_run=args.dry_run, retry_errors=args.retry_errors, max_attempts=args.max_attempts)
