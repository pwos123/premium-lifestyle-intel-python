#!/usr/bin/env python3
"""
第一关:硬性闸门(pass/fail)
逐条检查600篇文章,任何一项不通过即fail
模型:最便宜的模型(qwen-turbo)
"""

import sys, json, logging, time, argparse
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.config import load_config, load_model_configs
from prompts.gate1_pass_fail import GATE1_SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gate1")

CURRENT_DATE = date.today().isoformat()




def build_gate1_prompt(a: dict) -> str:
    images = a.get("images", [])
    if isinstance(images, str):
        try: images = json.loads(images)
        except: images = []
    first_image = images[0] if images else "无"

    return f"""请检查以下文章:

article_id: {a['id']}
标题: {a.get('title', '')}
英文原题: {a.get('translated_title', '') or a.get('title', '')}
摘要: {a.get('summary', '')}
正文开头: {(a.get('content', '') or '')[:500]}
配图URL列表首图: {first_image}
信源: {a.get('source', '')}
频道: {a.get('category', '')}

    请按照系统提示中的 JSON 格式输出检查结果。"""


def build_gate1_system_prompt() -> str:
    return GATE1_SYSTEM_PROMPT.format(current_date=CURRENT_DATE)


def run_gate1(limit: int = 600, dry_run: bool = False):
    config = load_config()
    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    # 使用gate1指定的模型
    gate_cfg = config.get("gate_models", {}).get("gate1", {})
    provider = gate_cfg.get("provider", "qwen")
    model_override = gate_cfg.get("model_override")

    if provider not in model_configs:
        logger.error(f"Gate1 provider '{provider}' 未配置 API Key")
        return

    mc = model_configs[provider]
    if model_override:
        mc = ModelConfig(name=mc.name, api_key=mc.api_key, base_url=mc.base_url, model=model_override, weight=mc.weight)

    caller = LLMCaller({provider: mc})
    if not caller.available_models:
        logger.error(f"Gate1 模型 {provider}/{mc.model} 不可用")
        return

    articles = db.get_gate1_candidates(limit=limit)
    logger.info(f"Gate1 待检查: {len(articles)} 篇")

    stats = {"pass": 0, "fail": 0, "needs_human": 0, "error": 0}

    for i, a in enumerate(articles):
        article_id = a["id"]
        title = (a.get("title") or "")[:60]
        logger.info(f"[{i+1}/{len(articles)}] {title}...")

        try:
            prompt = build_gate1_prompt(a)
            result = caller.call_model(provider, build_gate1_system_prompt(), prompt, temperature=0.2, max_tokens=800, timeout=30)

            if not result.success or not result.data:
                stats["error"] += 1
                logger.warning(f"  Gate1 调用失败: {result.error}")
                continue

            data = result.data
            # 校验回显
            if str(data.get("article_id")) != str(article_id):
                logger.warning(f"  article_id 不一致! 输入={article_id} 回显={data.get('article_id')}, 丢弃结果")
                stats["error"] += 1
                continue

            verdict = data.get("verdict", "fail")
            failed = data.get("failed_checks", [])
            needs_human = data.get("needs_human", False)

            if not dry_run:
                db.set_gate1_result(article_id, verdict, failed, needs_human)
                if verdict == "fail":
                    db.auto_archive(article_id, "质检未通过", archive_type="archived")

            if verdict == "pass":
                stats["pass"] += 1
                logger.info(f"  ✅ PASS")
            else:
                stats["fail"] += 1
                logger.info(f"  ❌ FAIL: {failed}")

            if needs_human:
                stats["needs_human"] += 1

        except Exception as e:
            stats["error"] += 1
            logger.error(f"  EXCEPTION: {e}")

        time.sleep(0.3)  # 便宜模型rate limit宽松

    logger.info(f"Gate1 完成: pass={stats['pass']} fail={stats['fail']} needs_human={stats['needs_human']} error={stats['error']}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="第一关:硬性闸门 pass/fail")
    parser.add_argument("--limit", type=int, default=600, help="最大处理数")
    parser.add_argument("--dry-run", action="store_true", help="仅测试不写库")
    args = parser.parse_args()
    run_gate1(limit=args.limit, dry_run=args.dry_run)
