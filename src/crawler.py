"""
爬虫引擎 — 支持 RSS 和网页两种抓取模式
RSS 模式优先（更稳定、不会被反爬）
"""

import asyncio
import logging
import random
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .parser import ContentParser
from .rss_parser import fetch_rss_articles_async

logger = logging.getLogger(__name__)


class Crawler:
    """异步网页爬虫，支持 RSS + 网页两种模式"""

    def __init__(
        self,
        max_concurrent: int = 5,
        max_articles_per_site: int = 10,
        request_timeout: int = 30,
        retry_count: int = 3,
        user_agents: list[str] = None,
        image_cache_dir: str = "static/images",
        max_image_concurrent: int = 3,
        max_site_concurrent: int = 4,
        site_timeout: int = 180,
        max_images_per_article: int = 5,
        min_host_interval: float = 0.25,
        rss_enrich_min_content_chars: int = 600,
    ):
        self.max_concurrent = max_concurrent
        self.max_articles_per_site = max_articles_per_site
        self.request_timeout = request_timeout
        self.retry_count = retry_count
        self.user_agents = user_agents or [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
        ]
        self.user_agent = random.choice(self.user_agents)
        self.image_cache_dir = Path(image_cache_dir)
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)
        self.parser = ContentParser()
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.image_semaphore = asyncio.Semaphore(max_image_concurrent)
        self.site_semaphore = asyncio.Semaphore(max_site_concurrent)
        self.site_timeout = site_timeout
        self.max_images_per_article = max(1, int(max_images_per_article))
        self.min_host_interval = max(0.0, float(min_host_interval))
        self.rss_enrich_min_content_chars = max(0, int(rss_enrich_min_content_chars))
        self._host_locks = defaultdict(asyncio.Lock)
        self._host_last_request = defaultdict(float)

    def _random_ua(self) -> str:
        return self.user_agent

    def _request_headers(self, extra: dict | None = None) -> dict:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }
        headers.update(extra or {})
        return headers

    def _site_outer_timeout(self, site: dict) -> float:
        """Give crawl_site enough grace to return partial articles near timeout."""
        site_timeout = max(1.0, float(site.get("site_timeout", self.site_timeout)))
        return max(site_timeout + 45.0, site_timeout * 1.25)

    async def _respect_host_interval(self, url: str):
        host = urlparse(url).netloc.lower()
        if not host:
            return
        async with self._host_locks[host]:
            elapsed = time.monotonic() - self._host_last_request[host]
            if elapsed < self.min_host_interval:
                await asyncio.sleep(self.min_host_interval - elapsed)
            self._host_last_request[host] = time.monotonic()

    async def fetch_page(
        self,
        url: str,
        client: httpx.AsyncClient,
        headers: dict | None = None,
    ) -> str:
        """获取单个页面 HTML"""
        for attempt in range(self.retry_count):
            try:
                await self._respect_host_interval(url)
                async with self.semaphore:
                    resp = await client.get(
                        url,
                        headers=self._request_headers(headers),
                        timeout=self.request_timeout,
                        follow_redirects=True,
                    )
                    if resp.status_code in (401, 403, 404, 410):
                        logger.warning("抓取停止(%s): %s", resp.status_code, url)
                        return ""
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After", "")
                        delay = (
                            min(float(retry_after), 30.0)
                            if retry_after.isdigit()
                            else min(2 ** attempt + random.random(), 10.0)
                        )
                        logger.warning("站点限流，%.1fs 后重试: %s", delay, url)
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:
                logger.warning(f"抓取失败 (尝试 {attempt+1}/{self.retry_count}): {url} - {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(2 ** attempt + random.random())
        return ""

    async def crawl_site(self, site: dict, client: httpx.AsyncClient) -> list[dict]:
        """
        抓取单个网站的文章列表
        优先使用 RSS 模式，回退到网页模式
        """
        site_name = site["name"]
        site_url = site["url"]
        site_type = site.get("type", "webpage")
        rss_url = site.get("rss") or site.get("rss_url") or ""
        selectors = site.get("selectors", {})
        category_hint = site.get("category_hint", "")
        request_headers = site.get("headers", {})
        site_timeout = max(1.0, float(site.get("site_timeout", self.site_timeout)))
        # 留一点余量，让单篇慢任务被取消时仍能返回已完成文章。
        deadline = time.monotonic() + max(0.5, site_timeout - 2.0)

        logger.info(f"开始抓取: {site_name} ({site_url})")

        # 1. 优先 RSS 模式
        if rss_url or site_type == "rss":
            feed_url = rss_url or site_url
            logger.info(f"  使用 RSS 模式: {feed_url}")
            try:
                await self._respect_host_interval(feed_url)
                async with self.semaphore:
                    raw_articles = await fetch_rss_articles_async(
                        feed_url,
                        client,
                        site.get("max_articles", self.max_articles_per_site),
                        timeout=min(self.request_timeout, 20),
                        headers=request_headers,
                    )
                if raw_articles:
                    article_limit = max(1, int(site.get("article_concurrent", 4)))
                    article_sem = asyncio.Semaphore(article_limit)

                    async def enrich(raw_article):
                        async with article_sem:
                            return await self._enrich_rss_article(
                                raw_article,
                                site_name,
                                category_hint,
                                selectors,
                                site_url,
                                request_headers,
                                client,
                            )

                    results = await self._collect_article_results(
                        [enrich(raw_article) for raw_article in raw_articles],
                        timeout=max(0.1, deadline - time.monotonic()),
                        site_name=site_name,
                    )
                    articles = [item for item in results if isinstance(item, dict)]
                    logger.info(f"  RSS 抓取完成: {len(articles)} 篇")
                    return articles
                logger.warning("  RSS 无文章，回退到网页模式")
            except Exception as e:
                logger.warning(f"  RSS 模式失败，回退到网页模式: {e}")

        # 2. 网页模式
        logger.info("  使用网页模式")
        html = await self.fetch_page(site_url, client, request_headers)
        if not html:
            logger.warning(f"  无法获取首页: {site_name}")
            return []

        article_selector = selectors.get("article_list")
        links = self.parser.parse_link_list(html, site_url, article_selector)
        links = links[: site.get("max_articles", self.max_articles_per_site)]
        logger.info(f"  发现 {len(links)} 个文章链接")

        article_limit = max(1, int(site.get("article_concurrent", 4)))
        article_sem = asyncio.Semaphore(article_limit)

        async def crawl_link(link):
            async with article_sem:
                return await self._crawl_article(
                    link,
                    site_name,
                    category_hint,
                    selectors,
                    site_url,
                    request_headers,
                    client,
                )

        results = await self._collect_article_results(
            [crawl_link(link) for link in links],
            timeout=max(0.1, deadline - time.monotonic()),
            site_name=site_name,
        )
        articles = [item for item in results if isinstance(item, dict)]

        logger.info(f"  网页模式完成: {len(articles)} 篇")
        return articles

    async def _enrich_rss_article(
        self,
        article: dict,
        site_name: str,
        category_hint: str,
        selectors: dict,
        site_url: str,
        request_headers: dict,
        client: httpx.AsyncClient,
    ) -> dict | None:
        url = article.get("url", "")
        if not url:
            return None
        image_urls = article.get("images", [])
        # Many feeds already contain usable text and images. Avoid fetching every
        # article page again, which is the largest source of anti-bot failures.
        if len(article.get("content", "")) < self.rss_enrich_min_content_chars or not image_urls:
            full_html = await self.fetch_page(url, client, {"Referer": site_url, **request_headers})
            if full_html:
                parsed = self.parser.parse_article(full_html, url, selectors)
                if len(parsed.get("content", "")) > len(article.get("content", "")):
                    article["content"] = parsed["content"]
                if parsed.get("title") and not article.get("title"):
                    article["title"] = parsed["title"]
                image_urls = list(dict.fromkeys((image_urls or []) + (parsed.get("images") or [])))
        if image_urls:
            article["images"] = await self._download_images(image_urls, client, referer_url=url)
        article["source"] = site_name
        article["category_hint"] = category_hint
        return article

    async def _collect_article_results(
        self,
        coroutines: list,
        timeout: float,
        site_name: str,
    ) -> list[dict]:
        """Collect completed article tasks and retain partial results on timeout."""
        if not coroutines:
            return []

        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        done, pending = await asyncio.wait(tasks, timeout=max(0.1, timeout))
        if pending:
            logger.warning(
                "  %s 达到时间预算，保留 %s 篇已完成结果，取消 %s 个慢任务",
                site_name,
                len(done),
                len(pending),
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        results = []
        for task in tasks:
            if task not in done or task.cancelled():
                continue
            try:
                item = task.result()
            except Exception as exc:
                logger.debug("  %s 单篇抓取失败: %s", site_name, exc)
                continue
            if isinstance(item, dict):
                results.append(item)
        return results

    async def _crawl_article(
        self,
        url: str,
        site_name: str,
        category_hint: str,
        selectors: dict,
        site_url: str,
        request_headers: dict,
        client: httpx.AsyncClient,
    ) -> dict | None:
        article_html = await self.fetch_page(url, client, {"Referer": site_url, **request_headers})
        if not article_html:
            return None
        parsed = self.parser.parse_article(article_html, url, selectors)
        if not parsed.get("title") or len(parsed.get("content", "")) < 80:
            return None
        parsed["images"] = await self._download_images(
            parsed.get("images", []),
            client,
            referer_url=url,
        )
        parsed["source"] = site_name
        parsed["category_hint"] = category_hint
        return parsed

    async def refetch_single(self, url: str, selectors: dict = None) -> dict | None:
        """重新抓取单篇文章的全文内容和图片"""
        async with self._make_client() as client:
            html = await self.fetch_page(url, client)
            if not html:
                return None

            parsed = self.parser.parse_article(html, url, selectors or {})
            result = {"content": "", "images": []}

            if len(parsed.get("content", "")) > 100:
                result["content"] = parsed["content"]
            if parsed.get("images"):
                local_images = await self._download_images(parsed["images"], client, referer_url=url)
                result["images"] = local_images

            return result

    async def crawl_all(self, sites: list[dict]) -> list[dict]:
        """抓取所有网站"""
        enabled_sites = [s for s in sites if s.get("enabled", True)]
        logger.info(f"开始抓取 {len(enabled_sites)} 个网站")

        all_articles = []
        async for article in self.crawl_all_streaming(enabled_sites):
            all_articles.append(article)

        logger.info(f"抓取完成，共 {len(all_articles)} 篇文章")
        return all_articles

    async def _download_images(
        self,
        urls: list[str],
        client: httpx.AsyncClient,
        referer_url: str = "",
    ) -> list[str]:
        """下载图片到本地缓存"""
        candidate_limit = max(self.max_images_per_article * 6, self.max_images_per_article)
        unique_urls = list(dict.fromkeys(
            url for url in urls if self._is_candidate_image_url(url)
        ))[:candidate_limit]

        async def download(url):
            try:
                return await self._download_single_image(url, client, referer_url=referer_url)
            except Exception as e:
                logger.debug(f"图片下载失败: {url} - {e}")
                return ""

        results = await asyncio.gather(*(download(url) for url in unique_urls))
        return [path for path in results if path][:self.max_images_per_article]

    @staticmethod
    def _is_candidate_image_url(url: str) -> bool:
        if not url or not isinstance(url, str) or "{{" in url or "}}" in url:
            return False
        lowered = url.lower()
        return not any(token in lowered for token in (
            "logo", "icon", "avatar", "pixel", "spacer", "tracking",
            "placeholder", "loading", "sprite", "1x1", "blank",
            "transparent", "contact-msg", "scorecardresearch.com",
            "flexiimages", "images.fie.futurecdn.net",
            "rachel_cormack.jpg?w=77",
            "gksv8hm2glnpcijk3i63rt",
            "mvek3i4ydj5epg9exytmpt",
            "rieasezukfzrc3twywjqst",
        ))

    async def _download_single_image(
        self,
        url: str,
        client: httpx.AsyncClient,
        referer_url: str = "",
    ) -> str:
        """下载单张图片，验真后才保存"""
        import hashlib
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix or ".jpg"
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
            ext = ".jpg"

        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"{url_hash}{ext}"
        local_path = self.image_cache_dir / filename

        if local_path.exists() and local_path.stat().st_size > 0:
            return str(local_path)

        try:
            async with self.image_semaphore:
                await self._respect_host_interval(url)
                image_headers = {
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                }
                if referer_url:
                    image_headers["Referer"] = referer_url
                resp = await client.get(
                    url,
                    headers=self._request_headers(image_headers),
                    timeout=min(self.request_timeout, 15),
                    follow_redirects=True,
                )
                if resp.status_code != 200:
                    return ""

                data = resp.content

                # 1. 大小检查: <2KB 不是真实图片
                if len(data) < 2048:
                    return ""

                # 2. 不是 HTML 错误页
                if data[:100].lstrip().startswith(b"<"):
                    return ""

                # 3. 魔数检查
                magic = data[:12]
                is_image = (
                    magic[:3] == b"\xff\xd8\xff" or       # JPEG
                    magic[:4] == b"\x89PNG" or             # PNG
                    magic[:4] == b"RIFF" or                # WebP
                    magic[:4] == b"GIF8" or                # GIF
                    magic[:4] == b"<svg" or                # SVG
                    magic[:2] == b"BM" or                  # BMP
                    b"ftypavif" in magic                   # AVIF
                )
                if not is_image:
                    return ""

                # 4. 尺寸检查: 过小的缩略图/icon 跳过
                try:
                    from PIL import Image
                    from io import BytesIO
                    img = Image.open(BytesIO(data))
                    w, h = img.size
                    if w < 300 or h < 240:
                        return ""
                except Exception:
                    pass  # 不能解析尺寸也不妨事，继续

                local_path.write_bytes(data)
                return str(local_path)
        except Exception:
            pass

        return ""

    async def crawl_all_streaming(self, sites: list[dict]):
        """流式抓取所有网站 — 逐篇产出，避免内存积压"""
        enabled_sites = [s for s in sites if s.get("enabled", True)]
        logger.info(f"开始流式抓取 {len(enabled_sites)} 个网站")

        async with self._make_client() as client:
            async def run_site(site):
                async with self.site_semaphore:
                    outer_timeout = self._site_outer_timeout(site)
                    try:
                        articles = await asyncio.wait_for(
                            self.crawl_site(site, client),
                            timeout=outer_timeout,
                        )
                        return site, articles, ""
                    except asyncio.TimeoutError:
                        return site, [], f"单站超时>{outer_timeout:.0f}s"
                    except Exception as exc:
                        return site, [], str(exc)

            tasks = [asyncio.create_task(run_site(site)) for site in enabled_sites]
            for task in asyncio.as_completed(tasks):
                site, articles, error = await task
                if error:
                    logger.error("抓取 %s 失败: %s", site.get("name"), error)
                    continue
                logger.info("站点完成: %s | %s 篇", site.get("name"), len(articles))
                for article in articles:
                    yield article

        logger.info("流式抓取完成")

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.request_timeout, connect=min(self.request_timeout, 10)),
            limits=httpx.Limits(
                max_connections=max(self.max_concurrent * 2, 10),
                max_keepalive_connections=max(self.max_concurrent, 5),
            ),
        )


def crawl_sites(sites: list[dict], **kwargs) -> list[dict]:
    """同步入口：抓取所有网站"""
    crawler = Crawler(**kwargs)
    return asyncio.run(crawler.crawl_all(sites))
