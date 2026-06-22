#!/usr/bin/env python3
"""
存量图片批量压缩 — 按 settings.yaml 的 max_width/quality 压缩全部缓存图片
用法: python run_image_compress.py [--dry-run]
"""

import argparse, logging, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("img_compress")


def compress_image(path: str, max_width: int, quality: int, dry_run: bool) -> tuple[int, int]:
    """Compress a single image file in-place. Returns (before_bytes, after_bytes)."""
    before = os.path.getsize(path)
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(path)
        fmt = img.format or "JPEG"
        if img.mode in ("RGBA", "P", "LA"):
            if fmt == "PNG" and img.mode == "RGBA":
                pass  # keep RGBA for PNG
            else:
                img = img.convert("RGB")
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)

        if dry_run:
            return (before, before)

        out = BytesIO()
        save_fmt = "JPEG" if fmt not in ("JPEG", "PNG", "GIF", "WEBP") else fmt
        save_kwargs = {"format": save_fmt, "optimize": True}
        if save_fmt == "JPEG":
            save_kwargs["quality"] = quality
        img.save(out, **save_kwargs)
        compressed = out.getvalue()

        if len(compressed) < before:
            with open(path, "wb") as f:
                f.write(compressed)
            return (before, len(compressed))
        return (before, before)
    except Exception as e:
        logger.debug(f"压缩失败 {path}: {e}")
        return (before, before)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dir", type=str, default=None)
    args = parser.parse_args()

    config = load_config()
    img_cfg = config.get("images", {})
    image_dir = args.dir or img_cfg.get("cache_dir", "static/images")
    max_width = img_cfg.get("max_width", 1200)
    quality = img_cfg.get("quality", 85)

    if not os.path.isdir(image_dir):
        logger.error(f"目录不存在: {image_dir}")
        return

    files = [f for f in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, f))]
    total = len(files)
    logger.info(f"扫描 {image_dir}: {total} 个文件")
    logger.info(f"压缩参数: max_width={max_width}px, quality={quality}")

    total_before = 0
    total_after = 0
    compressed_count = 0
    skipped_count = 0

    for i, fname in enumerate(sorted(files)):
        fpath = os.path.join(image_dir, fname)
        before, after = compress_image(fpath, max_width, quality, args.dry_run)
        total_before += before
        total_after += after
        if after < before:
            compressed_count += 1
            saved_pct = (1 - after / before) * 100
            if (i + 1) % 500 == 0 or saved_pct > 50:
                logger.info(f"  [{i+1}/{total}] {fname}: {before//1024}K → {after//1024}K (-{saved_pct:.0f}%)")
        else:
            skipped_count += 1

    saved_mb = (total_before - total_after) / (1024 * 1024)
    before_mb = total_before / (1024 * 1024)
    after_mb = total_after / (1024 * 1024)

    logger.info("=" * 50)
    logger.info(f"压缩完成: {total} 文件")
    logger.info(f"  压缩前: {before_mb:.1f} MB")
    logger.info(f"  压缩后: {after_mb:.1f} MB")
    logger.info(f"  节省:   {saved_mb:.1f} MB ({saved_mb/before_mb*100:.1f}%)" if before_mb > 0 else "  无变化")
    logger.info(f"  已压缩: {compressed_count} | 跳过: {skipped_count}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
