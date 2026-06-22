"""
内容解析器 — 从网页中提取标题、正文、图片
"""

import logging
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ContentParser:
    """从 HTML 中提取结构化内容"""

    def __init__(self):
        # 不需要的标签
        self.remove_tags = [
            "script", "style", "nav", "footer", "header",
            "aside", "iframe", "noscript", "svg",
        ]

    def parse_article(self, html: str, url: str, selectors: dict = None) -> dict:
        """
        解析文章页面，提取标题、正文、图片

        Args:
            html: HTML 内容
            url: 文章 URL
            selectors: CSS 选择器配置

        Returns:
            {"title": ..., "content": ..., "images": [...]}
        """
        soup = BeautifulSoup(html, "lxml")

        # Many sites keep lazy-loaded or JSON-LD image data in script/noscript.
        # Extract media before removing those tags.
        images = self._extract_images(soup, selectors, url)

        # 移除无用标签
        for tag in self.remove_tags:
            for element in soup.find_all(tag):
                element.decompose()

        title = self._extract_title(soup, selectors)
        content = self._extract_content(soup, selectors, url)

        return {
            "title": title,
            "content": content,
            "images": images,
            "url": url,
        }

    def parse_link_list(self, html: str, base_url: str, selector: str = None) -> list[str]:
        """从列表页提取文章链接"""
        soup = BeautifulSoup(html, "lxml")
        links = []

        if selector:
            elements = soup.select(selector)
        else:
            # 自动检测文章链接
            elements = soup.find_all("a", href=True)

        seen = set()
        for el in elements:
            href = el.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            full_url = urljoin(base_url, href)

            # 过滤非文章链接
            if not self._is_article_url(full_url, base_url):
                continue

            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

        return links

    def _extract_title(self, soup: BeautifulSoup, selectors: dict = None) -> str:
        """提取标题"""
        # 尝试配置的选择器
        if selectors and selectors.get("title"):
            for sel in selectors["title"].split(","):
                el = soup.select_one(sel.strip())
                if el and el.get_text(strip=True):
                    return el.get_text(strip=True)

        # 通用策略
        # 1. og:title
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()

        # 2. <h1>
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)

        # 3. <title>
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)

        return "未知标题"

    def _extract_content(self, soup: BeautifulSoup, selectors: dict = None, url: str = "") -> str:
        """提取正文"""
        content_text = ""

        # 尝试配置的选择器
        if selectors and selectors.get("content"):
            for sel in selectors["content"].split(","):
                elements = soup.select(sel.strip())
                if elements:
                    content_text = "\n".join(el.get_text(separator="\n", strip=True) for el in elements)
                    if len(content_text) > 100:
                        break

        # 备用：使用 readability 算法
        if len(content_text) < 100:
            try:
                from readability import Document
                doc = Document(str(soup))
                readable_html = doc.summary()
                readable_soup = BeautifulSoup(readable_html, "lxml")
                content_text = readable_soup.get_text(separator="\n", strip=True)
            except Exception:
                pass

        # 备用：提取 article / main 标签
        if len(content_text) < 100:
            for tag_name in ["article", "main", '[role="main"]']:
                if tag_name.startswith("["):
                    el = soup.select_one(tag_name)
                else:
                    el = soup.find(tag_name)
                if el:
                    content_text = el.get_text(separator="\n", strip=True)
                    if len(content_text) > 100:
                        break

        # 清理
        content_text = re.sub(r"\n{3,}", "\n\n", content_text)
        content_text = re.sub(r" {2,}", " ", content_text)
        return content_text.strip()

    def _extract_images(self, soup: BeautifulSoup, selectors: dict = None, url: str = "") -> list[str]:
        """提取图片 URL — 智能定位正文区，不收 og:image，去重"""
        images = []

        # 智能定位正文容器: 找包含最多 <p> 的区块。正文图优先于全页
        # selector，避免 Wallpaper* 这类站点的推荐图/通用资源挤占名额。
        content_area = self._find_content_area(soup)
        max_images = 30 if content_area else 6

        for img in content_area.find_all("img"):
            src = self._get_best_image_url(img)
            # Shopify CDN {width}x 模板 → 请求全尺寸
            src = src.replace("{width}", "1200") if src else src
            if src:
                full_url = urljoin(url, src)
                if full_url not in images and self._is_valid_image(full_url):
                    images.append(full_url)
            if len(images) >= max_images:
                break

        if selectors and selectors.get("image"):
            for sel in selectors["image"].split(","):
                for img in soup.select(sel.strip()):
                    src = self._get_best_image_url(img)
                    if src:
                        full_url = urljoin(url, src)
                        if full_url not in images and self._is_valid_image(full_url):
                            images.append(full_url)

        # Cover fallbacks for layouts where editorial images live outside body.
        if not images:
            for attrs in (
                {"property": "og:image"},
                {"property": "og:image:secure_url"},
                {"name": "twitter:image"},
                {"name": "twitter:image:src"},
            ):
                meta = soup.find("meta", attrs=attrs)
                value = meta.get("content", "") if meta else ""
                if value:
                    full_url = urljoin(url, value)
                    if self._is_valid_image(full_url):
                        images.append(full_url)

        if not images:
            images.extend(self._extract_jsonld_images(soup, url))

        # 去重: 同一路径去 query 参数后的变体
        images = self._dedup_images(images)
        images = self._rank_images(images)

        return images

    @staticmethod
    def _get_best_image_url(img) -> str:
        """从 <img> 取最优图片 URL。
        优先级: data-src / data-original / data-lazy-src > srcset(最大尺寸) > src。
        data: URI 和已知占位图(1×1, blank, spacer)一律跳过。"""
        # 1. lazy-load 属性 (真图优先)
        for attr in [
            "data-src", "data-original", "data-lazy-src", "data-lazy",
            "data-image", "data-image-src", "data-flickity-lazyload",
        ]:
            val = img.get(attr, "")
            if val and not val.startswith("data:"):
                return val

        # 2. srcset — 取最大尺寸
        srcset = img.get("data-srcset") or img.get("data-lazy-srcset") or img.get("srcset", "")
        if srcset:
            candidates = []
            for part in srcset.split(","):
                part = part.strip()
                if not part:
                    continue
                pieces = part.rsplit(None, 1)
                url_candidate = pieces[0].strip()
                if len(pieces) == 2:
                    desc = pieces[1].strip().rstrip("w")
                    try:
                        size = int(desc)
                    except ValueError:
                        try:
                            size = int(float(desc.rstrip("x")) * 100)
                        except ValueError:
                            size = 0
                    candidates.append((size, url_candidate))
                else:
                    candidates.append((0, url_candidate))
            if candidates:
                candidates.sort(key=lambda x: -x[0])
                return candidates[0][1]

        # 3. src — 仅在不是占位图时使用
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            if not re.search(r"1x1|1\.gif|blank|spacer|placeholder|pixel|transparent\.gif", src, re.I):
                return src

        return ""

    @staticmethod
    def _extract_jsonld_images(soup: BeautifulSoup, base_url: str) -> list[str]:
        images = []

        def collect(value):
            if isinstance(value, str):
                images.append(urljoin(base_url, value))
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                if value.get("url"):
                    collect(value["url"])
                elif value.get("contentUrl"):
                    collect(value["contentUrl"])

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or script.get_text() or "")
            except (json.JSONDecodeError, TypeError):
                continue
            nodes = payload if isinstance(payload, list) else [payload]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                graph = node.get("@graph", [])
                candidates = [node] + (graph if isinstance(graph, list) else [])
                for candidate in candidates:
                    if isinstance(candidate, dict) and candidate.get("image"):
                        collect(candidate["image"])
            if images:
                break
        return [image for image in images if ContentParser._is_valid_image(image)]

    @staticmethod
    def _find_content_area(soup: BeautifulSoup):
        """智能定位正文容器: 找 <p> 最多的 div/section/article/main;
        若该区块无图，扩到父级 article/main 或含图父容器
        以支持图文分离布局(Leibal/Sight Unseen/Shopify)。"""
        candidates = []
        for tag in soup.find_all(["article", "main", "div", "section"]):
            p_count = len(tag.find_all("p", recursive=False))
            if p_count >= 2:
                candidates.append((p_count, tag))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            content_area = candidates[0][1]
            # 图文分离布局: 内容区无图，向上找含图容器
            if len(content_area.find_all("img")) == 0:
                expanded = None
                for ancestor in content_area.parents:
                    if ancestor.name in ("article", "main"):
                        if len(ancestor.find_all("p")) >= 2:
                            expanded = ancestor
                        break  # 碰到 article/main 就停，不管是否可用
                if expanded:
                    return expanded
                # 无 article/main（或 article/main p 不够），找含图父容器
                for ancestor in content_area.parents:
                    if len(ancestor.find_all("img")) >= 3:
                        return ancestor
            return content_area
        return soup.find("article") or soup.find("main") or soup

    @staticmethod
    def _dedup_images(images: list[str]) -> list[str]:
        """去 CDN 变体: 同路径不同 query 参数只保留一个"""
        from urllib.parse import urlparse, urlunparse
        seen = set()
        result = []
        for img_url in images:
            parsed = urlparse(img_url)
            stem = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
            if stem not in seen:
                seen.add(stem)
                result.append(img_url)
        return result

    @staticmethod
    def _rank_images(images: list[str]) -> list[str]:
        def score(img_url: str) -> int:
            lowered = img_url.lower()
            value = 0
            if any(token in lowered for token in (
                "scorecardresearch.com", "flexiimages",
                "images.fie.futurecdn.net", "avatar", "profile",
                "author", "logo", "icon",
            )):
                value -= 1000
            if any(token in lowered for token in (
                "gksv8hm2glnpcijk3i63rt",
                "mvek3i4ydj5epg9exytmpt",
                "rieasezukfzrc3twywjqst",
            )):
                value -= 1000
            if "/wp-content/uploads/" in lowered:
                value += 80
            if "cdn.mos.cms.futurecdn.net" in lowered:
                value += 60
            if re.search(r"[-_=](1920|1600|1500|1400|1280|1200|1024)(?:[-_.?&]|$)", lowered):
                value += 40
            if re.search(r"[?&](w|width)=(1920|1600|1500|1400|1280|1200|1024|1000)", lowered):
                value += 40
            if re.search(r"[?&](w|width)=(77|120|140|150)", lowered):
                value -= 400
            if re.search(r"[-_](77|120|140|150)-", lowered):
                value -= 300
            return value

        ranked = sorted(enumerate(images), key=lambda item: (-score(item[1]), item[0]))
        return [img for _, img in ranked]

    @staticmethod
    def _is_article_url(url: str, base_url: str) -> bool:
        """判断 URL 是否是文章链接"""
        # 必须是同域名
        from urllib.parse import urlparse
        base_domain = urlparse(base_url).netloc
        url_domain = urlparse(url).netloc

        # 允许子域名
        if not (base_domain in url_domain or url_domain in base_domain):
            return False

        # 排除非文章路径
        skip_patterns = [
            "/tag/", "/category/", "/author/", "/page/",
            "/login", "/signup", "/register", "/search",
            "/cart", "/checkout", "/account",
            ".pdf", ".zip", ".mp4", ".mp3",
            "/feed", "/rss", "/sitemap",
            "#", "javascript:",
        ]
        url_lower = url.lower()
        for pattern in skip_patterns:
            if pattern in url_lower:
                return False

        # 文章链接通常有日期或长路径
        if re.search(r"/\d{4}/", url) or re.search(r"/[a-z0-9-]{10,}", url):
            return True

        return True  # 默认允许

    @staticmethod
    def _is_valid_image(url: str) -> bool:
        """判断是否是有效图片 URL"""
        if not url or url.startswith("data:"):
            return False
        skip_patterns = ["logo", "icon", "avatar", "badge", "pixel", "spacer", "tracking", "banner", "header", "footer", "button", "arrow", "social", "share", "default", "placeholder", "bg-", "background", "loading", "sprite", "1x1", "blank", "empty", "dummy", "transparent"]
        url_lower = url.lower()
        for pattern in skip_patterns:
            if pattern in url_lower:
                return False
        return True
