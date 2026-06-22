#!/usr/bin/env python3
"""
图片审计与补抓 — 全库扫描缺失图, 按原始URL重下, 压缩至1600px/q80
用法: python run_image_audit.py [--dry-run]
"""

import argparse, json, logging, os, sys, time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("image_audit")

# Simple HTTP fetch (avoid heavy dependencies)
import urllib.request
import urllib.error
import ssl

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

def fetch_image(url: str, timeout: int = 15) -> bytes | None:
    """Fetch image bytes from URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            if resp.status == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "image" in content_type or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                    return resp.read()
    except Exception as e:
        pass
    return None

def compress_image(data: bytes, max_width: int = 1600, quality: int = 80) -> bytes | None:
    """Compress image using PIL if available, else return original."""
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()
    except ImportError:
        return data
    except Exception:
        return data

def image_exists_locally(url: str, image_dir: str) -> bool:
    """Check if image is already cached locally."""
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename or "." not in filename:
        filename = f"{abs(hash(url))}.jpg"
    local_path = os.path.join(image_dir, filename)
    return os.path.exists(local_path) and os.path.getsize(local_path) > 100

def save_image(data: bytes, url: str, image_dir: str) -> str | None:
    """Save image to local cache, return filename."""
    os.makedirs(image_dir, exist_ok=True)
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename or "." not in filename:
        ext = ".jpg"
        # Try to detect from content
        if data[:4] == b"\x89PNG":
            ext = ".png"
        elif data[:3] == b"GIF":
            ext = ".gif"
        elif data[:4] == b"RIFF":
            ext = ".webp"
        filename = f"{abs(hash(url))}{ext}"
    local_path = os.path.join(image_dir, filename)
    try:
        with open(local_path, "wb") as f:
            f.write(data)
        return filename
    except Exception:
        return None

def run_audit(dry_run: bool = False):
    config = load_config()
    db = Database(config["database"]["path"])
    image_dir = config.get("images", {}).get("cache_dir", "static/images")
    
    # Scan all articles with images
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, images FROM articles WHERE images IS NOT NULL AND images != '[]'"
        ).fetchall()
    
    stats = {"total_articles": len(rows), "missing": 0, "downloaded": 0, "already_cached": 0, "failed": 0}
    
    for row in rows:
        aid = row["id"]
        title = (row["title"] or "")[:50]
        images = row["images"]
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except:
                images = []
        
        if not images:
            continue
        
        for img_url in images:
            if not img_url or not img_url.startswith("http"):
                continue
            
            if image_exists_locally(img_url, image_dir):
                stats["already_cached"] += 1
                continue
            
            # Missing locally — try to download
            stats["missing"] += 1
            logger.info(f"  #{aid} 缺图: {os.path.basename(urlparse(img_url).path)[:50]}")
            
            if dry_run:
                continue
            
            data = fetch_image(img_url)
            if data and len(data) > 500:
                compressed = compress_image(data)
                filename = save_image(compressed or data, img_url, image_dir)
                if filename:
                    stats["downloaded"] += 1
                    logger.info(f"    ✅ 已下载: {filename} ({len(compressed or data)} bytes)")
                else:
                    stats["failed"] += 1
            else:
                stats["failed"] += 1
                logger.warning(f"    ❌ 下载失败")
            
            time.sleep(0.3)  # Rate limit
    
    logger.info(
        f"\n图片审计完成: 扫描{stats['total_articles']}篇, "
        f"缺失{stats['missing']}张, 已缓存{stats['already_cached']}张, "
        f"下载{stats['downloaded']}张, 失败{stats['failed']}张"
    )
    return stats

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="图片审计与补抓")
    parser.add_argument("--dry-run", action="store_true", help="仅扫描不下载")
    args = parser.parse_args()
    run_audit(dry_run=args.dry_run)
