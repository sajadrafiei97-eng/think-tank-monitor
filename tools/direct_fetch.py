"""
Direct-fetch fallback: discovers recent articles straight from a site's
sitemap (or homepage scrape), matches keywords against title/URL-slug/body,
and date-filters using sitemap lastmod or article meta tags.

Used when search engines return nothing for a site (small sites are often
poorly indexed by Google) or when the search API is rate-limited.
Consumes NO search-API quota — only direct HTTP requests to the site itself.
"""
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from fetcher import _get, _scrape_html

logger = logging.getLogger(__name__)

# Per-site budget of extra article-page fetches (date extraction + body match)
MAX_ARTICLE_FETCHES = 14
MAX_CHILD_SITEMAPS = 8
MAX_SITEMAP_ENTRIES = 500
MAX_UNDATED_CANDIDATES = 40
MAX_LISTING_FETCHES = 6

_ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟـ]")  # tashkeel + tatweel

_DATE_META_PATTERNS = [
    re.compile(r'article:published_time["\']?\s+content=["\']([^"\']+)', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"'),
    # microdata: <meta itemprop="datePublished" content="..."> or
    # <span itemprop='datePublished' ...>2026-06-11</span> (e.g. rawabetcenter)
    re.compile(r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)', re.I),
    re.compile(r'itemprop=["\']datePublished["\'][^>]*>\s*(\d{4}-\d{2}-\d{2})', re.I),
    re.compile(r'property=["\']og:updated_time["\']\s+content=["\']([^"\']+)', re.I),
    re.compile(r'<time[^>]+datetime=["\']([^"\']+)', re.I),
]

_TITLE_PATTERNS = [
    re.compile(r'property=["\']og:title["\']\s+content=["\']([^"\']+)', re.I),
    re.compile(r"<title[^>]*>([^<]+)</title>", re.I),
]

_LISTING_SEGMENTS = {
    "blog", "blogs", "article", "articles", "posts", "post",
    "news", "publications", "publication", "studies", "reports",
    "المقالات", "مقالات", "المدونة", "مدونة",
}
_TAXONOMY_SEGMENTS = {
    "category", "categories", "tag", "tags", "author", "page",
    "تصنيف", "وسم", "كاتب",
}


def normalize(text: str) -> str:
    """Arabic-aware normalization so 'ايران' matches 'إِيرَان' etc."""
    text = _ARABIC_DIACRITICS.sub("", text)
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")
                .replace("ة", "ه"))
    return text.lower()


def compile_keywords(keywords: list) -> list:
    """Latin-script keywords match on word boundaries ('iran' must not hit
    'Tirana'); Arabic keywords match as substrings because prefixes attach
    to the word itself (وإيران، بطهران…)."""
    compiled = []
    for k in keywords:
        nk = normalize(k)
        if re.fullmatch(r"[a-z0-9 \-']+", nk):
            compiled.append(re.compile(r"\b" + re.escape(nk) + r"\b"))
        else:
            compiled.append(nk)
    return compiled


def _matches(text: str, compiled_keywords: list) -> bool:
    norm = normalize(text)
    for k in compiled_keywords:
        if isinstance(k, str):
            if k in norm:
                return True
        elif k.search(norm):
            return True
    return False


def _slug_text(url: str) -> str:
    """Decode the URL path into searchable text (slugs often contain the title)."""
    path = unquote(urlparse(url).path)
    return re.sub(r"[-_/+]", " ", path)


def _path_segments(url: str) -> list:
    path = unquote(urlparse(url).path).strip("/").lower()
    return [seg for seg in path.split("/") if seg]


def _is_listing_url(url: str) -> bool:
    """Return True for category/tag/blog listing pages that should not be sent."""
    segments = _path_segments(url)
    if not segments:
        return True
    if any(seg in _TAXONOMY_SEGMENTS for seg in segments):
        return True
    if len(segments) == 1 and segments[0] in _LISTING_SEGMENTS:
        return True
    return False


def _parse_date(raw: str):
    raw = raw.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# Arabic-Indic (٠-٩) and Persian (۰-۹) digits → ASCII
_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_AR_MONTHS = {
    "يناير": 1, "كانون الثاني": 1, "فبراير": 2, "شباط": 2,
    "مارس": 3, "آذار": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "نيسان": 4,
    "مايو": 5, "أيار": 5, "ايار": 5, "يونيو": 6, "حزيران": 6,
    "يوليو": 7, "تموز": 7, "أغسطس": 8, "اغسطس": 8, "آب": 8,
    "سبتمبر": 9, "أيلول": 9, "ايلول": 9, "أكتوبر": 10, "اكتوبر": 10,
    "تشرين الأول": 10, "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الأول": 12,
}
_AR_MONTH_RE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(map(re.escape, _AR_MONTHS)) + r")\s+(20\d{2})"
)
_YMD_RE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_DMY_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b")


