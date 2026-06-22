#!/usr/bin/env python3
"""
信源健康检查：验证每个网站是否可访问、能否发现文章、能否解析首篇内容。
不调用大模型，不入库。
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx
import yaml

from src.crawler import Crawler
from src.rss_parser import fetch_rss_articles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_sites(filter_name: str = "") -> list[dict]:
    with open(Path(__file__).parent / "config" / "sites.yaml", encoding="utf-8") as f:
        sites = yaml.safe_load(f).get("sites", [])
    if filter_name:
        sites = [s for s in sites if filter_name.lower() in s["name"].lower()]
    return [s for s in sites if s.get("enabled", True)]


async def verify_site(site: dict, crawler: Crawler, client: httpx.AsyncClient) -> dict:
    name = site.get("name", "")
    site_type = site.get("type", "webpage")
    rss_url = site.get("rss") or ""
    selectors = site.get("selectors", {})
    result = {
        "name": name,
        "url": site.get("url", ""),
        "type": site_type,
        "category": site.get("category_hint", ""),
        "ok": False,
        "stage": "",
        "article_count": 0,
        "sample_url": "",
        "sample_title": "",
        "sample_content_len": 0,
        "error": "",
    }

    try:
        if rss_url or site_type == "rss":
            feed_url = rss_url or site["url"]
            items = fetch_rss_articles(feed_url, 3)
            result["article_count"] = len(items)
            if not items:
                result["stage"] = "rss_empty"
                result["error"] = "RSS 未返回文章"
                return result
            sample = items[0]
            result["sample_url"] = sample.get("url", "")
            result["sample_title"] = sample.get("title", "")
            result["sample_content_len"] = len(sample.get("content", "") or "")
            result["stage"] = "rss"
            result["ok"] = True
            return result

        html = await crawler.fetch_page(site["url"], client)
        if not html:
            result["stage"] = "homepage"
            result["error"] = "首页无法访问"
            return result

        links = crawler.parser.parse_link_list(html, site["url"], selectors.get("article_list"))
        result["article_count"] = len(links)
        if not links:
            result["stage"] = "link_list"
            result["error"] = "未发现文章链接"
            return result

        result["sample_url"] = links[0]
        article_html = await crawler.fetch_page(links[0], client)
        if not article_html:
            result["stage"] = "sample_page"
            result["error"] = "样本文章无法访问"
            return result

        parsed = crawler.parser.parse_article(article_html, links[0], selectors)
        result["sample_title"] = parsed.get("title", "")
        result["sample_content_len"] = len(parsed.get("content", "") or "")
        result["stage"] = "sample_parse"
        result["ok"] = bool(result["sample_title"] and result["sample_content_len"] >= 80)
        if not result["ok"]:
            result["error"] = "样本文章解析内容不足"
        return result
    except Exception as e:
        result["stage"] = result["stage"] or "exception"
        result["error"] = str(e)
        return result


async def run(filter_name: str = "", concurrent: int = 5) -> list[dict]:
    sites = load_sites(filter_name)
    crawler = Crawler(max_concurrent=concurrent, max_articles_per_site=3, request_timeout=25)
    results = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for site in sites:
            logger.info("验证信源: %s", site.get("name"))
            result = await verify_site(site, crawler, client)
            results.append(result)
            mark = "OK" if result["ok"] else "FAIL"
            logger.info("%s | %s | %s | %s", mark, result["name"], result["stage"], result["error"])
    return results


def write_reports(results: list[dict]) -> tuple[Path, Path]:
    out_dir = Path("data/site_checks")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"site_check_{stamp}.json"
    csv_path = out_dir / f"site_check_{stamp}.csv"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()) if results else [])
        writer.writeheader()
        writer.writerows(results)
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description="验证信源抓取健康度")
    parser.add_argument("--site", default="", help="只验证名称包含该文本的信源")
    parser.add_argument("--concurrent", type=int, default=5)
    args = parser.parse_args()

    results = asyncio.run(run(args.site, args.concurrent))
    json_path, csv_path = write_reports(results)
    ok_count = sum(1 for r in results if r["ok"])
    logger.info("验证完成: %s/%s 可抓取", ok_count, len(results))
    logger.info("JSON: %s", json_path)
    logger.info("CSV: %s", csv_path)


if __name__ == "__main__":
    main()
