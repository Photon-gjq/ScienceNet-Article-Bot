import argparse
import logging
import os
import time
from pathlib import Path

from .crawler import CrawlError, create_session, fetch_articles
from .state import StateError, load_ids, save_ids
from .telegram import TelegramClient, TelegramError

LOG = logging.getLogger(__name__)
DEFAULT_STATE = Path(__file__).resolve().parent.parent / "previous_articles.json"


def deliver(articles, previous_ids, state_path, client, max_messages=5, delay=1.1):
    pending = [article for article in articles if article.id not in previous_ids]
    sent = 0
    for article in pending[:max_messages]:
        if sent:
            time.sleep(delay)
        client.send(article.message())
        previous_ids.add(article.id)
        # Persist only acknowledged deliveries, immediately after each send.
        save_ids(state_path, previous_ids)
        sent += 1
        LOG.info("Delivered article=%s", article.id)
    return sent, len(pending) - sent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Forward ScienceNet articles to Telegram")
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch/preview only; never send or update history"
    )
    parser.add_argument(
        "--verify-telegram",
        action="store_true",
        help="Check Telegram credentials and permissions without sending",
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--max-messages", type=int, default=5, help="Per-run delivery cap (default: 5)"
    )
    args = parser.parse_args(argv)
    if args.max_messages < 1:
        parser.error("--max-messages must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        previous_ids = load_ids(args.state_file)
        if not previous_ids:
            raise StateError(
                "Delivery history is empty; restore it before running to prevent a mass replay"
            )
        with create_session() as session:
            articles = fetch_articles(session, previous_ids)
        pending = [article for article in articles if article.id not in previous_ids]
        LOG.info("Found %d unseen articles; delivery cap=%d", len(pending), args.max_messages)
        if args.dry_run or args.verify_telegram:
            for article in pending[: args.max_messages]:
                LOG.info("Preview article=%s title=%s", article.id, article.title)
            if args.verify_telegram:
                with TelegramClient(
                    os.getenv("BOT_TOKEN", ""), os.getenv("CHAT_ID", ""), read_only=True
                ) as client:
                    client.verify()
                LOG.info(
                    "Telegram authentication and posting permissions verified (no messages sent)"
                )
            LOG.info("Dry run complete: no messages sent; history unchanged")
            return 0
        with TelegramClient(os.getenv("BOT_TOKEN", ""), os.getenv("CHAT_ID", "")) as client:
            client.verify()
            sent, remaining = deliver(
                articles, previous_ids, args.state_file, client, args.max_messages
            )
        LOG.info("Delivered %d articles; %d queued for later runs", sent, remaining)
        return 0
    except (CrawlError, StateError, TelegramError) as exc:
        LOG.error("%s", exc)
        return 1
