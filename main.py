"""
main.py – CLI entry point for the Contact Form Submitter agent.

Usage:
    python main.py                       # process all URLs in targets.csv
    python main.py --csv other.csv       # use a custom CSV file
    python main.py --headless            # override headless mode
    python main.py --url https://x.com   # run against a single URL
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

from config import settings
from db import ResultsDB
from agent import run_batch

# ── Logging ──────────────────────────────────────────────────
LOG_FMT = "%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s"
LOG_DATE = "%H:%M:%S"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format=LOG_FMT, datefmt=LOG_DATE, level=level, stream=sys.stdout)
    # Quieten noisy libraries
    for name in ("httpx", "httpcore", "openai", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ── CSV loader ───────────────────────────────────────────────
def _load_targets(csv_path: Path) -> list[str]:
    """Read the 'url' column from the CSV, stripping blanks."""
    urls: list[str] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            url = row.get("url", "").strip()
            if url:
                urls.append(url)
    return urls


# ── CLI ──────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI-driven contact-form submitter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to targets CSV (default: targets.csv in project root)",
    )
    p.add_argument(
        "--url",
        type=str,
        default=None,
        help="Submit to a single URL instead of reading the CSV",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="Run the browser without a visible window",
    )
    p.add_argument(
        "--headful",
        action="store_true",
        default=None,
        help="Run the browser with a visible window (default)",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return p.parse_args()


# ── Main ─────────────────────────────────────────────────────
async def _async_main() -> None:
    args = _parse_args()
    _setup_logging(verbose=args.verbose)

    log = logging.getLogger("main")

    # Override headless from CLI flags
    if args.headless:
        settings.headless = True
    elif args.headful:
        settings.headless = False

    # Validate API key
    if not settings.gemini_api_key:
        log.error(
            "GEMINI_API_KEY is not set. "
            "Create a .env file (see .env.example) or export the variable."
        )
        sys.exit(1)

    # Resolve target URLs
    if args.url:
        urls = [args.url]
    else:
        csv_path = args.csv or settings.targets_csv
        if not csv_path.exists():
            log.error("Targets CSV not found: %s", csv_path)
            sys.exit(1)
        urls = _load_targets(csv_path)

    if not urls:
        log.warning("No URLs to process. Exiting.")
        sys.exit(0)

    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║   Contact Form Submitter  –  %d target(s)        ║", len(urls))
    log.info("║   Mode: %s                               ║", "headless" if settings.headless else "headful ")
    log.info("╚══════════════════════════════════════════════════╝")

    db = ResultsDB(settings.results_db)

    try:
        results = await run_batch(urls, settings, db)
    finally:
        db.close()

    # ── Summary ───────────────────────────────────────────────
    submitted = sum(1 for r in results if r.status == "submitted")
    blocked = sum(1 for r in results if r.status == "captcha_blocked")
    no_form = sum(1 for r in results if r.status == "no_form")
    errors = sum(1 for r in results if r.status == "error")

    log.info("")
    log.info("┌─────────────── SUMMARY ───────────────┐")
    log.info("│  ✅ Submitted       : %d", submitted)
    log.info("│  🛡️  CAPTCHA blocked : %d", blocked)
    log.info("│  ⚠️  No form found   : %d", no_form)
    log.info("│  ❌ Errors          : %d", errors)
    log.info("│  📊 Total           : %d", len(results))
    log.info("└────────────────────────────────────────┘")
    log.info("Results saved to %s", settings.results_db)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
