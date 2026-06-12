import json
import os
import re
import requests

GH_TOKEN = os.environ["GH_TOKEN"]
REPO     = os.environ.get("GITHUB_REPOSITORY", "sajadrafiei97-eng/think-tank-monitor")
SCHEDULE_FILE = "config_schedule.json"

# ── bot definitions ────────────────────────────────────────────────────────────
BOTS = {
    "arabic": {
        "token":     os.environ["TELEGRAM_BOT_TOKEN"],
        "chat_id":   str(os.environ["TELEGRAM_CHAT_ID"]),
        "offset_file": ".tmp/bot_offset_ar.json",
        "systems":   ["عربی", "هر دو"],
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

# Pattern: "YYYY-MM-DD to YYYY-MM-DD [arabic|english|both] [title|full]"
DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})"
    r"(?:\s+(arabic|english|both))?"
    r"(?:\s+(title|full))?",
    re.IGNORECASE,
)

HELP_TEXT = (
    "راهنمای استفاده:\n\n"
    "ابتدا حالت جستجو را انتخاب کن، سپس بازه را بزن — هر دو در همان poll بعدی پردازش می‌شوند:\n\n"
    "  🔎 فقط عنوان — جستجو فقط در عنوان (سریع‌تر)\n"
    "  📄 عنوان + متن — جستجو در عنوان و متن (جامع‌تر)\n\n"
    "📅 تاریخ دلخواه با حالت:\n"
    "  YYYY-MM-DD to YYYY-MM-DD arabic title\n"
    "  YYYY-MM-DD to YYYY-MM-DD english full\n\n"
    "دستورات:\n"
    "  /schedule on  — روشن کردن ارسال خودکار ۹ صبح\n"
    "  /schedule off — خاموش کردن ارسال خودکار ۹ صبح\n"
    "  /status       — وضعیت فعلی"
)


def make_keyboard(bot_key: str) -> dict:
    bot = BOTS[bot_key]
    rows = []
    for sys_label in bot["systems"]:
        row = [{"text": f"{sys_label} - {rng}"} for rng in RANGE_MAP]
        rows.append(row)
    rows.append([
        {"text": "🔎 فقط عنوان"},
        {"text": "📄 عنوان + متن"},
    ])
    rows.append([
        {"text": "📅 تاریخ دلخواه"},
        {"text": "📊 وضعیت"},
        {"text": "❓ راهنما"},
    ])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


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
    data = {}
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            data = json.load(f)
    data["enabled"] = enabled
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_search_mode(bot_key: str) -> str:
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            return json.load(f).get(f"search_mode_{bot_key}", "full")
    return "full"


def save_search_mode(bot_key: str, mode: str):
    data = {}
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            data = json.load(f)
    data[f"search_mode_{bot_key}"] = mode
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(data, f, indent=2)


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
            date_from: str = "", date_to: str = "", mode: str = "") -> bool:
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    inputs = {"days": str(days), "system": system}
    if date_from:
        inputs["date_from"] = date_from
    if date_to:
        inputs["date_to"] = date_to
    if mode:
        inputs["mode"] = mode
    r = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/monitor.yml/dispatches",
        headers=headers,
        json={"ref": "main", "inputs": inputs},
        timeout=15,
    )
    return r.status_code == 204


def run_and_confirm(token: str, chat_id: str, system: str, bot_key: str,
                    days: int = 1, date_from: str = "", date_to: str = "",
                    mode: str = ""):
    labels = {"both": "عربی + انگلیسی", "arabic": "عربی", "english": "انگلیسی"}
    mode_icons = {"title": " 🔎", "full": " 📄"}
    period = (f"{date_from} تا {date_to}" if date_from
              else ("امروز" if days == 1 else f"{days} روز اخیر"))
    kb = make_keyboard(bot_key)
    if trigger(system, days, date_from, date_to, mode):
        send(token, chat_id,
             f"✅ شروع شد\nسیستم: {labels.get(system, system)}"
             f"\nبازه: {period}{mode_icons.get(mode, '')}\n\n"
             f"نتایج چند دقیقه دیگر می‌رسد.",
             reply_markup=kb)
    else:
        send(token, chat_id, "❌ خطا در اجرا. لطفاً دوباره تلاش کن.", reply_markup=kb)


