import json
import os
import re
import requests

GH_TOKEN = os.environ["GH_TOKEN"]
REPO     = "sajadrafiei97-eng/think-tank-monitor"
SCHEDULE_FILE = "config_schedule.json"

# ── bot definitions ────────────────────────────────────────────────────────────
BOTS = {
    "arabic": {
        "token":     os.environ["TELEGRAM_BOT_TOKEN"],
        "chat_id":   str(os.environ["TELEGRAM_CHAT_ID"]),
        "offset_file": ".tmp/bot_offset_ar.json",
        "systems":   ["عربی", "هر دو"],          # options this bot can trigger
        "system_map": {"عربی": "arabic", "هر دو": "both"},
    },
    "english": {
        "token":     os.environ["TELEGRAM_BOT_TOKEN_EN"],
        "chat_id":   str(os.environ["TELEGRAM_CHAT_ID_EN"]),
        "offset_file": ".tmp/bot_offset_en.json",
        "systems":   ["انگلیسی", "هر دو"],
        "system_map": {"انگلیسی": "english", "هر دو": "both"},
    },
}

# Time range buttons → days
RANGE_MAP = {
    "امروز": 1,
    "۳ روز": 3,
    "هفته":  7,
}

# Pattern: "YYYY-MM-DD to YYYY-MM-DD [arabic|english|both]" (free text)
DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})"
    r"(?:\s+(arabic|english|both))?",
    re.IGNORECASE,
)

HELP_TEXT = (
    "راهنمای استفاده:\n\n"
    "یکی از دکمه‌های کیبورد را بزن تا جستجو شروع شود.\n\n"
    "📅 تاریخ دلخواه:\n"
    "بعد از زدن این دکمه، بازه را تایپ کن:\n"
    "  YYYY-MM-DD to YYYY-MM-DD\n"
    "  YYYY-MM-DD to YYYY-MM-DD arabic\n"
    "  YYYY-MM-DD to YYYY-MM-DD english\n"
    "(بدون ذکر سیستم = هر دو)\n\n"
    "دستورات:\n"
    "  /schedule on  — روشن کردن ارسال خودکار ۹ صبح\n"
    "  /schedule off — خاموش کردن ارسال خودکار ۹ صبح\n"
    "  /status       — وضعیت فعلی"
)


def make_keyboard(bot_key: str) -> dict:
    """Build the ReplyKeyboard for a given bot (arabic/english)."""
    bot = BOTS[bot_key]
    rows = []
    for sys_label in bot["systems"]:
        row = [{"text": f"{sys_label} - {rng}"} for rng in RANGE_MAP]
        rows.append(row)
    rows.append([
        {"text": "📅 تاریخ دلخواه"},
        {"text": "📊 وضعیت"},
        {"text": "❓ راهنما"},
    ])
    return {"keyboard": rows, "resize_keyboard": True, "persistent": True}


def load_offset(path: str) -> int:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f).get("offset", 0)
    return 0


def save_offset(path: str, offset: int):
    os.makedirs(".tmp", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"offset": offset}, f)


def load_schedule_enabled() -> bool:
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            return json.load(f).get("enabled", True)
    return True


def save_schedule_enabled(enabled: bool):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump({"enabled": enabled}, f, indent=2)


def get_updates(token: str, offset: int) -> list:
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": offset, "timeout": 0, "limit": 20},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def send(token: str, chat_id: str, text: str, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload, timeout=10,
    )


def trigger(system: str, days: int = 1,
            date_from: str = "", date_to: str = "") -> bool:
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    inputs = {"days": str(days), "system": system}
    if date_from:
        inputs["date_from"] = date_from
    if date_to:
        inputs["date_to"] = date_to
    r = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/monitor.yml/dispatches",
        headers=headers,
        json={"ref": "main", "inputs": inputs},
        timeout=15,
    )
    return r.status_code == 204


def run_and_confirm(token: str, chat_id: str, system: str,
                    days: int = 1, date_from: str = "", date_to: str = ""):
    labels = {"both": "عربی + انگلیسی", "arabic": "عربی", "english": "انگلیسی"}
    period = (f"{date_from} تا {date_to}" if date_from
              else ("امروز" if days == 1 else f"{days} روز اخیر"))
    if trigger(system, days, date_from, date_to):
        send(token, chat_id,
             f"✅ شروع شد\nسیستم: {labels.get(system, system)}\nبازه: {period}\n\n"
             f"نتایج چند دقیقه دیگر می‌رسد.")
    else:
        send(token, chat_id, "❌ خطا در اجرا. لطفاً دوباره تلاش کن.")


def handle(token: str, chat_id: str, text: str, bot_key: str):
    bot   = BOTS[bot_key]
    kbmap = bot["system_map"]   # e.g. {"عربی": "arabic", "هر دو": "both"}

    # 1. Keyboard button: "عربی - ۳ روز" or "هر دو - امروز" etc.
    for sys_label, days_label in [(s, d) for s in kbmap for d in RANGE_MAP]:
        if text == f"{sys_label} - {days_label}":
            run_and_confirm(token, chat_id, kbmap[sys_label], RANGE_MAP[days_label])
            return

    # 2. Custom date range typed as free text
    m = DATE_RE.fullmatch(text.strip())
    if m:
        date_from, date_to = m.group(1), m.group(2)
        system = (m.group(3) or "both").lower()
        # restrict system to what this bot is allowed to trigger
        allowed = set(kbmap.values())
        if system not in allowed:
            system = next(iter(allowed))  # fall back to first allowed
        run_and_confirm(token, chat_id, system, date_from=date_from, date_to=date_to)
        return

    # 3. Date help button
    if text == "📅 تاریخ دلخواه":
        send(token, chat_id,
             "📅 بازه تاریخ را وارد کن:\n\n"
             "فرمت:  YYYY-MM-DD to YYYY-MM-DD [system]\n\n"
             "مثال‌ها:\n"
             "2026-06-01 to 2026-06-07\n"
             "2026-06-01 to 2026-06-07 arabic\n"
             "2026-06-01 to 2026-06-07 english")
        return

    # 4. Status
    if text in ("📊 وضعیت", "/status"):
        state = "روشن ✅" if load_schedule_enabled() else "خاموش ⛔"
        send(token, chat_id, f"وضعیت ارسال خودکار ۹ صبح: {state}")
        return

    # 5. Help / start
    if text in ("❓ راهنما", "/help", "/start"):
        send(token, chat_id, HELP_TEXT, reply_markup=make_keyboard(bot_key))
        return

    # 6. Schedule toggle
    if text.lower().startswith("/schedule"):
        parts = text.split()
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            send(token, chat_id, "استفاده:\n/schedule on\n/schedule off")
            return
        enabled = parts[1].lower() == "on"
        save_schedule_enabled(enabled)
        state = "روشن ✅" if enabled else "خاموش ⛔"
        send(token, chat_id, f"ارسال خودکار ۹ صبح {state} شد.")
        return


def process_bot(bot_key: str):
    bot = BOTS[bot_key]
    offset = load_offset(bot["offset_file"])
    updates = get_updates(bot["token"], offset)
    new_offset = offset

    for update in updates:
        new_offset = update["update_id"] + 1
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        if chat_id != bot["chat_id"] or not text:
            continue

        handle(bot["token"], bot["chat_id"], text, bot_key)

    if new_offset != offset:
        save_offset(bot["offset_file"], new_offset)

    print(f"[{bot_key}] {len(updates)} updates, offset → {new_offset}")


def main():
    process_bot("arabic")
    process_bot("english")


if __name__ == "__main__":
    main()
