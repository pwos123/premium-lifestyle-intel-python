import hashlib
import json
from pathlib import Path
from typing import Any


def parse_image_list(value: Any) -> list[str]:
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


def is_manual_image(path: str) -> bool:
    return Path(path or "").name.startswith("manual_")


def _resolve_local(path: str) -> Path | None:
    p = Path(path)
    candidates = [p]
    if not p.is_absolute():
        candidates.extend([
            Path("/data/images") / p.name,
            Path("/app/static/images") / p.name,
            Path("static/images") / p.name,
        ])
    else:
        candidates.extend([
            Path("/data/images") / p.name,
            Path("/app/static/images") / p.name,
            Path("static/images") / p.name,
        ])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _content_key(path: str) -> str:
    local = _resolve_local(path)
    if not local:
        return ""
    try:
        return hashlib.md5(local.read_bytes()).hexdigest()
    except Exception:
        return ""


def _path_key(path: str) -> str:
    name = Path(path or "").name
    return name.lower() if name else str(path).lower()


def merge_article_images(
    existing: Any,
    incoming: Any,
    *,
    max_images: int = 15,
) -> list[str]:
    """Merge crawled images into an article without disturbing manual edits.

    Existing order is authoritative. New crawler images are appended only when
    they are not already represented by filename or by local file hash.
    """
    existing_list = parse_image_list(existing)
    incoming_list = parse_image_list(incoming)
    if not existing_list:
        return incoming_list[:max_images]
    if not incoming_list:
        return existing_list

    result: list[str] = []
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()

    for image in existing_list:
        key = _path_key(image)
        if key in seen_paths and not is_manual_image(image):
            continue
        result.append(image)
        seen_paths.add(key)
        content_key = _content_key(image)
        if content_key:
            seen_hashes.add(content_key)

    for image in incoming_list:
        if len(result) >= max_images:
            break
        key = _path_key(image)
        if key in seen_paths:
            continue
        content_key = _content_key(image)
        if content_key and content_key in seen_hashes:
            continue
        result.append(image)
        seen_paths.add(key)
        if content_key:
            seen_hashes.add(content_key)

    return result


def has_image_improvement(existing: Any, incoming: Any, *, max_images: int = 15) -> bool:
    merged = merge_article_images(existing, incoming, max_images=max_images)
    return len(merged) > len(parse_image_list(existing))
