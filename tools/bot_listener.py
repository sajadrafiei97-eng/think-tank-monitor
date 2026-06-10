import json
import os
import requests

TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID  = str(os.environ["TELEGRAM_CHAT_ID"])
GH_TOKEN = os.environ["GH_TOKEN"]
REPO     = "sajadrafiei97-eng/think-tank-monitor"
OFFSET_FILE = ".tmp/bot_offset.json"

HELP_TEXT = (
    "دستورات موجود:\n\n"
    "/run — هر دو سیستم، امروز\n"
    "/run 3 — هر دو سیستم، ۳ روز اخیر\n"
    "/run_ar 7 — فقط عربی، ۷ روز اخیر\n"
    "/run_en 5 — فقط انگلیسی، ۵ روز اخیر\n"
    "/help — این راهنما"
)


def load_offset() -> int:
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            return json.load(f).get("offset", 0)
    return 0


def save_offset(offset: int):
    os.makedirs(".tmp", exist_ok=True)
    with open(OFFSET_FILE, "w") as f:
        json.dump({"offset": offset}, f)


def get_updates(offset: int) -> list:
    r = requests.get(
        f"https://api.telegram.org/bot{TOKEN}/getUpdates",
        params={"offset": offset, "timeout": 0, "limit": 20},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def send_message(text: str):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=10,
    )


def trigger_workflow(days: int, system: str) -> bool:
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    r = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/monitor.yml/dispatches",
        headers=headers,
        json={"ref": "main", "inputs": {"days": str(days), "system": system}},
        timeout=15,
    )
    return r.status_code == 204


def parse_command(text: str):
    """Returns (days, system) or None if not a valid /run command."""
    parts = text.strip().split()
    if not parts:
        return None

    cmd = parts[0].lower()

    if cmd in ("/help", "/start"):
        send_message(HELP_TEXT)
        return None

    if cmd == "/run":
        system = "both"
    elif cmd == "/run_ar":
        system = "arabic"
    elif cmd == "/run_en":
        system = "english"
    else:
        return None

    days = 1
    if len(parts) >= 2:
        try:
            days = max(1, min(int(parts[1]), 30))
        except ValueError:
            send_message(f"عدد نامعتبر: {parts[1]}\nمثال: /run 7")
            return None

    return days, system


def main():
    offset = load_offset()
    updates = get_updates(offset)

    new_offset = offset
    for update in updates:
        new_offset = update["update_id"] + 1

        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        if chat_id != CHAT_ID:
            continue

        if not text.startswith("/"):
            continue

        result = parse_command(text)
        if result is None:
            continue

        days, system = result
        labels = {"both": "عربی + انگلیسی", "arabic": "عربی", "english": "انگلیسی"}

        if trigger_workflow(days, system):
            day_word = "روز اخیر" if days > 1 else "امروز"
            period = f"{days} {day_word}" if days > 1 else day_word
            send_message(
                f"✅ شروع شد\n"
                f"سیستم: {labels[system]}\n"
                f"بازه: {period}\n\n"
                f"نتایج چند دقیقه دیگر می‌رسد."
            )
        else:
            send_message("❌ خطا در اجرا. لطفاً دوباره تلاش کن.")

    if new_offset != offset:
        save_offset(new_offset)

    print(f"Processed {len(updates)} updates, offset: {new_offset}")


if __name__ == "__main__":
    main()
