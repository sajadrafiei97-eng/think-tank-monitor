# -*- coding: utf-8 -*-
"""
پایش روزانه اندیشکده‌های عربی
جستجو در Google برای یافتن یادداشت‌های مرتبط با ایران
ارسال لینک‌ها به تلگرام
"""

import requests
import json
import os
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# تنظیمات
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_articles.json")

# ─────────────────────────────────────────────
# سایت‌ها
# ─────────────────────────────────────────────
SITES = [
    "rawabetcenter.com", "eurasiaar.org", "bayancenter.org",
    "afaip.com", "ecss.com.eg", "alzaytouna.net", "caus.org.lb",
    "agsi.org", "truestudies.org", "trendsgroup.org",
    "europarabct.com", "rasanah-iiis.org", "democraticac.de",
    "studies.aljazeera.net", "orouba.ps", "hewariraq.com",
    "dimensionscenter.net", "acpss.ahram.org.eg", "futureuae.com",
    "dohainstitute.org", "raseef22.net", "epc.ae",
]

# ─────────────────────────────────────────────
# کلیدواژه‌ها
# ─────────────────────────────────────────────
KEYWORDS = [
    "ايران", "إيران", "ايرانية", "إيرانية",
    "ايرانيون", "إيرانيون", "ايرانيين", "إيرانيين",
    "الايراني", "الإيراني", "الحرس الثوري",
    "الجمهورية الاسلامية", "الجمهورية الإسلامية",
    "المرشد الاعلى", "المرشد الأعلى",
    "خامنئي", "خامنائي", "مضيق هرمز", "هرمز", "طهران",
]


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=2)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if not resp.ok:
            print(f"  خطای تلگرام: {resp.text[:200]}")
    except Exception as e:
        print(f"  خطا در ارسال تلگرام: {e}")
    time.sleep(0.4)


def search_articles(today):
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            print("  خطا: کتابخانه ddgs نصب نیست. دستور: pip install ddgs")
            return []

    sites_q  = " OR ".join([f"site:{s}" for s in SITES])
    kw_q     = " OR ".join([f'"{k}"' for k in KEYWORDS])
    query    = f"({sites_q}) ({kw_q}) after:{today} before:{today}"

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=100, timelimit="d"):
                link  = r.get("href", "")
                title = r.get("title", "")
                # فقط از سایت‌های هدف
                if any(s in link for s in SITES):
                    results.append({"title": title, "link": link})
    except Exception as e:
        print(f"  خطای جستجو: {e}")
    return results


def main():
    today   = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*50}\n  پایش — {now_str}\n{'='*50}")

    seen = load_seen()
    results = search_articles(today)
    print(f"  {len(results)} نتیجه یافت شد.")

    new_articles = [r for r in results if r["link"] not in seen]
    for r in new_articles:
        seen.add(r["link"])
    print(f"  {len(new_articles)} مورد جدید.")

    if new_articles:
        send_telegram(
            f"📡 <b>پایش اندیشکده‌ها</b>\n"
            f"🗓 {now_str}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"یادداشت‌های جدید: <b>{len(new_articles)}</b> مورد"
        )
        # گروه‌بندی بر اساس سایت
        by_site = {}
        for r in new_articles:
            for s in SITES:
                if s in r["link"]:
                    by_site.setdefault(s, []).append(r)
                    break
        for site, items in by_site.items():
            lines = [f"🔹 <b>{site}</b>\n"]
            for item in items[:8]:
                lines.append(f'• <a href="{item["link"]}">{item["title"][:120]}</a>')
            send_telegram("\n".join(lines))
            time.sleep(0.3)
        print(f"  ✅ ارسال به تلگرام انجام شد.")
    else:
        send_telegram(f"📭 <b>پایش {now_str}</b>\nیادداشت جدید مرتبط با ایران یافت نشد.")
        print("  📭 موردی جدید نبود.")

    save_seen(seen)


if __name__ == "__main__":
    main()
