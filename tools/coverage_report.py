"""
Per-site coverage diagnostic: tests each site with both intitle and body search,
correctly handles SerpAPI "no results" responses, and reports to Telegram.
Uses both SERPAPI_KEY and SERPAPI_KEY_EN to avoid quota exhaustion.
"""
import argparse
import os
import sys
import time
from urllib.parse import urlparse

import requests
import yaml
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

_ap = argparse.ArgumentParser()
_ap.add_argument("--config", default="config.yaml")
_args, _ = _ap.parse_known_args()

with open(os.path.join(BASE_DIR, _args.config), encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Read credentials from config (falls back to Arabic defaults)
creds     = config.get("credentials", {})
serp_env  = creds.get("serpapi_key_env",    "SERPAPI_KEY")
token_env = creds.get("telegram_token_env", "TELEGRAM_BOT_TOKEN")
chat_env  = creds.get("telegram_chat_env",  "TELEGRAM_CHAT_ID")

# Rotate between two keys to avoid quota exhaustion
_alt_serp = "SERPAPI_KEY_EN" if serp_env == "SERPAPI_KEY" else "SERPAPI_KEY"
SERPAPI_KEYS = [k for k in [
    os.getenv(serp_env,   "").strip(),
    os.getenv(_alt_serp,  "").strip(),
] if k]

BOT_TOKEN   = os.getenv(token_env, "").strip()
CHAT_ID     = os.getenv(chat_env,  "").strip()
SERPAPI_URL = "https://serpapi.com/search"

NO_RESULTS_MSG = "google hasn't returned any results for this query"

if not SERPAPI_KEYS:
    print("No SERPAPI key found"); sys.exit(1)
if not BOT_TOKEN or not CHAT_ID:
    print("Telegram credentials not set"); sys.exit(1)

think_tanks = config["think_tanks"]
keywords    = config["keywords"]

kw_mid      = len(keywords) // 2
kw_intitle  = [keywords[:kw_mid], keywords[kw_mid:]]
kw_body     = [k for k in keywords if " " in k] or keywords[:6]

_key_idx = 0


def _next_key() -> str:
    global _key_idx
    key = SERPAPI_KEYS[_key_idx % len(SERPAPI_KEYS)]
    _key_idx += 1
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


def _serpapi_call(query: str, days: int) -> tuple[int, str]:
    """
    Returns (count, status).
    count >= 0 : results found
    count == -1: quota exhausted → stop all searches
    count == -2: other error
    """
    try:
        resp = requests.get(
            SERPAPI_URL,
            params={
                "api_key": _next_key(),
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
            err = str(data["error"])
            # "no results" is a valid 0-result response, not a real error
            if NO_RESULTS_MSG in err.lower():
                return 0, "ok"
            err_lower = err.lower()
            if "run out" in err_lower or "quota" in err_lower or "credit" in err_lower:
                return -1, "quota"
            return -2, err

        return len(data.get("organic_results", [])), "ok"

    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code == 429:
            time.sleep(10)
            return -1, "rate_limit"
        return -2, f"HTTP {code}"
    except Exception as e:
        return -2, str(e)[:80]


def search_site(site: str, days: int) -> tuple[int, str, str]:
    """
    Returns (total_count, pass_that_found_it, error_msg).
    pass: 'intitle', 'body', or 'none'
    """
    # Pass 1: intitle search (2 keyword batches)
    intitle_count = 0
    for batch in kw_intitle:
        kw_part = " OR ".join(f'intitle:"{k}"' for k in batch)
        count, status = _serpapi_call(f"site:{site} ({kw_part})", days)
        if status == "quota":
            return -1, "", "quota"
        if status != "ok":
            return -2, "", status
        intitle_count += count
        time.sleep(1)

    if intitle_count > 0:
        return intitle_count, "intitle", "ok"

    # Pass 2: body search (broader — catches articles without keyword in title)
    kw_part = " OR ".join(f'"{k}"' for k in kw_body)
    count, status = _serpapi_call(f"site:{site} ({kw_part})", days)
    if status == "quota":
        return -1, "", "quota"
    if status != "ok":
        return -2, "", status
    time.sleep(1)

    if count > 0:
        return count, "body", "ok"

    return 0, "none", "ok"


def main():
    days = int(os.getenv("COVERAGE_DAYS", "14"))
    print(f"Testing {len(think_tanks)} sites — last {days} days — {len(SERPAPI_KEYS)} key(s)\n")
    send_telegram(f"⏳ تست پوشش سایت‌ها ({len(think_tanks)} مرکز، {days} روز) شروع شد...")

    found_intitle = []
    found_body    = []
    empty         = []
    quota_skip    = []
    errors        = []
    quota_hit     = False

    for tt in think_tanks:
        site = tt["url"].replace("https://", "").replace("http://", "").rstrip("/")
        name = tt["name"]

        if quota_hit:
            quota_skip.append((name, site))
            print(f"⏭ {site}: skipped (quota)")
            continue

        count, via, status = search_site(site, days)
        print(f"{'✅' if count > 0 else ('❌' if count == 0 else '⚠')} {site}: "
              f"{f'{count} via {via}' if count > 0 else status if count < 0 else 'no results'}")

        if count > 0 and via == "intitle":
            found_intitle.append((name, site, count))
        elif count > 0 and via == "body":
            found_body.append((name, site, count))
        elif count == 0:
            empty.append((name, site))
        elif count == -1:
            quota_hit = True
            quota_skip.append((name, site))
        else:
            errors.append((name, site, status))

        time.sleep(1)

    total = len(think_tanks)
    found_n = len(found_intitle) + len(found_body)

    lines = [f"<b>📊 گزارش پوشش سایت‌ها ({days} روز)</b>\n"]

    if found_intitle:
        lines.append(f"<b>✅ intitle — کلیدواژه در تیتر ({len(found_intitle)}):</b>")
        for name, _, count in sorted(found_intitle, key=lambda x: -x[2]):
            lines.append(f"  • {name} — {count} نتیجه")

    if found_body:
        lines.append(f"\n<b>🔍 body — کلیدواژه در متن ({len(found_body)}):</b>")
        for name, _, count in sorted(found_body, key=lambda x: -x[2]):
            lines.append(f"  • {name} — {count} نتیجه")

    if empty:
        lines.append(f"\n<b>❌ بدون نتیجه ({len(empty)}/{total}):</b>")
        for name, site in empty:
            lines.append(f"  • {name}\n    ({site})")

    if quota_skip:
        lines.append(f"\n<b>⏸ کوتا تموم شد — تست نشد ({len(quota_skip)}):</b>")
        for name, _ in quota_skip:
            lines.append(f"  • {name}")

    if errors:
        lines.append(f"\n<b>⚠️ خطا ({len(errors)}):</b>")
        for name, _, err in errors:
            lines.append(f"  • {name}: {err[:60]}")

    lines.append(f"\n<b>جمع: {found_n}/{total} دارای نتیجه</b>")

    msg = "\n".join(lines)
    for chunk in [msg[i:i+3900] for i in range(0, len(msg), 3900)]:
        send_telegram(chunk)
        time.sleep(1)

    print(f"\nDone. intitle:{len(found_intitle)} body:{len(found_body)} "
          f"empty:{len(empty)} quota:{len(quota_skip)} error:{len(errors)}")


if __name__ == "__main__":
    main()
