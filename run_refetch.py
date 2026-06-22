#!/usr/bin/env python3
"""
补齐缺失内容 — 重新抓取内容过短或缺少图片的文章
用法: python run_refetch.py [--min-content 200] [--dry-run]
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from src.crawler import Crawler
from src.database import Database
from services.image_merge import merge_article_images, parse_image_list

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sites():
    sites_path = Path(__file__).parent / "config" / "sites.yaml"
    with open(sites_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sites", [])


def get_selector_for_url(url: str, sites: list[dict]) -> dict:
    """根据 URL 找到对应网站的选择器配置"""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    for site in sites:
        site_domain = urlparse(site["url"]).netloc.lower()
        if site_domain in domain or domain in site_domain:
            return site.get("selectors", {})
    return {}


async def refetch_articles(articles: list[dict], sites: list[dict], config: dict, dry_run: bool = False):
    crawler_cfg = config.get("crawler", {})
    crawler = Crawler(
        max_concurrent=3,
        request_timeout=crawler_cfg.get("request_timeout", 30),
        retry_count=crawler_cfg.get("retry_count", 3),
        user_agents=crawler_cfg.get("user_agents"),
        image_cache_dir=config.get("images", {}).get("cache_dir", "static/images"),
        max_images_per_article=crawler_cfg.get("max_images_per_article", 5),
    )

    db = Database(config["database"]["path"])
    success = 0
    fail = 0

    for i, article in enumerate(articles):
        url = article["url"]
        title = article["title"][:50]
        content_len = len(article.get("content", "") or "")
        current_images = parse_image_list(article.get("images"))
        has_images = bool(current_images)

        logger.info(f"[{i+1}/{len(articles)}] 重抓: {title}... (内容:{content_len}字, 图片:{'有' if has_images else '无'})")

        if dry_run:
            continue

        selectors = get_selector_for_url(url, sites)
        result = await crawler.refetch_single(url, selectors)

        if not result:
            logger.warning(f"  ❌ 抓取失败")
            fail += 1
            continue

        updates = {}
        new_content = result.get("content", "")
        new_images = result.get("images", [])

        if new_content and len(new_content) > content_len:
            updates["content"] = new_content[:8000]
            logger.info(f"  📝 内容: {content_len} → {len(new_content)} 字")

        if new_images:
            merged_images = merge_article_images(
                current_images,
                new_images,
                max_images=max(crawler.max_images_per_article * 3, crawler.max_images_per_article),
            )
            if len(merged_images) > len(current_images):
                updates["images"] = merged_images
                logger.info(f"  🖼️ 图片: {len(current_images)} → {len(merged_images)} 张")

        if updates:
            db.update_article(article["id"], updates)
            success += 1
            logger.info(f"  ✅ 已更新")
        else:
            logger.info(f"  ⏭️ 无改善，跳过")
            fail += 1

    logger.info(f"补齐完成: 成功 {success} | 未改善/失败 {fail}")


def main():
    parser = argparse.ArgumentParser(description="补齐缺失内容和图片")
    parser.add_argument("--min-content", type=int, default=200, help="内容最短字数（低于此值触发重抓）")
    parser.add_argument("--dry-run", action="store_true", help="只显示需要重抓的文章，不实际执行")
    parser.add_argument("--min-images", type=int, default=3, help="图片少于此数量也触发重抓")
    args = parser.parse_args()

    config = load_config()
    sites = load_sites()
    db = Database(config["database"]["path"])

    # 找出需要重抓的文章：内容过短、无图或少图
    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT id, url, title, content, images, status FROM articles
               WHERE status IN ('approved', 'candidate', 'pending')
                 AND (
                   content IS NULL OR content = '' OR length(content) < ?
                   OR images IS NULL OR images = '[]'
                   OR COALESCE(json_array_length(images), 0) < ?
                 )
               ORDER BY status = 'approved' DESC, score DESC""",
            (args.min_content, args.min_images),
        ).fetchall()

    articles = [db._row_to_dict(r) for r in rows]

    if not articles:
        logger.info("所有文章内容和图片都完整，无需重抓")
        return

    logger.info(f"找到 {len(articles)} 篇需要补齐的文章")

    if args.dry_run:
        for a in articles:
            content_len = len(a.get("content", "") or "")
            has_img = bool(a.get("images") and a["images"] != "[]")
            logger.info(f"  [{a['status']}] {a['title'][:60]} | 内容:{content_len}字 | 图片:{'✅' if has_img else '❌'}")
        return

    asyncio.run(refetch_articles(articles, sites, config))


if __name__ == "__main__":
    main()