def handle(token: str, chat_id: str, text: str, bot_key: str):
    bot   = BOTS[bot_key]
    kbmap = bot["system_map"]
    kb    = make_keyboard(bot_key)

    # 1. Search button: "عربی - امروز" etc. — reads current saved mode automatically
    for sys_label, days_label in [(s, d) for s in kbmap for d in RANGE_MAP]:
        if text == f"{sys_label} - {days_label}":
            mode = load_search_mode(bot_key)   # picks up any mode set in same batch
            run_and_confirm(token, chat_id, kbmap[sys_label], bot_key,
                            RANGE_MAP[days_label], mode=mode)
            return

    # 2. Custom date range: "2026-06-01 to 2026-06-07 [arabic] [title]"
    m = DATE_RE.fullmatch(text.strip())
    if m:
        date_from, date_to = m.group(1), m.group(2)
        system = (m.group(3) or "both").lower()
        mode   = (m.group(4) or load_search_mode(bot_key)).lower()
        allowed = set(kbmap.values())
        if system not in allowed:
            system = next(iter(allowed))
        run_and_confirm(token, chat_id, system, bot_key,
                        date_from=date_from, date_to=date_to, mode=mode)
        return

    # 3. Date help button
    if text == "📅 تاریخ دلخواه":
        send(token, chat_id,
             "📅 بازه تاریخ را وارد کن:\n\n"
             "فرمت:  YYYY-MM-DD to YYYY-MM-DD [system] [mode]\n\n"
             "مثال‌ها:\n"
             "2026-06-01 to 2026-06-07\n"
             "2026-06-01 to 2026-06-07 arabic title\n"
             "2026-06-01 to 2026-06-07 english full",
             reply_markup=kb)
        return

    # 4. Search mode toggle — saves locally so next search in same batch picks it up
    if text == "🔎 فقط عنوان":
        save_search_mode(bot_key, "title")
        mode_label = "فقط عنوان 🔎"
        send(token, chat_id, f"✅ حالت جستجو: {mode_label}", reply_markup=kb)
        return

    if text == "📄 عنوان + متن":
        save_search_mode(bot_key, "full")
        send(token, chat_id, "✅ حالت جستجو: عنوان + متن 📄", reply_markup=kb)
        return

    # 5. Status
    if text in ("📊 وضعیت", "/status"):
        state = "روشن ✅" if load_schedule_enabled() else "خاموش ⛔"
        mode = load_search_mode(bot_key)
        mode_label = "فقط عنوان 🔎" if mode == "title" else "عنوان + متن 📄"
        send(token, chat_id,
             f"وضعیت ارسال خودکار ۹ صبح: {state}\n"
             f"حالت جستجو پیش‌فرض: {mode_label}",
             reply_markup=kb)
        return

    # 6. Help / start
    if text in ("❓ راهنما", "/help", "/start"):
        send(token, chat_id, HELP_TEXT, reply_markup=kb)
        return

    # 7. Schedule toggle
    if text.lower().startswith("/schedule"):
        parts = text.split()
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            send(token, chat_id, "استفاده:\n/schedule on\n/schedule off", reply_markup=kb)
            return
        enabled = parts[1].lower() == "on"
        save_schedule_enabled(enabled)
        state = "روشن ✅" if enabled else "خاموش ⛔"
        send(token, chat_id, f"ارسال خودکار ۹ صبح {state} شد.", reply_markup=kb)
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

    print(f"[{bot_key}] {len(updates)} updates, offset -> {new_offset}")


def main():
    process_bot("arabic")
    process_bot("english")


if __name__ == "__main__":
    main()
