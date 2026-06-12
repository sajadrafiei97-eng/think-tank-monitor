import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
TAVILY_URL = "https://api.tavily.com/search"
SERPAPI_URL = "https://serpapi.com/search"


_NON_CONTENT_EXTS = {'.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.zip', '.rar'}
_INDEX_PAGE_RE = re.compile(r'/(index|default)\.(aspx?|html?|php)$', re.IGNORECASE)


def _is_report_url(url: str) -> bool:
    """Return False for file downloads and generic listing/index pages."""
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in _NON_CONTENT_EXTS):
        return False
    if _INDEX_PAGE_RE.search(path):
        return False
    return True


def _domain(url: str) -> str:
    # Accepts full URLs and bare domains ("rawabetcenter.com" has no netloc
    # when parsed directly — re-parse with a // prefix)
    netloc = urlparse(url).netloc or urlparse("//" + url).netloc
    return netloc.removeprefix("www.")


def _is_allowed(url: str, allowed_domains: set) -> bool:
    d = _domain(url)
    return any(d == a or d.endswith("." + a) for a in allowed_domains)


def google_search(api_key: str, cse_id: str, sites: list, keywords: list,
                  days: int = 1, title_only: bool = False) -> list:
    results = []
    site_part = " OR ".join(f"site:{s}" for s in sites)

    # Split keywords into 2 batches to stay within query length limits
    mid = len(keywords) // 2
    queries = []
    for batch in [keywords[:mid], keywords[mid:]]:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in batch)
        queries.append(f"({site_part}) ({kw_part})")

    if not title_only:
        # body pass — same keyword subset the other engines use
        body_kws = [k for k in keywords if " " in k] or keywords[:6]
        kw_part = " OR ".join(f'"{k}"' for k in body_kws)
        queries.append(f"({site_part}) ({kw_part})")

    for query in queries:
        try:
            resp = requests.get(
                GOOGLE_CSE_URL,
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": 10,
                    "dateRestrict": f"d{days}",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])

            for item in items:
                results.append({
                    "title": item.get("title", "").strip(),
                    "url": item.get("link", "").strip(),
                })

            logger.info(f"Google batch: {len(items)} results")

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                logger.warning("Google CSE: quota exceeded")
            else:
                logger.warning(f"Google CSE HTTP error: {e}")
        except Exception as e:
            logger.warning(f"Google CSE failed: {e}")

    return results


def tavily_search(api_key: str, sites: list, keywords: list, days: int = 1) -> list:
    # Use most distinctive keywords (length > 4 chars, prefer multi-word)
    ranked = sorted(keywords, key=lambda k: (len(k.split()) > 1, len(k)), reverse=True)
    query_keywords = ranked[:12]
    query = " OR ".join(f'"{k}"' for k in query_keywords)

    domains = [_domain(s) for s in sites]

    try:
        resp = requests.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "include_domains": domains,
                "max_results": 20,
                "topic": "news",
                "days": days,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("results", [])

        results = [
            {"title": r.get("title", "").strip(), "url": r.get("url", "").strip()}
            for r in items
            if r.get("url")
        ]

        logger.info(f"Tavily: {len(results)} results")
        return results

    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            logger.warning("Tavily: invalid API key")
        elif e.response is not None and e.response.status_code == 429:
            logger.warning("Tavily: quota exceeded")
        else:
            body = e.response.text[:200] if e.response is not None else ""
            logger.warning(f"Tavily HTTP error: {e} — {body}")
    except Exception as e:
        logger.warning(f"Tavily failed: {e}")

    return []


def _make_tbs(days: int = 1, date_from: str = "", date_to: str = "") -> str:
    if date_from and date_to:
        try:
            s = datetime.strptime(date_from, "%Y-%m-%d")
            e = datetime.strptime(date_to,   "%Y-%m-%d")
        except ValueError as exc:
            logger.warning(f"Invalid date range ({date_from} / {date_to}): {exc} — falling back to {days}d")
            return _make_tbs(days)
        return (f"cdr:1,cd_min:{s.month}/{s.day}/{s.year},"
                f"cd_max:{e.month}/{e.day}/{e.year}")
    return f"qdr:d{days}"


