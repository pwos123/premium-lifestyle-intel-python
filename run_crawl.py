#!/usr/bin/env python3
"""
抓取入口 — 抓取网站 → 快速分析（单模型） → 存入数据库
深度分析留给人工筛选之后
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.crawler import Crawler
from src.quick_analyzer import QuickAnalyzer
from src.database import Database, _normalize_url
from src.config import load_config, load_model_configs
from src.category_classifier import correct_category
from services.image_merge import merge_article_images, parse_image_list

# 日志: 优先写入 /data/output (Fly.io volume), 回退到本地 data/
_handlers = [logging.StreamHandler()]
for _log_dir in [Path("/data/output"), Path("data")]:
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        _log_path = _log_dir / "crawl.log"
        _log_path.touch()
        _handlers.append(logging.FileHandler(str(_log_path), encoding="utf-8"))
        break
    except Exception:
        continue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)


def load_sites(filter_name: str = None):
    sites_path = Path(__file__).parent / "config" / "sites.yaml"
    with open(sites_path, encoding="utf-8") as f:
        import yaml
        data = yaml.safe_load(f)
    sites = data.get("sites", [])
    if filter_name:
        sites = [s for s in sites if filter_name.lower() in s["name"].lower()]
    return sites


async def run_crawl(sites: list[dict], config: dict, dry_run: bool = False):
    db = Database(config["database"]["path"])
    crawler_cfg = config.get("crawler", {})

    crawler = Crawler(
        max_concurrent=crawler_cfg.get("max_concurrent", 5),
        max_articles_per_site=crawler_cfg.get("max_articles_per_site", 10),
        request_timeout=crawler_cfg.get("request_timeout", 30),
        retry_count=crawler_cfg.get("retry_count", 3),
        user_agents=crawler_cfg.get("user_agents"),
        image_cache_dir=config.get("images", {}).get("cache_dir", "static/images"),
        max_image_concurrent=crawler_cfg.get("max_image_concurrent", 3),
        max_site_concurrent=crawler_cfg.get("max_site_concurrent", 4),
        site_timeout=crawler_cfg.get("site_timeout", 180),
        max_images_per_article=crawler_cfg.get("max_images_per_article", 5),
        min_host_interval=crawler_cfg.get("min_host_interval", 0.25),
        rss_enrich_min_content_chars=crawler_cfg.get("rss_enrich_min_content_chars", 600),
    )

    # 快速分析默认保持开启；可用配置显式关闭以只做网络采集。
    quick_enabled = crawler_cfg.get("quick_analysis_enabled", True)
    quick = QuickAnalyzer(load_model_configs(config)) if quick_enabled else None

    logger.info("=" * 50)
    logger.info("开始每日抓取（快速分析模式）")
    logger.info(f"目标网站: {len(sites)} 个")

    new_count = 0
    skip_count = 0
    total_count = 0
    min_score = config.get("ai", {}).get("min_score", 60)
    featured_count = 0
    image_missing_count = 0
    min_content_chars = max(50, int(crawler_cfg.get("min_content_chars", 200)))
    require_images = crawler_cfg.get("require_images", False)

    async for article in crawler.crawl_all_streaming(sites):
        total_count += 1
        url = article.get("url", "")
        url = _normalize_url(url)
        article["url"] = url
        existing = db.get_article_by_url(url)
        if existing:
            merged_images = merge_article_images(
                existing.get("images"),
                article.get("images"),
                max_images=max(crawler.max_images_per_article * 3, crawler.max_images_per_article),
            )
            if len(merged_images) > len(parse_image_list(existing.get("images"))):
                db.update_article(existing["id"], {"images": merged_images})
                logger.info(
                    "  已存在，补充图片: #%s %s → %s",
                    existing["id"],
                    len(parse_image_list(existing.get("images"))),
                    len(merged_images),
                )
            skip_count += 1
            continue

        # 质量过滤：内容太短的文章跳过
        content_text = article.get("content", "")
        if len(content_text) < min_content_chars:
            logger.info(f"  内容过短({len(content_text)}字，需≥{min_content_chars})，跳过")
            skip_count += 1
            continue

        if require_images and not article.get("images"):
            logger.info("  未下载到有效配图，跳过并保留到下次重试")
            skip_count += 1
            image_missing_count += 1
            continue

        logger.info(f"[{total_count}] 快速分析: {article['title'][:50]}...")

        if dry_run:
            logger.info("  [DRY RUN] 跳过")
            continue

        analysis = {
            "is_relevant": True,
            "category": article.get("category_hint", ""),
            "quick_score": 50,
            "quick_reason": "",
        }
        if quick:
            try:
                analysis = await asyncio.wait_for(
                    asyncio.to_thread(
                        quick.analyze,
                        title=article["title"],
                        content=article.get("content", ""),
                        source=article.get("source", ""),
                    ),
                    timeout=crawler_cfg.get("quick_analysis_timeout", 45),
                )
            except Exception as e:
                logger.error(f"  快速分析失败: {e}")

        final_category, category_reason = correct_category(
            title=article["title"],
            content=article.get("content", ""),
            source=article.get("source", ""),
            category_hint=article.get("category_hint", ""),
            ai_category=analysis.get("category", ""),
        )

        article_data = {
            "url": url,
            "title": article["title"],
            "translated_title": analysis.get("translated_title", ""),
            "translated_content": analysis.get("translated_content", ""),
            "source": article.get("source", ""),
            "content": article.get("content", "")[:8000],
            "summary": analysis.get("quick_reason", ""),
            "images": article.get("images", []),
            "category": final_category,
            "score": analysis.get("quick_score", 50),
            "tags": [],
            "recommend_reason": analysis.get("quick_reason", ""),
            "scenario": "",
            "pros": [],
            "cons": [],
            "recommend_level": "待定",
            "is_relevant": 1 if analysis.get("is_relevant", True) else 0,
            "model_votes": {},
            "status": "pending",
        }

        article_id = db.insert_article(article_data)
        if article_id:
            new_count += 1
            if article_data.get("score", 0) >= min_score and analysis.get("is_relevant", True):
                featured_count += 1
            logger.info(f"  入库 #{article_id} | {article_data.get('score',50)}分 | {article_data.get('category','')} ({category_reason})")
        else:
            skip_count += 1

    stats = db.get_stats()
    logger.info("=" * 50)
    logger.info(f"抓取完成: 处理 {total_count} | 新增 {new_count} | 精选 {featured_count} | 跳过 {skip_count} | 缺图 {image_missing_count}")
    logger.info(f"数据库: 总计 {stats['total']} | 待审核 {stats['pending']} | 已通过 {stats['approved']}")
    logger.info("=" * 50)
    logger.info("下一步: python run_review.py 打开审核页面")


def main():
    parser = argparse.ArgumentParser(description="每日抓取（快速分析）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--site", type=str, help="只抓取指定网站")
    args = parser.parse_args()

    config = load_config()
    sites = load_sites(args.site)
    if not sites:
        logger.error("没有找到匹配的网站")
        return
    asyncio.run(run_crawl(sites, config, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
