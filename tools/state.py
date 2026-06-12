import json
import os
from urllib.parse import parse_qsl, unquote, urlencode, urlparse


def _normalize_url(url: str) -> str:
    """Canonical form for dedup: no scheme, no www/port, percent-decoded path,
    query kept (it can be the article id, e.g. ?p=110057) minus utm_* noise.

    Lesson 2026-06-13: the seen file held the same article 3 times
    (https vs :443, %D8 vs %d8) while ?p= articles collided to one entry.
    """
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    host = host.removeprefix("www.")
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    path = unquote(parsed.path).rstrip("/")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    qs = f"?{urlencode(query)}" if query else ""
    return f"{host}{path}{qs}"


def load_seen_urls(path: str) -> set:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # re-normalize on load so entries saved under older rules still match
        return {_normalize_url(u) for u in data}
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