def _safe_date(y: int, m: int, d: int):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def sniff_date(text: str):
    """Find a publish date in free text: handles Arabic-Indic digits,
    ٢٠٢٦-٦-٤ / 18/05/2026 numeric forms and '١٥ مارس ٢٠٢٦' month names."""
    text = text.translate(_DIGIT_TRANS)

    m = _AR_MONTH_RE.search(text)
    if m:
        return _safe_date(int(m.group(3)), _AR_MONTHS[m.group(2)], int(m.group(1)))

    m = _YMD_RE.search(text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _DMY_RE.search(text)
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        day, month = (d1, d2) if d2 <= 12 else (d2, d1)  # Arabic sites: D/M/Y
        return _safe_date(int(m.group(3)), month, day)

    return None


def _fetch_article_page(url: str, with_body: bool = False) -> tuple:
    """Fetch an article page once; extract (published_date, display_title, body_text)."""
    resp = _get(url)
    if not resp:
        return None, "", ""
    html = resp.text[:200000]
    found_date = None
    for pat in _DATE_META_PATTERNS:
        m = pat.search(html)
        if m:
            found_date = _parse_date(m.group(1))
            if found_date:
                break
    title = ""
    for pat in _TITLE_PATTERNS:
        m = pat.search(html)
        if m:
            title = m.group(1).strip()
            break
    body = ""
    if with_body or not found_date:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        body = soup.get_text(separator=" ", strip=True)[:40000]
        if not found_date:
            # no machine-readable meta date — sniff the visible byline area
            # (e.g. rasanah prints '١٥ مارس ٢٠٢٦' as plain text)
            found_date = sniff_date(body[:1500])
    if not with_body:
        body = ""
    return found_date, title, body


def _sitemap_candidates(site_url: str) -> list:
    """Possible sitemap locations: robots.txt + common paths."""
    candidates = []
    robots = _get(urljoin(site_url, "/robots.txt"))
    if robots:
        for line in robots.text.splitlines():
            if line.lower().startswith("sitemap:"):
                candidates.append(line.split(":", 1)[1].strip())
    candidates += [
        urljoin(site_url, "/sitemap.xml"),
        urljoin(site_url, "/sitemap_index.xml"),
        urljoin(site_url, "/wp-sitemap.xml"),
    ]
    seen = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def _parse_sitemap_xml(xml_text: str) -> tuple:
    """Returns (kind, entries) where kind is 'index' or 'urlset',
    entries is a list of (loc, lastmod_date_or_None)."""
    kind = "index" if "<sitemapindex" in xml_text[:2000] else "urlset"
    entries = []
    for m in re.finditer(
        r"<loc>\s*([^<\s]+)\s*</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", xml_text
    ):
        loc = m.group(1).strip()
        lastmod = _parse_date(m.group(2)) if m.group(2) else None
        entries.append((loc, lastmod))
    return kind, entries


def _collect_sitemap_entries(site_url: str) -> list:
    """Gather (url, lastmod) pairs from the site's sitemap tree."""
    for sm_url in _sitemap_candidates(site_url):
        resp = _get(sm_url)
        if not resp or "<" not in resp.text[:200]:
            continue
        kind, entries = _parse_sitemap_xml(resp.text)
        if not entries:
            continue

        if kind == "urlset":
            return entries[:MAX_SITEMAP_ENTRIES]

        # sitemap index → fetch children, newest lastmod first.
        # Also include the tail in document order: WordPress-style sitemaps
        # put the newest posts in the highest-numbered child, often w/o lastmod.
        by_lastmod = sorted(entries, key=lambda e: e[1] or date.min, reverse=True)
        picked, seen_children = [], set()
        for child_url, _ in by_lastmod[:MAX_CHILD_SITEMAPS - 2] + entries[-2:]:
            if child_url not in seen_children:
                seen_children.add(child_url)
                picked.append(child_url)
        collected = []
        for child_url in picked:
            child = _get(child_url)
            if not child:
                continue
            child_kind, child_entries = _parse_sitemap_xml(child.text)
            if child_kind == "urlset":
                collected.extend(child_entries)
            if len(collected) >= MAX_SITEMAP_ENTRIES:
                break
        if collected:
            return collected[:MAX_SITEMAP_ENTRIES]
    return []


def _expand_listing_candidates(candidates: list, win_start: date, win_end: date) -> list:
    """Scrape recent listing pages from sitemaps and add article links found inside.

    Some sites keep current articles off the sitemap and only update a blog or
    article listing page. We inspect a small number of those pages but never
    return the listing page itself as a match.
    """
    expanded = []
    seen_urls = {c["url"] for c in candidates}
    fetched = 0

    for candidate in candidates:
        if fetched >= MAX_LISTING_FETCHES:
            break
        if not _is_listing_url(candidate["url"]):
            continue
        cand_date = candidate.get("date")
        if cand_date and (cand_date < win_start or cand_date > win_end):
            continue

        fetched += 1
        for row in _scrape_html(candidate["url"]):
            url = row["url"]
            if url in seen_urls or _is_listing_url(url):
                continue
            seen_urls.add(url)
            context = row.get("context", "") + " " + row.get("title", "")
            expanded.append({
                "title": row["title"],
                "url": url,
                "date": sniff_date(context),
            })

    return expanded + candidates


def find_matches(site_url: str, keywords: list, days: int = 1,
                 date_from: str = "", date_to: str = "",
                 fetch_body: bool = True,
                 max_article_fetches: int = MAX_ARTICLE_FETCHES,
                 require_date: bool = False) -> dict:
    """
    Discover keyword-matching articles on a site without any search API.

    Returns {
      "matches":      [{title, url, date, via}],  # within the date window
      "latest_older": {title, url, date} | None,  # newest match OUTSIDE window
      "method":       "sitemap" | "html" | "none",
      "checked":      int,
    }
    """
    if date_from and date_to:
        try:
            win_start = datetime.strptime(date_from, "%Y-%m-%d").date()
            win_end = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            win_start = date.today() - timedelta(days=days)
            win_end = date.today()
    else:
        win_start = date.today() - timedelta(days=days)
        win_end = date.today()

    norm_keywords = compile_keywords(keywords)
    fetch_budget = max_article_fetches

    entries = _collect_sitemap_entries(site_url)
    method = "sitemap" if entries else "html"

    if entries:
        candidates = [{"title": "", "url": loc, "date": lastmod}
                      for loc, lastmod in entries
                      if urlparse(loc).path.strip("/")]
    else:
        scraped = _scrape_html(site_url)
        # listing pages often print the date next to each link — sniff it
        candidates = [{"title": r["title"], "url": r["url"],
                       "date": sniff_date(r.get("context", "") + " " + r["title"])}
                      for r in scraped]
        if not candidates:
            method = "none"

    candidates = _expand_listing_candidates(candidates, win_start, win_end)

    # newest first; undated last (capped — they cost a page fetch to date)
    dated = sorted([c for c in candidates if c["date"]],
                   key=lambda c: c["date"], reverse=True)
    undated = [c for c in candidates if not c["date"]][:MAX_UNDATED_CANDIDATES]
    candidates = dated + undated

    matches = []
    latest_older = None
    seen_urls = set()
    body_candidates = []

    for c in candidates:
        url = c["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        if _is_listing_url(url):
            continue

        # Some sitemaps expose only numeric URLs and have a slightly stale
        # lastmod. If it is near the window, fetch the article metadata before
        # deciding it is too old.
        if (c["date"] and c["date"] < win_start and not c["title"]
                and c["date"] >= win_start - timedelta(days=2)
                and fetch_budget > 0):
            fetch_budget -= 1
            meta_date, meta_title, _ = _fetch_article_page(url)
            c["date"] = meta_date or c["date"]
            c["title"] = meta_title or c["title"]

        # cheap pre-filter: skip clearly-old dated entries (keep newest-older for reporting)
        if c["date"] and c["date"] < win_start:
            if _matches(c["title"] + " " + _slug_text(url), norm_keywords):
                if not latest_older or c["date"] > latest_older["date"]:
                    latest_older = {"title": c["title"] or _slug_text(url).strip(),
                                    "url": url, "date": c["date"]}
            continue

        title_matched = _matches(c["title"] + " " + _slug_text(url), norm_keywords)
        meta_date, meta_title = None, ""
        if not title_matched and not c["title"] and c["date"] and fetch_budget > 0:
            fetch_budget -= 1
            meta_date, meta_title, _ = _fetch_article_page(url)
            c["date"] = c["date"] or meta_date
            c["title"] = c["title"] or meta_title
            title_matched = _matches(c["title"] + " " + _slug_text(url), norm_keywords)

        if title_matched:
            art_date, art_title = c["date"], c["title"]
            if (not art_date or not art_title) and fetch_budget > 0:
                fetch_budget -= 1
                meta_date, meta_title, _ = _fetch_article_page(url)
                art_date = art_date or meta_date
                art_title = art_title or meta_title
            if require_date and not art_date:
                continue
            if art_date and art_date < win_start:
                if not latest_older or art_date > latest_older["date"]:
                    latest_older = {"title": art_title or _slug_text(url).strip(),
                                    "url": url, "date": art_date}
                continue
            if art_date and art_date > win_end:
                continue
            matches.append({
                "title": art_title or _slug_text(url).strip(),
                "url": url,
                "date": art_date,
                "via": "title",
            })
        elif c["date"]:  # in-window, title didn't match → candidate for body pass
            body_candidates.append(c)

    if fetch_body:
        for c in body_candidates:
            if fetch_budget <= 0:
                break
            fetch_budget -= 1
            meta_date, meta_title, text = _fetch_article_page(c["url"], with_body=True)
            if text and _matches(text, norm_keywords):
                match_date = c["date"] or meta_date
                if require_date and not match_date:
                    continue
                matches.append({
                    "title": meta_title or c["title"] or _slug_text(c["url"]).strip(),
                    "url": c["url"],
                    "date": match_date,
                    "via": "body",
                })

    logger.info(f"[direct] {urlparse(site_url).netloc}: method={method} "
                f"checked={len(seen_urls)} matched={len(matches)}")
    return {
        "matches": matches,
        "latest_older": latest_older,
        "method": method,
        "checked": len(seen_urls),
    }
