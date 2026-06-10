import logging
import re

import chardet
import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIMEOUT = 15
ARTICLE_PATH_PATTERNS = re.compile(
    r"/(report|paper|brief|analysis|commentary|publication|study|article|post|opinion|news|article|item)s?/",
    re.IGNORECASE,
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ThinkTankMonitor/1.0)",
    "Accept-Charset": "utf-8",
}


def fetch_reports(think_tank: dict, max_full_text_chars: int = 80000) -> list:
    name = think_tank["name"]
    rss_url = think_tank.get("rss")
    site_url = think_tank["url"]

    if rss_url:
        results = _fetch_rss(rss_url)
        if len(results) >= 3:
            logger.info(f"[{name}] RSS: {len(results)} entries from configured feed")
            return results

    discovered_rss = _discover_rss(site_url)
    if discovered_rss:
        results = _fetch_rss(discovered_rss)
        if len(results) >= 3:
            logger.info(f"[{name}] RSS: {len(results)} entries from auto-discovered feed")
            return results

    results = _scrape_html(site_url)
    logger.info(f"[{name}] HTML: {len(results)} entries from scraping")
    return results


def _fetch_rss(rss_url: str) -> list:
    try:
        feed = feedparser.parse(rss_url)
        results = []
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()
            if title and url:
                results.append({"title": title, "url": url, "summary": summary})
        return results
    except Exception as e:
        logger.warning(f"RSS fetch failed for {rss_url}: {e}")
        return []


def _discover_rss(site_url: str) -> str:
    try:
        resp = _get(site_url)
        if not resp:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        for link in soup.find_all("link", rel="alternate"):
            link_type = link.get("type", "")
            if "rss" in link_type or "atom" in link_type:
                href = link.get("href", "")
                if href:
                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(site_url, href)
                    return href
    except Exception as e:
        logger.warning(f"RSS discovery failed for {site_url}: {e}")
    return ""


def _scrape_html(site_url: str) -> list:
    resp = _get(site_url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    from urllib.parse import urljoin, urlparse

    base_domain = urlparse(site_url).netloc
    seen = set()
    results = []

    candidates = []

    for tag in soup.find_all(["article", "div"], class_=re.compile(r"(post|card|item|entry|news|article|study|publication)", re.I)):
        for a in tag.find_all("a", href=True):
            candidates.append(a)

    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        a = tag.find("a", href=True)
        if a:
            candidates.append(a)

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if len(text) > 25:
            candidates.append(a)

    for a in candidates:
        href = a.get("href", "").strip()
        text = a.get_text(strip=True)

        if not href or not text or len(text) < 15:
            continue

        if href.startswith("/"):
            href = urljoin(site_url, href)
        elif not href.startswith("http"):
            continue

        if urlparse(href).netloc != base_domain:
            continue

        if href in seen:
            continue

        if ARTICLE_PATH_PATTERNS.search(href) or len(text) > 30:
            seen.add(href)
            results.append({"title": text, "url": href, "summary": ""})

    return results[:50]


def fetch_full_text(url: str, max_chars: int = 80000) -> str:
    resp = _get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:max_chars]


def _get(url: str) -> requests.Response:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1", "ascii"):
            detected = chardet.detect(resp.content)
            if detected["encoding"]:
                resp.encoding = detected["encoding"]

        return resp
    except requests.RequestException as e:
        logger.warning(f"HTTP request failed for {url}: {e}")
        return None