def _serpapi_call(api_key: str, query: str, tbs: str = "", hl: str = "ar",
                  gl: str = "eg", num: int = 20) -> list:
    params = {
        "api_key": api_key,
        "engine": "google",
        "q": query,
        "num": num,
        "hl": hl,
        "gl": gl,
    }
    if tbs:
        params["tbs"] = tbs
    try:
        resp = requests.get(
            SERPAPI_URL,
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            logger.warning(f"SerpAPI error: {data['error']}")
            return []

        items = data.get("organic_results", [])
        logger.info(f"SerpAPI query: {len(items)} results")
        return [
            {"title": r.get("title", "").strip(), "url": r.get("link", "").strip()}
            for r in items if r.get("title") and r.get("link")
        ]

    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code == 401:
            logger.warning("SerpAPI: invalid API key")
        elif code == 429:
            logger.warning("SerpAPI: quota exceeded")
        else:
            logger.warning(f"SerpAPI HTTP error: {e}")
    except Exception as e:
        logger.warning(f"SerpAPI failed: {e}")

    return []


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


_SITE_BATCH = 3  # sites per sub-query — balance between coverage and competition


def serpapi_search(api_key: str, sites: list, keywords: list, tbs: str = None,
                   hl: str = "ar", gl: str = "eg", days: int = 1,
                   date_from: str = "", date_to: str = "",
                   title_only: bool = False) -> list:
    date_filter = tbs if tbs is not None else _make_tbs(days, date_from, date_to)
    allowed_domains = {_domain(s) for s in sites}

    results = []
    seen_normalized = set()

    def _add_filtered(items):
        skipped = 0
        for r in items:
            url = r["url"]
            if not _is_allowed(url, allowed_domains):
                skipped += 1
                logger.debug(f"Filtered out non-allowed domain: {_domain(url)}")
                continue
            if not _is_report_url(url):
                skipped += 1
                logger.debug(f"Filtered out non-report URL: {url}")
                continue
            norm = _normalize_url(url)
            if norm not in seen_normalized:
                seen_normalized.add(norm)
                results.append(r)
        if skipped:
            logger.info(f"  Filtered {skipped} result(s) (domain/pdf/index)")

    site_batches = [sites[i:i+_SITE_BATCH] for i in range(0, len(sites), _SITE_BATCH)]

    # Pass 1: intitle search — 2 keyword batches × N site batches
    mid = len(keywords) // 2
    for site_batch in site_batches:
        site_part = " OR ".join(f"site:{s}" for s in site_batch)
        for kw_batch in [keywords[:mid], keywords[mid:]]:
            kw_part = " OR ".join(f'intitle:"{k}"' for k in kw_batch)
            _add_filtered(_serpapi_call(api_key, f"({site_part}) ({kw_part})",
                                        date_filter, hl, gl))

    logger.info(f"Pass 1 (intitle): {len(results)} results")

    if not title_only:
        # Pass 2: body search — catches articles where keyword is in text not title
        body_kws = [k for k in keywords if " " in k] or keywords[:6]
        kw_body = " OR ".join(f'"{k}"' for k in body_kws)
        for site_batch in site_batches:
            site_part = " OR ".join(f"site:{s}" for s in site_batch)
            _add_filtered(_serpapi_call(api_key, f"({site_part}) ({kw_body})",
                                        date_filter, hl, gl))
        logger.info(f"Pass 1+2 total: {len(results)} results")

    return results


def serpapi_user_query(api_key: str, sites: list, keywords: list,
                       days: int = 1, date_from: str = "", date_to: str = "",
                       title_only: bool = False, hl: str = "ar",
                       gl: str = "eg") -> list:
    """
    The operator-specified single Google query — one SerpAPI call per run:

      (site:a OR site:b ...) (intitle:"k1" OR ...) after:YYYY-MM-DD before:YYYY-MM-DD

    Google's own after/before operators decide the date window; whatever
    Google returns (filtered to allowed domains, no files/index pages) is
    what gets sent. No client-side date guessing.
    """
    today = datetime.now().date()
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError as exc:
            logger.warning(f"Invalid date range ({date_from}/{date_to}): {exc} "
                           f"— falling back to last {days} day(s)")
            start, end = today - timedelta(days=days), today
        # explicit ranges are inclusive → widen by 1 day on each side
        # because Google's after/before are exclusive
        after, before = start - timedelta(days=1), end + timedelta(days=1)
    else:
        # "last N days": after:(today-N) excludes day N+1 back, includes today
        after, before = today - timedelta(days=days), today + timedelta(days=1)

    site_part = " OR ".join(f"site:{s}" for s in sites)
    if title_only:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in keywords)
    else:
        kw_part = " OR ".join(f'"{k}"' for k in keywords)
    query = f"({site_part}) ({kw_part}) after:{after} before:{before}"
    logger.info(f"Single-query mode ({'title' if title_only else 'full'}), "
                f"window {after} → {before} (exclusive)")

    items = _serpapi_call(api_key, query, hl=hl, gl=gl, num=50)
    if len(items) >= 50:
        logger.warning("Result page saturated (50) — some results may be cut off")

    allowed_domains = {_domain(s) for s in sites}
    results, seen_norm = [], set()
    for r in items:
        url = r["url"]
        if not _is_allowed(url, allowed_domains) or not _is_report_url(url):
            continue
        norm = _normalize_url(url)
        if norm not in seen_norm:
            seen_norm.add(norm)
            results.append(r)
    logger.info(f"Single-query results: {len(results)} (of {len(items)} raw)")
    return results


