"""
Per-site coverage diagnostic: tests each site individually with a 30-day window
and reports which sites return results in Google's index via SerpAPI.
Results are sent to Telegram.
"""
import os
import sys
import time
from urllib.parse import urlparse

import requests
import yaml
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SERPAPI_URL = "https://serpapi.com/search"

if not SERPAPI_KEY:
    print("SERPAPI_KEY not set"); sys.exit(1)
if not BOT_TOKEN or not CHAT_ID:
    print("Telegram credentials not set"); sys.exit(1)

with open(os.path.join(BASE_DIR, "config.yaml"), encoding="utf-8") as f:
    config = yaml.safe_load(f)

think_tanks = config["think_tanks"]
keywords = config["keywords"]

# Two representative keyword groups
kw_mid = len(keywords) // 2
kw_batches = [keywords[:kw_mid], keywords[kw_mid:]]


def _domain(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.")


def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


def search_site(site: str, days: int = 30) -> int:
    """Return total result count for a site across both keyword batches."""
    total = 0
    for kw_batch in kw_batches:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in kw_batch)
        query = f"site:{site} ({kw_part})"
        try:
            resp = requests.get(
                SERPAPI_URL,
                params={
                    "api_key": SERPAPI_KEY,
                    "engine": "google",
                    "q": query,
                    "num": 10,
                    "tbs": f"qdr:d{days}",
                    "hl": "ar",
                    "gl": "eg",
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                print(f"  SerpAPI error for {site}: {data['error']}")
                return -1
            items = data.get("organic_results", [])
            total += len(items)
        except Exception as e:
            print(f"  Request error for {site}: {e}")
            return -1
        time.sleep(0.5)  # avoid rate limiting
    return total


def main():
    days = int(os.getenv("COVERAGE_DAYS", "30"))
    print(f"Testing {len(think_tanks)} sites over last {days} days...\n")

    send_telegram(f"⏳ تست پوشش سایت‌ها ({len(think_tanks)} مرکز، {days} روز گذشته) شروع شد...")

    results = []
    for tt in think_tanks:
        site = tt["url"].replace("https://", "").replace("http://", "").rstrip("/")
        name = tt["name"]
        count = search_site(site, days)
        status = "✅" if count > 0 else ("❓" if count == -1 else "❌")
        label = f"{count} نتیجه" if count > 0 else ("خطا" if count == -1 else "بدون نتیجه")
        results.append((status, name, site, label, count))
        print(f"{status} {site}: {label}")
        time.sleep(0.5)

    # Build report
    found = [r for r in results if r[4] > 0]
    missing = [r for r in results if r[4] == 0]
    error = [r for r in results if r[4] == -1]

    lines = [f"<b>📊 گزارش پوشش سایت‌ها ({days} روز گذشته)</b>\n"]

    if found:
        lines.append(f"<b>✅ دارای نتیجه ({len(found)}/{len(think_tanks)}):</b>")
        for _, name, site, label, _ in sorted(found, key=lambda x: -x[4]):
            lines.append(f"  • {name} — {label}")

    if missing:
        lines.append(f"\n<b>❌ بدون نتیجه ({len(missing)}/{len(think_tanks)}):</b>")
        for _, name, site, _, _ in missing:
            lines.append(f"  • {name}\n    ({site})")

    if error:
        lines.append(f"\n<b>❓ خطا ({len(error)}):</b>")
        for _, name, site, _, _ in error:
            lines.append(f"  • {name}")

    msg = "\n".join(lines)

    # Split if too long for Telegram (4096 char limit)
    if len(msg) > 4000:
        chunks = [msg[i:i+3900] for i in range(0, len(msg), 3900)]
        for chunk in chunks:
            send_telegram(chunk)
            time.sleep(1)
    else:
        send_telegram(msg)

    print(f"\nDone. Found: {len(found)}, Missing: {len(missing)}, Error: {len(error)}")


if __name__ == "__main__":
    main()
