import json
import os
from urllib.parse import urlparse, urlunparse


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path.rstrip("/") or "/",
        fragment="",
    )
    return urlunparse(normalized)


def load_seen_urls(path: str) -> set:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data)
    except (json.JSONDecodeError, IOError):
        return set()


def save_seen_urls(seen: set, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def filter_new_reports(reports: list, seen: set) -> list:
    return [r for r in reports if _normalize_url(r["url"]) not in seen]


def mark_sent(urls: list, seen: set, path: str) -> set:
    for url in urls:
        seen.add(_normalize_url(url))
    save_seen_urls(seen, path)
    return seen
