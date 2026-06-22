import hashlib
import json
from pathlib import Path
from typing import Any


def parse_images(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except Exception:
            return []
    return []


def resolve_image_path(path: str) -> Path | None:
    """Resolve cached article image with the same fallbacks used by H5 rendering."""
    p = Path(path)
    if p.exists():
        return p
    alt = Path("/data/images") / p.name
    if alt.exists():
        return alt
    alt_local = Path("static/images") / p.name
    if alt_local.exists():
        return alt_local
    alt2 = Path("/app/static/images") / p.name
    if alt2.exists():
        return alt2
    return None


def image_to_static_url(path: str) -> str:
    """Convert an image path to the public /images/<filename> URL if it exists."""
    try:
        p = Path(path)
        if not p.exists():
            alt = Path("/data/images") / p.name
            if alt.exists():
                p = alt
            else:
                alt_local = Path("static/images") / p.name
                if alt_local.exists():
                    p = alt_local
                else:
                    alt2 = Path("/app/static/images") / p.name
                    if alt2.exists():
                        p = alt2
                    else:
                        return ""
        return f"/images/{p.name}"
    except Exception:
        return ""


def is_junk_image(path: str) -> bool:
    """Filter out small icons, avatars, logos, banners, and extreme aspect ratios."""
    fname = Path(path).name.lower()
    junk_patterns = ["avatar", "icon", "logo", "banner", "favicon", "gravatar", "profile"]
    if any(p in fname for p in junk_patterns):
        return True
    try:
        from PIL import Image

        rp = resolve_image_path(path)
        if rp is None:
            return False
        with Image.open(rp) as img:
            w, h = img.size
            if w < 400 or h < 400:
                return True
            ratio = max(w, h) / max(min(w, h), 1)
            if ratio > 3.5:
                return True
    except Exception:
        pass
    return False


def select_h5_visible_images(images: Any, max_gallery: int = 4) -> dict[str, Any]:
    """Return the per-card cover and gallery images that the H5 renderer would show.

    This is intentionally per-article. The final H5 still applies issue-level cover
    de-duplication after all cards are assembled.
    """
    parsed = parse_images(images)
    existing_raw = [p for p in parsed if resolve_image_path(p)]
    existing = [p for p in existing_raw if not is_junk_image(p)]
    if not existing:
        existing = existing_raw

    cover = image_to_static_url(existing[0]) if existing else ""
    cover_hash = None
    if existing:
        try:
            rp = resolve_image_path(existing[0])
            if rp:
                cover_hash = hashlib.md5(rp.read_bytes()).hexdigest()
        except Exception:
            pass

    seen_hashes = {cover_hash} if cover_hash else set()
    gallery: list[str] = []
    for p in existing[1:]:
        if len(gallery) >= max_gallery:
            break
        if is_junk_image(p):
            continue
        try:
            rp = resolve_image_path(p)
            if not rp:
                continue
            h = hashlib.md5(rp.read_bytes()).hexdigest()
        except Exception:
            continue
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        url = image_to_static_url(p)
        if url:
            gallery.append(url)

    return {
        "cover": cover,
        "gallery": gallery,
        "visible": ([cover] if cover else []) + gallery,
        "raw_count": len(parsed),
        "existing_count": len(existing_raw),
        "filtered_count": max(len(existing_raw) - len(existing), 0),
        "note": "final_issue_may_dedupe_cover",
    }
