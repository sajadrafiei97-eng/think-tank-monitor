import logging

logger = logging.getLogger(__name__)


def matches_any_keyword(report: dict, keywords: list, fetch_fn) -> bool:
    title = report.get("title", "")
    summary = report.get("summary", "")
    combined = (title + " " + summary).lower()

    for kw in keywords:
        if kw.lower() in combined:
            return True

    full_text = fetch_fn(report["url"])
    if not full_text:
        return False

    full_lower = full_text.lower()
    for kw in keywords:
        if kw.lower() in full_lower:
            return True

    return False


def filter_reports(reports: list, keywords: list, fetch_fn) -> list:
    matched = []
    for report in reports:
        try:
            if matches_any_keyword(report, keywords, fetch_fn):
                matched.append(report)
                logger.info(f"  Match: {report['title'][:80]}")
        except Exception as e:
            logger.warning(f"  Error checking report {report.get('url', '')}: {e}")
    return matched