def search_all(google_api_key: str, google_cse_id: str, tavily_api_key: str,
               sites: list, keywords: list, serpapi_key: str = "",
               hl: str = "ar", gl: str = "eg", days: int = 1,
               date_from: str = "", date_to: str = "",
               title_only: bool = False) -> list:
    all_results = []
    seen_urls = set()

    def _add(items):
        for r in items:
            url = r.get("url", "")
            if url and url not in seen_urls and _is_report_url(url):
                seen_urls.add(url)
                all_results.append(r)

    custom_range = bool(date_from and date_to)

    if not google_api_key or not google_cse_id:
        logger.info("Google CSE: skipped (no credentials)")
    elif custom_range:
        logger.info("Google CSE: skipped (custom date range not supported)")
    else:
        logger.info("Running Google CSE search...")
        _add(google_search(google_api_key, google_cse_id, sites, keywords,
                           days=days, title_only=title_only))

    if not tavily_api_key:
        logger.info("Tavily: skipped (no credentials)")
    elif custom_range:
        logger.info("Tavily: skipped (custom date range not supported)")
    else:
        logger.info("Running Tavily search...")
        tv = tavily_search(tavily_api_key, sites, keywords, days=days)
        if title_only and tv:
            # Tavily has no intitle operator — enforce title mode client-side
            from direct_fetch import compile_keywords, _matches
            ck = compile_keywords(keywords)
            kept = [r for r in tv if _matches(r.get("title", ""), ck)]
            logger.info(f"Tavily title filter: {len(tv)} → {len(kept)}")
            tv = kept
        _add(tv)

    if serpapi_key:
        logger.info(f"Running SerpAPI search (title_only={title_only})...")
        _add(serpapi_search(serpapi_key, sites, keywords, hl=hl, gl=gl,
                            days=days, date_from=date_from, date_to=date_to,
                            title_only=title_only))
    else:
        logger.info("SerpAPI: skipped (no credentials)")

    logger.info(f"Combined unique results: {len(all_results)}")
    return all_results
