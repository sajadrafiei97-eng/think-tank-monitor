import logging
import time

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX_MESSAGE_LEN = 4096


def _escape_html(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def _shorten(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[:max_len - 3] + "..."


def _split_escaped_text(text: str, max_len: int) -> list:
    """Split text into HTML-escaped chunks no longer than max_len."""
    if max_len <= 0:
        return [""]

    chunks = []
    current = ""
    for char in text:
        escaped = _escape_html(char)
        if current and len(current) + len(escaped) > max_len:
            chunks.append(current)
            current = escaped
        else:
            current += escaped
    if current or not chunks:
        chunks.append(current)
    return chunks


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


def _format_report_line(report: dict, max_message_len: int, header_len: int) -> str:
    url = _escape_html(report.get("url", "").strip())
    title = _escape_html(report.get("title", "").strip())
    line_template_len = len(f'• <a href="{url}"></a>')
    max_title_len = max(0, max_message_len - header_len - line_template_len)
    title = _shorten(title, max_title_len)
    return f'• <a href="{url}">{title}</a>'


def _format_single_report_messages(header: str, report: dict,
                                   max_message_len: int) -> list:
    """Build one or more messages that include the full URL.

    Very long URLs can make the HTML anchor itself too large. In that case,
    fall back to plain text with a shortened title and the full URL. If even
    the URL alone is longer than Telegram's message limit, split the URL over
    multiple messages rather than dropping the item.
    """
    linked = header + _format_report_line(report, max_message_len, len(header))
    if len(linked) <= max_message_len:
        return [linked]

    raw_url = report.get("url", "").strip()
    url = _escape_html(raw_url)
    title = _escape_html(report.get("title", "").strip())
    plain_template_len = len("• \n") + len(url)
    max_title_len = max_message_len - len(header) - plain_template_len
    if max_title_len >= 0:
        title = _shorten(title, max_title_len)
        plain = f"{header}• {title}\n{url}"
        if len(plain) <= max_message_len:
            return [plain]

    if len(url) <= max_message_len:
        return [url]

    intro_text = f"{header}• {_shorten(title, max_message_len - len(header) - 2)}"
    messages = [intro_text[:max_message_len]]
    part_prefix = "URL part:\n"
    part_limit = max_message_len - len(part_prefix)
    messages.extend(part_prefix + part for part in _split_escaped_text(raw_url, part_limit))
    return messages


def _chunk_reports(header: str, reports: list,
                   max_message_len: int = TELEGRAM_MAX_MESSAGE_LEN) -> list:
    chunks = []
    current_lines = []
    current_reports = []

    def _flush_current():
        if current_lines:
            chunks.append(([header + "\n".join(current_lines)],
                           list(current_reports)))
            current_lines.clear()
            current_reports.clear()

    for report in reports:
        line = _format_report_line(report, max_message_len, len(header))
        if len(header + line) > max_message_len:
            _flush_current()
            chunks.append((_format_single_report_messages(header, report,
                                                          max_message_len),
                           [report]))
            continue

        candidate = header + "\n".join(current_lines + [line])
        if current_lines and len(candidate) > max_message_len:
            _flush_current()
            current_lines = [line]
            current_reports = [report]
        else:
            current_lines.append(line)
            current_reports.append(report)

    _flush_current()

    return chunks


def send_batch(bot_token: str, chat_id: str, new_reports: list, mark_sent_fn):
    # Group reports by source, preserving insertion order (already sorted by think-tank)
    groups: dict[str, list] = {}
    for report in new_reports:
        src = report.get("_source", "")
        groups.setdefault(src, []).append(report)

    sent_urls = []
    for source, reports in groups.items():
        header = f"🔹 <b>{_escape_html(source)}</b>\n"
        chunks = _chunk_reports(header, reports)

        for messages, chunk_reports in chunks:
            all_sent = True
            for message in messages:
                ok = _send_raw(bot_token, chat_id, message)
                time.sleep(0.5)
                if not ok:
                    all_sent = False
                    break
            if not all_sent:
                logger.error(f"  Failed to send {len(chunk_reports)} report(s) from {source}; not marking seen")
                continue

            urls = [r["url"] for r in chunk_reports]
            sent_urls.extend(urls)
            mark_sent_fn(urls)
            for r in chunk_reports:
                logger.info(f"  Sent: {r['title'][:60]}")

    return sent_urls
