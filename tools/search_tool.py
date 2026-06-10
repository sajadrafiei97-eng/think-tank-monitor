import logging
from datetime import datetime
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
TAVILY_URL = "https://api.tavily.com/search"
SERPAPI_URL = "https://serpapi.com/search"


def _domain(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.")


def _is_allowed(url: str, allowed_domains: set) -> bool:
    d = _domain(url)
    return any(d == a or d.endswith("." + a) for a in allowed_domains)


def google_search(api_key: str, cse_id: str, sites: list, keywords: list) -> list:
    results = []
    site_part = " OR ".join(f"site:{s}" for s in sites)

    # Split keywords into 2 batches to stay within query length limits
    mid = len(keywords) // 2
    batches = [keywords[:mid], keywords[mid:]]

    for batch in batches:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in batch)
        query = f"({site_part}) ({kw_part})"

        try:
            resp = requests.get(
                GOOGLE_CSE_URL,
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": 10,
                    "dateRestrict": "d1",
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


def tavily_search(api_key: str, sites: list, keywords: list) -> list:
    # Use most distinctive keywords (length > 4 chars, prefer multi-word)
    ranked = sorted(keywords, key=lambda k: (len(k.split()) > 1, len(k)), reverse=True)
    query_keywords = ranked[:12]
    query = " OR ".join(f'"{k}"' for k in query_keywords)

    domains = [_domain(s) for s in sites]

    try:
        resp = requests.post(
            TAVILY_URL,
            json={
                "api_key": api_key,
                "query": query,
                "include_domains": domains,
                "max_results": 20,
                "topic": "news",
                "days": 1,
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
            logger.warning(f"Tavily HTTP error: {e}")
    except Exception as e:
        logger.warning(f"Tavily failed: {e}")

    return []


def _make_tbs(days: int = 1, date_from: str = "", date_to: str = "") -> str:
    if date_from and date_to:
        s = datetime.strptime(date_from, "%Y-%m-%d")
        e = datetime.strptime(date_to,   "%Y-%m-%d")
        return (f"cdr:1,cd_min:{s.month}/{s.day}/{s.year},"
                f"cd_max:{e.month}/{e.day}/{e.year}")
    if days == 1:
        t = datetime.now()
        d = f"{t.month}/{t.day}/{t.year}"
        return f"cdr:1,cd_min:{d},cd_max:{d}"
    return f"qdr:d{days}"


def _serpapi_call(api_key: str, query: str, tbs: str, hl: str = "ar", gl: str = "eg") -> list:
    try:
        resp = requests.get(
            SERPAPI_URL,
            params={
                "api_key": api_key,
                "engine": "google",
                "q": query,
                "num": 10,
                "tbs": tbs,
                "hl": hl,
                "gl": gl,
            },
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
    host = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def serpapi_search(api_key: str, sites: list, keywords: list, tbs: str = None,
                   hl: str = "ar", gl: str = "eg", days: int = 1,
                   date_from: str = "", date_to: str = "") -> list:
    date_filter = tbs if tbs is not None else _make_tbs(days, date_from, date_to)
    site_part = " OR ".join(f"site:{s}" for s in sites)
    allowed_domains = {s.lstrip("www.") for s in sites}

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
            norm = _normalize_url(url)
            if norm not in seen_normalized:
                seen_normalized.add(norm)
                results.append(r)
        if skipped:
            logger.info(f"  Filtered {skipped} result(s) from non-listed domains")

    # Pass 1: intitle search (2 keyword batches)
    mid = len(keywords) // 2
    for batch in [keywords[:mid], keywords[mid:]]:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in batch)
        query = f"({site_part}) ({kw_part})"
        _add_filtered(_serpapi_call(api_key, query, date_filter, hl, gl))

    logger.info(f"Pass 1 (intitle): {len(results)} results")

    # Pass 2: body search — catches sites not well-covered by intitle
    body_kws = [k for k in keywords if " " in k] or keywords[:6]
    kw_body = " OR ".join(f'"{k}"' for k in body_kws)
    query_body = f"({site_part}) ({kw_body})"
    _add_filtered(_serpapi_call(api_key, query_body, date_filter, hl, gl))

    logger.info(f"Pass 1+2 total: {len(results)} results")
    return results


def search_all(google_api_key: str, google_cse_id: str, tavily_api_key: str,
               sites: list, keywords: list, serpapi_key: str = "",
               hl: str = "ar", gl: str = "eg", days: int = 1,
               date_from: str = "", date_to: str = "") -> list:
    all_results = []
    seen_urls = set()

    def _add(items):
        for r in items:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    if google_api_key and google_cse_id:
        logger.info("Running Google CSE search...")
        _add(google_search(google_api_key, google_cse_id, sites, keywords))
    else:
        logger.info("Google CSE: skipped (no credentials)")

    if tavily_api_key:
        logger.info("Running Tavily search...")
        _add(tavily_search(tavily_api_key, sites, keywords))
    else:
        logger.info("Tavily: skipped (no credentials)")

    if serpapi_key:
        logger.info("Running SerpAPI search...")
        _add(serpapi_search(serpapi_key, sites, keywords, hl=hl, gl=gl,
                            days=days, date_from=date_from, date_to=date_to))
    else:
        logger.info("SerpAPI: skipped (no credentials)")

    logger.info(f"Combined unique results: {len(all_results)}")
    return all_results
