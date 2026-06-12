"""
Per-site coverage diagnostic: tests each site individually and reports
which sites return results via SerpAPI. Sends results to Telegram.
Uses both SERPAPI_KEY and SERPAPI_KEY_EN to avoid quota exhaustion.
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

# Support two SERPAPI keys — rotate between them to avoid quota exhaustion
SERPAPI_KEYS = [k for k in [
    os.getenv("SERPAPI_KEY", "").strip(),
    os.getenv("SERPAPI_KEY_EN", "").strip(),
] if k]

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SERPAPI_URL = "https://serpapi.com/search"

if not SERPAPI_KEYS:
    print("No SERPAPI key found"); sys.exit(1)
if not BOT_TOKEN or not CHAT_ID:
    print("Telegram credentials not set"); sys.exit(1)

with open(os.path.join(BASE_DIR, "config.yaml"), encoding="utf-8") as f:
    config = yaml.safe_load(f)

think_tanks = config["think_tanks"]
keywords    = config["keywords"]

kw_mid = len(keywords) // 2
kw_batches = [keywords[:kw_mid], keywords[kw_mid:]]

_key_index = 0


def _next_key() -> str:
    global _key_index
    key = SERPAPI_KEYS[_key_index % len(SERPAPI_KEYS)]
    _key_index += 1
    return key


def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


def search_site(site: str, days: int) -> tuple[int, str]:
    """
    Returns (count, status):
      count >= 0 : number of results found
      count == -1: quota exhausted
      count == -2: other API error
    """
    total = 0
    for kw_batch in kw_batches:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in kw_batch)
        query   = f"site:{site} ({kw_part})"
        api_key = _next_key()
        try:
            resp = requests.get(
                SERPAPI_URL,
                params={
                    "api_key": api_key,
                    "engine": "google",
                    "q": query,
                    "num": 10,
                    "tbs": f"qdr:d{days}",
                    "hl": "ar",
                    "gl": "eg",
                },
                timeout=25,
            )
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                err = data["error"].lower()
                if "run out" in err or "quota" in err or "credit" in err:
                    print(f"  QUOTA exhausted for {site}")
                    return -1, "quota"
                print(f"  API error for {site}: {data['error']}")
                return -2, data["error"]

            total += len(data.get("organic_results", []))

        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code == 429:
                print(f"  Rate limit for {site}, waiting 10s...")
                time.sleep(10)
                return -1, "rate_limit"
            print(f"  HTTP {code} for {site}: {e}")
            return -2, str(e)
        except Exception as e:
            print(f"  Error for {site}: {e}")
            return -2, str(e)

        time.sleep(1)  # 1s between keyword batches

    return total, "ok"


def main():
    days = int(os.getenv("COVERAGE_DAYS", "7"))
    print(f"Testing {len(think_tanks)} sites — last {days} days — {len(SERPAPI_KEYS)} key(s)\n")

    send_telegram(f"⏳ تست پوشش سایت‌ها ({len(think_tanks)} مرکز، {days} روز گذشته) شروع شد...")

    found   = []
    empty   = []
    quota   = []
    errors  = []
    quota_hit = False

    for tt in think_tanks:
        site = tt["url"].replace("https://", "").replace("http://", "").rstrip("/")
        name = tt["name"]

        if quota_hit:
            quota.append((name, site))
            print(f"⏭ {site}: skipped (quota)")
            continue

        count, status = search_site(site, days)
        print(f"{'✅' if count > 0 else ('❌' if count == 0 else '⚠')}"
              f" {site}: {count if count >= 0 else status}")

        if count > 0:
            found.append((name, site, count))
        elif count == 0:
            empty.append((name, site))
        elif status == "quota" or status == "rate_limit":
            quota_hit = True
            quota.append((name, site))
        else:
            errors.append((name, site, status))

        time.sleep(1.5)

    # Build Telegram report
    total = len(think_tanks)
    lines = [f"<b>📊 گزارش پوشش سایت‌ها ({days} روز)</b>\n"]

    if found:
        lines.append(f"<b>✅ دارای نتیجه ({len(found)}/{total}):</b>")
        for name, site, count in sorted(found, key=lambda x: -x[2]):
            lines.append(f"  • {name} — {count} نتیجه")

    if empty:
        lines.append(f"\n<b>❌ بدون نتیجه ({len(empty)}/{total}):</b>")
        for name, site in empty:
            lines.append(f"  • {name}\n    ({site})")

    if quota:
        lines.append(f"\n<b>⏸ کوتا تموم شد — تست نشد ({len(quota)}):</b>")
        for name, site in quota:
            lines.append(f"  • {name}")

    if errors:
        lines.append(f"\n<b>⚠️ خطای دیگر ({len(errors)}):</b>")
        for name, site, err in errors:
            lines.append(f"  • {name}: {err[:60]}")

    msg = "\n".join(lines)
    chunks = [msg[i:i+3900] for i in range(0, len(msg), 3900)]
    for chunk in chunks:
        send_telegram(chunk)
        time.sleep(1)

    print(f"\nDone. Found:{len(found)}  Empty:{len(empty)}  Quota:{len(quota)}  Error:{len(errors)}")


if __name__ == "__main__":
    main()
