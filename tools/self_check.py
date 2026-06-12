"""
Weekly self-check: verifies every part of the monitor and reports to Telegram.
Runs Wednesdays 9:15 Tehran (05:45 UTC) via .github/workflows/selfcheck.yml,
or manually:  python tools/self_check.py [--dry-run]

Checks: tool compilation, config validity, SerpAPI quota on both keys,
yesterday's scheduled run, bot-listener freshness, seen-file integrity,
and site reachability. Sends ✅/⚠️ summary to the Arabic bot (falls back
to the English bot). Exits 1 when problems were found.
"""
import argparse
import glob
import json
import os
import py_compile
import sys
from datetime import datetime, timedelta, timezone

import requests
import yaml
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

REPO = "sajadrafiei97-eng/think-tank-monitor"
HEADERS_UA = {"User-Agent": "Mozilla/5.0 (compatible; ThinkTankMonitor/1.0)"}

problems = []   # things that need attention
notes = []      # informational lines


def check_tools_compile():
    for path in sorted(glob.glob(os.path.join(BASE_DIR, "tools", "*.py"))):
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as e:
            problems.append(f"کد قابل اجرا نیست: {os.path.basename(path)} — {str(e)[:80]}")


def check_configs():
    configs = []
    for name in ["config.yaml", "config_en.yaml"]:
        path = os.path.join(BASE_DIR, name)
        try:
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            assert cfg.get("think_tanks") and cfg.get("keywords")
            configs.append((name, cfg))
            notes.append(f"پیکربندی {name}: {len(cfg['think_tanks'])} سایت، "
                         f"{len(cfg['keywords'])} کلیدواژه")
        except Exception as e:
            problems.append(f"پیکربندی {name} خراب است: {str(e)[:80]}")
    try:
        with open(os.path.join(BASE_DIR, "config_schedule.json")) as f:
            sched = json.load(f)
        notes.append(f"حالت جستجو: عربی={sched.get('search_mode_arabic', '?')}، "
                     f"انگلیسی={sched.get('search_mode_english', '?')}، "
                     f"ارسال خودکار={'روشن' if sched.get('enabled', True) else 'خاموش'}")
    except Exception as e:
        problems.append(f"فایل زمان‌بندی خراب است: {str(e)[:80]}")
    return configs


def check_serpapi_quota():
    for label, env in [("عربی", "SERPAPI_KEY"), ("انگلیسی", "SERPAPI_KEY_EN")]:
        key = os.getenv(env, "").strip()
        if not key:
            problems.append(f"کلید جستجوی {label} ({env}) تنظیم نشده")
            continue
        try:
            r = requests.get("https://serpapi.com/account",
                             params={"api_key": key}, timeout=20)
            d = r.json()
            left = d.get("total_searches_left")
            if left is None:
                problems.append(f"کلید جستجوی {label}: پاسخ نامعتبر — {str(d)[:60]}")
            elif left < 40:
                problems.append(f"سهمیه جستجوی {label} رو به اتمام: {left} باقی مانده")
            else:
                notes.append(f"سهمیه جستجوی {label}: {left} باقی مانده")
        except Exception as e:
            problems.append(f"بررسی سهمیه {label} ناموفق: {str(e)[:60]}")


