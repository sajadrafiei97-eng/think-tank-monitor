import logging
import time

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_notification(bot_token: str, chat_id: str, report: dict, think_tank_name: str) -> bool:
    title = _escape_html(report.get("title", "").strip())
    url = report.get("url", "").strip()
    source = _escape_html(think_tank_name)

    message = f"📌 <b>{source}</b>\n{title}\n{url}"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(
            TELEGRAM_API.format(token=bot_token),
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        else:
            logger.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        logger.error(f"Telegram request failed: {e}")
        return False


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


def send_batch(bot_token: str, chat_id: str, new_reports: list, mark_sent_fn):
    sent_urls = []
    for report in new_reports:
        success = send_notification(bot_token, chat_id, report, report.get("_source", ""))
        if success:
            sent_urls.append(report["url"])
            mark_sent_fn([report["url"]])
            logger.info(f"  Sent: {report['title'][:60]}")
        else:
            logger.warning(f"  Failed to send: {report.get('url', '')}")
        time.sleep(0.5)
    return sent_urls
