import logging
import time

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")



def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=bot_token),
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def _send_raw(bot_token: str, chat_id: str, text: str, preview: bool = False) -> bool:
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=bot_token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": not preview,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        logger.error(f"Telegram request failed: {e}")
        return False


def send_batch(bot_token: str, chat_id: str, new_reports: list, mark_sent_fn):
    # Group reports by source, preserving insertion order (already sorted by think-tank)
    groups: dict[str, list] = {}
    for report in new_reports:
        src = report.get("_source", "")
        groups.setdefault(src, []).append(report)

    sent_urls = []
    for source, reports in groups.items():
        header = f"🔹 <b>{_escape_html(source)}</b>\n"
        lines = []
        for r in reports:
            title = _escape_html(r.get("title", "").strip())
            url = r.get("url", "").strip()
            lines.append(f'• <a href="{url}">{title}</a>')

        message = header + "\n".join(lines)
        # Telegram hard limit is 4096 chars — split into chunks if needed
        chunks = [message] if len(message) <= 4096 else [
            header + "\n".join(lines[i:i+10]) for i in range(0, len(lines), 10)
        ]

        for chunk in chunks:
            _send_raw(bot_token, chat_id, chunk)
            time.sleep(0.5)

        for r in reports:
            sent_urls.append(r["url"])
            mark_sent_fn([r["url"]])
            logger.info(f"  Sent: {r['title'][:60]}")

    return sent_urls
