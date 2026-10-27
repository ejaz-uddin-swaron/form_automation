"""
main.py – CLI entry point for the Contact Form Submitter agent.

Usage:
    python main.py                       # process all targets in targets.csv (or adu_companies_california.csv)
    python main.py --csv other.csv       # use a custom CSV file (supports 'Company Name,Website' or 'url,notes')
    python main.py --skip-existing       # skip targets already processed in results.db
    python main.py --limit 5             # process only the first 5 targets
    python main.py --offset 10           # start from the 10th target
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
from agent import Target, run_batch

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
def _load_targets(csv_path: Path) -> list[Target]:
    """
    Read targets from CSV.
    Detects URL and company name from various standard column names:
      - URL: 'website', 'url', 'link', 'web', 'site', 'target', 'domain'
      - Company: 'company name', 'company', 'business name', 'name', 'title'
    """
    targets: list[Target] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            norm = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}

            url = (
                norm.get("website")
                or norm.get("url")
                or norm.get("link")
                or norm.get("web")
                or norm.get("site")
                or norm.get("target")
                or norm.get("domain")
                or ""
            )
            if not url:
                continue

            # Prepend https:// if protocol was omitted
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            company = (
                norm.get("company name")
                or norm.get("company")
                or norm.get("business name")
                or norm.get("name")
                or norm.get("title")
                or ""
            )

            targets.append(Target(url=url, company=company))
    return targets


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
        help="Path to targets CSV (default: adu_companies_california.csv or targets.csv)",
    )
    p.add_argument(
        "--url",
        type=str,
        default=None,
        help="Submit to a single URL instead of reading the CSV",
    )
    p.add_argument(
        "--company",
        type=str,
        default="",
        help="Target company name (when using --url)",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip targets already recorded in results.db",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of targets to process in this run",
    )
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of targets to skip from the beginning of the list",
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

    # Resolve targets
    if args.url:
        targets = [Target(url=args.url, company=args.company)]
    else:
        if args.csv:
            csv_path = args.csv
        elif Path("adu_companies_california.csv").exists():
            csv_path = Path("adu_companies_california.csv")
        else:
            csv_path = settings.targets_csv

        if not csv_path.exists():
            log.error("Targets CSV not found: %s", csv_path)
            sys.exit(1)
        targets = _load_targets(csv_path)

    if not targets:
        log.warning("No targets to process. Exiting.")
        sys.exit(0)

    # Apply offset and limit
    if args.offset > 0:
        targets = targets[args.offset:]
    if args.limit is not None and args.limit > 0:
        targets = targets[:args.limit]

    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║   Contact Form Submitter  –  %d target(s)        ║", len(targets))
    log.info("║   Mode: %-37s║", "headless" if settings.headless else "headful")
    log.info("║   Skip Existing: %-30s║", "yes" if args.skip_existing else "no")
    log.info("╚══════════════════════════════════════════════════╝")

    db = ResultsDB(settings.results_db)

    try:
        results = await run_batch(
            targets,
            settings,
            db,
            skip_existing=args.skip_existing,
        )
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
    log.info("│  📊 Total Processed : %d", len(results))
    log.info("└────────────────────────────────────────┘")
    log.info("Results saved to %s", settings.results_db)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
