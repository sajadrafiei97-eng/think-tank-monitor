import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
key = os.getenv("SERPAPI_KEY", "")

sites = ["agsiw.org", "ecss.com.eg", "epc.ae", "hewariraq.com", "orouba.ps", "trendsgroup.org"]
keywords = "ايران OR إيران OR الحرس الثوري OR طهران OR خامنئي OR هرمز"

print(f"{'سایت':<30} {'indexed?':<12} {'نتایج بدون تاریخ':<20} {'نتایج ۲۴ ساعت'}")
print("-" * 80)

for site in sites:
    # Test 1: no date filter (all time)
    r1 = requests.get("https://serpapi.com/search", params={
        "api_key": key, "engine": "google",
        "q": f"site:{site} ({keywords})",
        "num": 5, "hl": "ar",
    }, timeout=20)
    d1 = r1.json()
    count_all = len(d1.get("organic_results", []))
    total_all = d1.get("search_information", {}).get("total_results", "?")

    # Test 2: last 24 hours
    r2 = requests.get("https://serpapi.com/search", params={
        "api_key": key, "engine": "google",
        "q": f"site:{site} ({keywords})",
        "num": 5, "hl": "ar", "tbs": "qdr:d",
    }, timeout=20)
    d2 = r2.json()
    count_24h = len(d2.get("organic_results", []))

    indexed = "✓" if count_all > 0 else "✗ نه"
    print(f"{site:<30} {indexed:<12} {str(count_all)+' ('+str(total_all)+')':<20} {count_24h}")
