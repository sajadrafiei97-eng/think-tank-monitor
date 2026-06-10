"""
Coverage test: searches last 30 days (no Telegram) to show which of the 22 sites
return Iran-related results in Google's index.
"""
import io
import os
import sys
from collections import defaultdict
from urllib.parse import urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yaml
from dotenv import load_dotenv

from search_tool import serpapi_search

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

serpapi_key = os.getenv("SERPAPI_KEY", "").strip()
if not serpapi_key:
    print("SERPAPI_KEY not set in .env")
    sys.exit(1)

with open(os.path.join(BASE_DIR, "config.yaml"), encoding="utf-8") as f:
    config = yaml.safe_load(f)

think_tanks = config["think_tanks"]
keywords = config["keywords"]
sites = [tt["url"].replace("https://", "").replace("http://", "").rstrip("/") for tt in think_tanks]
domain_to_name = {
    urlparse(tt["url"]).netloc.lstrip("www."): tt["name"]
    for tt in think_tanks
}

print("Searching last 30 days across all 22 sites...\n")

# Use last-month filter for broad coverage test
results = serpapi_search(serpapi_key, sites, keywords, tbs="qdr:m")

# Group by domain
by_domain = defaultdict(list)
for r in results:
    domain = urlparse(r["url"]).netloc.lstrip("www.")
    by_domain[domain].append(r["title"])

# Show which sites have results
found_domains = set(by_domain.keys())
all_domains = set(domain_to_name.keys())

print(f"{'SITE':<40} intitle  body-only")
print("-" * 70)

# Second pass: body-only search (no intitle) for sites with no results
missing = all_domains - found_domains
if missing:
    site_part2 = " OR ".join(f"site:{d}" for d in missing)
    kw_sample = " OR ".join(f'"{k}"' for k in keywords[:8])
    query2 = f"({site_part2}) ({kw_sample})"
    try:
        import requests as _req
        r2 = _req.get(
            "https://serpapi.com/search",
            params={"api_key": serpapi_key, "engine": "google",
                    "q": query2, "num": 10, "tbs": "qdr:y", "hl": "ar"},
            timeout=20,
        )
        r2.raise_for_status()
        for item in r2.json().get("organic_results", []):
            d = urlparse(item.get("link", "")).netloc.lstrip("www.")
            by_domain["body:" + d].append(item.get("title", ""))
    except Exception as e:
        print(f"  body-only search error: {e}")

for domain in sorted(domain_to_name.keys()):
    intitle_mark = f"✓ {len(by_domain[domain])}" if domain in found_domains else "—"
    body_mark = f"✓ {len(by_domain['body:'+domain])}" if ("body:" + domain) in by_domain else ("—" if domain not in found_domains else "")
    print(f"{domain:<40} {intitle_mark:<8} {body_mark}")

print(f"\nintitle پوشش: {len(found_domains)}/22   body پوشش: {len(found_domains | {d[5:] for d in by_domain if d.startswith('body:')})}/22")
