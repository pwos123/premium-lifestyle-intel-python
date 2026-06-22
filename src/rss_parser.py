"""
RSS 解析器 — 从 RSS/Atom feed 提取文章信息
"""

import logging
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree as ET
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 命名空间
NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
}


def fetch_rss_articles(feed_url: str, max_articles: int = 10) -> list[dict]:
    """
    从 RSS/Atom feed 提取文章列表

    Returns:
        [{"title": ..., "url": ..., "content": ..., "images": [...], "published": ...}]
    """
    try:
        resp = httpx.get(
            feed_url,
            headers={"User-Agent": "Mozilla/5.0 Chrome/125.0"},
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"RSS 获取失败: {feed_url} - {e}")
        return []

    return parse_rss_articles(resp.text, max_articles=max_articles)


async def fetch_rss_articles_async(
    feed_url: str,
    client: httpx.AsyncClient,
    max_articles: int = 10,
    timeout: int = 15,
    headers: dict | None = None,
) -> list[dict]:
    """Fetch RSS/Atom without blocking the crawler event loop."""
    request_headers = {
        "User-Agent": "Mozilla/5.0 Chrome/125.0",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    request_headers.update(headers or {})
    try:
        resp = await client.get(
            feed_url,
            headers=request_headers,
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error("RSS 获取失败: %s - %s", feed_url, exc)
        return []

    return parse_rss_articles(resp.text, max_articles=max_articles)


def parse_rss_articles(text: str, max_articles: int = 10) -> list[dict]:
    """Parse already-fetched RSS/Atom text."""
    text = (text or "").lstrip("\ufeff \t\r\n")
    articles = []
    feed_head = text[:1000].lower()

    # 尝试 RSS 2.0 格式
    if "<rss" in feed_head or "<channel" in feed_head or "<rdf:rdf" in feed_head:
        articles = _parse_rss2(text)
    # 尝试 Atom 格式
    elif "<feed" in feed_head:
        articles = _parse_atom(text)
    else:
        logger.warning("未知 feed 格式")
        return []

    return articles[:max_articles]


def _parse_rss2(text: str) -> list[dict]:
    """解析 RSS 2.0 格式"""
    articles = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        logger.error(f"RSS XML 解析失败: {e}")
        return []

    # RSS 1.0/RDF commonly namespaces <item>; compare the local tag name.
    for item in (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "item"):
        title = _get_text(item, "title")
        link = _get_text(item, "link")
        if not title or not link:
            continue

        # 提取内容：优先 content:encoded，其次 description
        content = ""
        for ns_key, ns_url in NAMESPACES.items():
            el = item.find(f"{{{ns_url}}}encoded")
            if el is not None and el.text:
                content = el.text
                break

        if not content:
            desc = _get_text(item, "description")
            if desc:
                content = desc

        # 从 HTML 内容中提取纯文本
        if content:
            soup = BeautifulSoup(content, "lxml")
            content_text = soup.get_text(separator="\n", strip=True)
            # 提取图片
            images = []
            for img in soup.find_all("img"):
                src = _best_image_src(img)
                if src and not src.startswith("data:") and _is_valid_image(src):
                    images.append(urljoin(link, src))
                if len(images) >= 15:
                    break
        else:
            content_text = ""
            images = []

        # 提取 enclosure 图片
        for enc in item.findall("enclosure"):
            url = enc.get("url", "")
            if url and "image" in enc.get("type", ""):
                if url not in images:
                    images.insert(0, url)

        # 提取 media:content 图片
        for ns_url in NAMESPACES.values():
            for media in item.findall(f"{{{ns_url}}}content"):
                url = media.get("url", "")
                if url and url not in images:
                    images.append(url)
            for media in item.findall(f"{{{ns_url}}}thumbnail"):
                url = media.get("url", "")
                if url and url not in images:
                    images.append(url)

        # 发布日期
        pub_date = _get_text(item, "pubDate") or _get_text(item, "dc:date") or ""

        articles.append({
            "title": title,
            "url": link,
            "content": content_text,
            "images": images,
            "published": pub_date,
        })

    return articles


def _parse_atom(text: str) -> list[dict]:
    """解析 Atom 格式"""
    articles = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        logger.error(f"Atom XML 解析失败: {e}")
        return []

    ns = NAMESPACES["atom"]
    for entry in root.findall(f"{{{ns}}}entry"):
        title_el = entry.find(f"{{{ns}}}title")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        # link
        link_el = entry.find(f"{{{ns}}}link")
        link = link_el.get("href", "") if link_el is not None else ""

        if not title or not link:
            continue

        # content
        content_el = entry.find(f"{{{ns}}}content")
        if content_el is None:
            content_el = entry.find(f"{{{ns}}}summary")
        content = content_el.text if content_el is not None and content_el.text else ""

        if content:
            soup = BeautifulSoup(content, "lxml")
            content_text = soup.get_text(separator="\n", strip=True)
            images = [
                urljoin(link, src)
                for img in soup.find_all("img")
                if (src := _best_image_src(img))
            ]
        else:
            content_text = ""
            images = []

        pub_date = ""
        updated = entry.find(f"{{{ns}}}updated")
        if updated is not None and updated.text:
            pub_date = updated.text

        articles.append({
            "title": title,
            "url": link,
            "content": content_text,
            "images": images,
            "published": pub_date,
        })

    return articles


def _get_text(element, tag: str) -> str:
    """安全获取子元素文本"""
    el = element.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    local_tag = tag.split(":")[-1]
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == local_tag and child.text:
            return child.text.strip()
    return ""


def _best_image_src(img) -> str:
    for attr in ("data-src", "data-original", "data-lazy-src", "data-image", "src"):
        value = img.get(attr, "")
        if value and not value.startswith("data:"):
            return value
    srcset = img.get("data-srcset") or img.get("srcset") or ""
    if srcset:
        return srcset.split(",")[-1].strip().split()[0]
    return ""


def _is_valid_image(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    lowered = url.lower()
    return not any(token in lowered for token in (
        "logo", "icon", "avatar", "pixel", "spacer", "tracking",
        "placeholder", "loading", "sprite", "1x1", "blank", "transparent",
    ))