def check_github_runs():
    token = os.getenv("GH_TOKEN", "").strip()
    if not token:
        problems.append("توکن گیت‌هاب تنظیم نشده — بررسی اجراها ممکن نیست")
        return
    H = {"Authorization": f"token {token}",
         "Accept": "application/vnd.github.v3+json"}
    now = datetime.now(timezone.utc)

    # last scheduled daily run within ~26h must have succeeded
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/workflows/monitor.yml/runs",
            headers=H, params={"per_page": 10}, timeout=20).json()
        runs = r.get("workflow_runs", [])
        recent = [x for x in runs
                  if (now - datetime.fromisoformat(
                      x["created_at"].replace("Z", "+00:00"))) < timedelta(hours=26)]
        if not recent:
            problems.append("در ۲۶ ساعت گذشته هیچ اجرای پایش انجام نشده")
        else:
            latest = recent[0]
            if latest.get("conclusion") == "success" or latest.get("status") in ("in_progress", "queued"):
                notes.append(f"آخرین اجرای پایش: {latest['created_at'][:16]} — "
                             f"{latest.get('conclusion') or latest.get('status')}")
            else:
                problems.append(f"آخرین اجرای پایش شکست خورده: "
                                f"{latest.get('conclusion')} ({latest['created_at'][:16]})")
    except Exception as e:
        problems.append(f"بررسی اجرای روزانه ناموفق: {str(e)[:60]}")

    # bot listener must have run within the last 20 minutes
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/workflows/bot_listener.yml/runs",
            headers=H, params={"per_page": 1}, timeout=20).json()
        runs = r.get("workflow_runs", [])
        if runs:
            age = now - datetime.fromisoformat(runs[0]["created_at"].replace("Z", "+00:00"))
            if runs[0].get("status") in ("in_progress", "queued") or age < timedelta(minutes=20):
                notes.append("ربات تلگرام: فعال")
            else:
                problems.append(f"ربات تلگرام از {int(age.total_seconds()//60)} دقیقه پیش اجرا نشده")
        else:
            problems.append("هیچ اجرایی از ربات تلگرام یافت نشد")
    except Exception as e:
        problems.append(f"بررسی ربات ناموفق: {str(e)[:60]}")


def check_seen_files():
    for name in [".tmp/seen_urls.json", ".tmp/seen_urls_en.json"]:
        path = os.path.join(BASE_DIR, name)
        if not os.path.exists(path):
            continue  # legitimate on first run
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            notes.append(f"حافظه لینک‌های ارسالی ({name.split('/')[-1]}): {len(data)} لینک")
        except Exception:
            problems.append(f"فایل حافظه خراب است: {name}")


def check_sites(configs):
    down = []
    for cfg_name, cfg in configs:
        for tt in cfg.get("think_tanks", []):
            url = tt["url"]
            try:
                r = requests.get(url, headers=HEADERS_UA, timeout=10,
                                 allow_redirects=True, stream=True)
                code = r.status_code
                r.close()
                if code >= 400 and code != 403:
                    down.append(f"{tt['name'][:35]} — کد {code}")
                # 403 = ضدربات؛ گوگل همچنان پوشش می‌دهد، خرابی نیست
            except Exception:
                down.append(f"{tt['name'][:35]} — در دسترس نیست")
    if down:
        problems.append("سایت‌های غیرقابل دسترس:\n    " + "\n    ".join(down))


def send_report(dry_run: bool):
    ok = not problems
    lines = ["🩺 بازرسی هفتگی سامانه پایش", ""]
    if ok:
        lines.append("✅ همه بخش‌ها سالم‌اند.")
    else:
        lines.append(f"⚠️ {len(problems)} مشکل پیدا شد:")
        lines += [f"  ❌ {p}" for p in problems]
    if notes:
        lines.append("")
        lines += [f"  • {n}" for n in notes]
    msg = "\n".join(lines)
    print(msg)
    if dry_run:
        return
    for token_env, chat_env in [("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
                                ("TELEGRAM_BOT_TOKEN_EN", "TELEGRAM_CHAT_ID_EN")]:
        token = os.getenv(token_env, "").strip()
        chat = os.getenv(chat_env, "").strip()
        if not token or not chat:
            continue
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": msg[:4000]}, timeout=15)
            if r.status_code == 200:
                return  # delivered — first working bot is enough
        except Exception:
            pass
    print("WARNING: Telegram delivery failed on all bots")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the report without sending to Telegram")
    args = ap.parse_args()

    check_tools_compile()
    configs = check_configs()
    check_serpapi_quota()
    check_github_runs()
    check_seen_files()
    check_sites(configs)
    send_report(args.dry_run)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
