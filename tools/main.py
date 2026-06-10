import argparse
import logging
import os
import sys
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv

from notifier import send_batch
from search_tool import search_all
from state import filter_new_reports, load_seen_urls, mark_sent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")


def _build_domain_map(think_tanks: list) -> dict:
    mapping = {}
    for tt in think_tanks:
        domain = urlparse(tt["url"]).netloc.lstrip("www.")
        mapping[domain] = tt["name"]
    return mapping


def _resolve_source(url: str, domain_map: dict) -> str:
    domain = urlparse(url).netloc.lstrip("www.")
    return domain_map.get(domain, domain)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml",
                        help="Config file name (relative to project root)")
    parser.add_argument("--days", type=int, default=1,
                        help="Number of days to look back (default: 1 = today only)")
    parser.add_argument("--no-dedup", action="store_true",
                        help="Skip seen-URL deduplication (for manual/historical runs)")
    parser.add_argument("--date-from", default="",
                        help="Custom start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--date-to", default="",
                        help="Custom end date YYYY-MM-DD")
    args = parser.parse_args()

    config_path = os.path.join(BASE_DIR, args.config)
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)

    load_dotenv(ENV_PATH)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Read credential env-var names from config (with defaults for Arabic system)
    creds = config.get("credentials", {})
    token_env  = creds.get("telegram_token_env", "TELEGRAM_BOT_TOKEN")
    chat_env   = creds.get("telegram_chat_env",  "TELEGRAM_CHAT_ID")
    serp_env   = creds.get("serpapi_key_env",     "SERPAPI_KEY")
    google_env = creds.get("google_api_key_env",  "GOOGLE_API_KEY")
    cse_env    = creds.get("google_cse_id_env",   "GOOGLE_CSE_ID")
    tavily_env = creds.get("tavily_key_env",      "TAVILY_API_KEY")

    bot_token     = os.getenv(token_env,  "").strip()
    chat_id       = os.getenv(chat_env,   "").strip()
    serpapi_key   = os.getenv(serp_env,   "").strip()
    google_api    = os.getenv(google_env, "").strip()
    google_cse    = os.getenv(cse_env,    "").strip()
    tavily_key    = os.getenv(tavily_env, "").strip()

    # Seen-URLs file (per-config so Arabic and English don't share state)
    seen_file = config.get("seen_urls_file", ".tmp/seen_urls.json")
    seen_path = os.path.join(BASE_DIR, seen_file)

    if not bot_token or not chat_id:
        logger.error(f"{token_env} or {chat_env} not set in .env")
        sys.exit(1)

    if not serpapi_key and not google_api and not tavily_key:
        logger.error("No search API key found in .env")
        sys.exit(1)

    think_tanks = config["think_tanks"]
    keywords    = config["keywords"]
    sites = [tt["url"].replace("https://", "").replace("http://", "").rstrip("/")
             for tt in think_tanks]
    domain_map = _build_domain_map(think_tanks)

    seen = load_seen_urls(seen_path)
    logger.info(f"Loaded {len(seen)} seen URLs  [{args.config}]")

    search_opts = config.get("search_options", {})
    hl = search_opts.get("hl", "ar")
    gl = search_opts.get("gl", "eg")

    results = search_all(google_api, google_cse, tavily_key, sites, keywords, serpapi_key,
                         hl=hl, gl=gl, days=args.days,
                         date_from=args.date_from, date_to=args.date_to)

    if not results:
        logger.info("No results found.")
        sys.exit(0)

    if args.no_dedup:
        new_results = results
        logger.info(f"{len(new_results)} results (dedup skipped)")
    else:
        new_results = filter_new_reports(results, seen)
        logger.info(f"{len(new_results)} new (of {len(results)} total)")

    if not new_results:
        logger.info("Nothing to send.")
        sys.exit(0)

    for r in new_results:
        r["_source"] = _resolve_source(r["url"], domain_map)

    def _mark_sent_now(urls):
        nonlocal seen
        if not args.no_dedup:
            seen = mark_sent(urls, seen, seen_path)

    sent = send_batch(bot_token, chat_id, new_results, _mark_sent_now)
    logger.info(f"\nDone. {len(sent)} report(s) sent to Telegram.")


if __name__ == "__main__":
    main()
