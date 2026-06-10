import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
from dotenv import load_dotenv
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
key = os.getenv("SERPAPI_KEY_EN", "")

sites = [
    "meforum.org", "mei.edu", "stimson.org", "rasanah-iiis.org",
    "ispionline.it", "crisisgroup.org", "isis-online.org", "rand.org",
    "hudson.org", "epc.ae", "csis.org", "agsi.org",
    "nationalinterest.org", "newlinesinstitute.org", "belfercenter.org",
]
keywords = "iran OR iranian OR tehran OR khamenei OR hormuz OR pezeshkian"

print(f"\n{'SITE':<35} {'All-time':<12} {'Last 24h'}")
print("-" * 62)

for site in sites:
    # All-time
    r1 = requests.get("https://serpapi.com/search", params={
        "api_key": key, "engine": "google",
        "q": f"site:{site} intitle:({keywords})",
        "num": 5, "hl": "en",
    }, timeout=20)
    c_all = len(r1.json().get("organic_results", []))

    # Last 24h
    r2 = requests.get("https://serpapi.com/search", params={
        "api_key": key, "engine": "google",
        "q": f"site:{site} intitle:({keywords})",
        "num": 5, "hl": "en", "tbs": "qdr:d",
    }, timeout=20)
    c_24h = len(r2.json().get("organic_results", []))

    mark_all = f"✓ {c_all}" if c_all else "—"
    mark_24h = f"✓ {c_24h}" if c_24h else "—"
    print(f"{site:<35} {mark_all:<12} {mark_24h}")

print()
