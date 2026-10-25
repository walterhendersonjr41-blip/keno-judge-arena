"""One-shot backfill script for Keno Duel AI.

Scrapes recent Tennessee KENO To Go draws from comparethelotto.com and inserts
them into the MongoDB `keno_draws` collection with mode="live" and
source=SOURCE_IMPORTED so the AIs have real historical context.

The Tennessee Lottery itself is behind Cloudflare and refuses non-browser
clients, so we use Playwright to render comparethelotto.com and parse its
historicalResults section. The site only exposes ~50 recent draws per page
load; there is no visible pagination, so requesting more just fetches what is
available.

Usage:
    python /app/scripts/backfill_history.py [--max 200] [--dry-run]

Prereqs (already satisfied on this pod):
    - playwright==1.58.0 (pip)
    - Chromium at /pw-browsers (PLAYWRIGHT_BROWSERS_PATH=/pw-browsers)
    - MONGO_URL and DB_NAME in /app/backend/.env

This is idempotent — draws already present in Mongo are skipped.
"""
import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure backend package is importable
BACKEND_DIR = Path("/app/backend")
sys.path.insert(0, str(BACKEND_DIR))

# Load backend .env for MONGO_URL / DB_NAME
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

# Force playwright to use the pod-provided browser cache
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

from bs4 import BeautifulSoup
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright

# Import backend models so schema stays canonical
from models import Draw, SOURCE_IMPORTED  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")

SOURCE_URL = "https://www.comparethelotto.com/us/results-tennessee-keno-to-go"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


async def fetch_page_html(timeout_seconds: int = 90) -> Optional[str]:
    """Render the results page past the site's anti-bot spinner."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
                                          args=["--no-sandbox",
                                                "--disable-blink-features=AutomationControlled"])
        try:
            ctx = await browser.new_context(user_agent=USER_AGENT,
                                            viewport={"width": 1280, "height": 900},
                                            locale="en-US")
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await ctx.new_page()
            title = ""
            html = ""
            try:
                # commit = as soon as navigation has started; the site's JS reload
                # loop otherwise prevents "load"/"domcontentloaded" from firing.
                await page.goto(SOURCE_URL, timeout=15_000, wait_until="commit")
            except Exception as e:
                log.info("initial goto did not settle (%s) — continuing to poll", type(e).__name__)
            # Wait for the real-content selector; browser is free to reload as needed.
            try:
                await page.wait_for_selector("#historicalResults", timeout=timeout_seconds * 1000)
                # Content is ready — pull HTML with a short retry in case of a stray reload.
                for _ in range(5):
                    try:
                        html = await page.content()
                        title = await page.title()
                        if "Latest Results" in title and len(html) > 100_000:
                            return html
                    except Exception:
                        await page.wait_for_timeout(1000)
                        continue
            except Exception as e:
                log.warning("selector wait failed: %s", type(e).__name__)
            log.warning("did not reach real content; last title=%r html_size=%d",
                        title, len(html))
            return None
        finally:
            await browser.close()


def parse_draws(html: str) -> List[Dict[str, Any]]:
    """Extract every (draw_number, numbers) pair the page exposes."""
    soup = BeautifulSoup(html, "lxml")
    hist = soup.find(id="historicalResults")
    if not hist:
        return []
    body = hist.find(class_="card-body")
    if not body:
        return []

    draws: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def flush():
        if current and current["draw_number"] and len(current["numbers"]) == 20:
            draws.append(current)

    for el in body.children:
        if getattr(el, "name", None) is None:
            continue
        if el.name == "p":
            text = el.get_text(" ", strip=True)
            m = re.search(r"Draw\s*#(\d+)", text)
            current = {"draw_number": int(m.group(1)) if m else None,
                       "numbers": []}
        elif el.name == "span" and "results-number" in (el.get("class") or []) and current:
            tail = el.get_text(strip=True).split()[-1] if el.get_text(strip=True) else ""
            nm = re.search(r"(\d+)", tail)
            if nm:
                n = int(nm.group(1))
                if 1 <= n <= 80:
                    current["numbers"].append(n)
        elif el.name == "hr":
            flush()
            current = None
    flush()
    # De-duplicate by draw_number (source sometimes repeats the newest)
    seen: Dict[int, Dict[str, Any]] = {}
    for d in draws:
        seen[d["draw_number"]] = d
    return sorted(seen.values(), key=lambda d: d["draw_number"], reverse=True)


async def insert_draws(records: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, int]:
    """Insert unique draws into keno_draws (mode='live'). Returns counts."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    col = db.keno_draws
    inserted = skipped = 0
    for r in records:
        exists = await col.find_one({"draw_number": r["draw_number"], "mode": "live"},
                                    {"_id": 1})
        if exists:
            skipped += 1
            continue
        doc = Draw(
            draw_number=r["draw_number"],
            winning_numbers=sorted(r["numbers"]),
            source=SOURCE_IMPORTED,
            mode="live",
            drawn_at=datetime.now(timezone.utc).isoformat(),
        ).model_dump()
        if dry_run:
            log.info("[dry-run] would insert draw #%s", doc["draw_number"])
        else:
            await col.insert_one(doc)
            log.info("inserted draw #%s (%d numbers)",
                     doc["draw_number"], len(doc["winning_numbers"]))
        inserted += 1
    client.close()
    return {"inserted": inserted, "skipped_existing": skipped, "total_scraped": len(records)}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill TN Keno history into MongoDB")
    parser.add_argument("--max", type=int, default=200,
                        help="Maximum draws to import (source caps at ~50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print, but do not write to DB")
    parser.add_argument("--from-file", type=str, default=None,
                        help="Skip scraping; parse HTML from this local file (useful for retries when source is rate-limiting)")
    args = parser.parse_args()

    if args.from_file:
        log.info("parsing local file %s", args.from_file)
        with open(args.from_file, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        log.info("fetching %s", SOURCE_URL)
        html = await fetch_page_html()
    if not html:
        log.error("failed to load results page — try again later")
        return 2
    records = parse_draws(html)
    log.info("scraped %d unique draws from source", len(records))
    if args.max and len(records) > args.max:
        records = records[: args.max]
    if not records:
        log.warning("no draws parsed — page structure may have changed")
        return 3
    stats = await insert_draws(records, dry_run=args.dry_run)
    log.info("done — %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
