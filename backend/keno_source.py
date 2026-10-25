"""Tennessee Keno draw source. Real draws only (tnlottery.com, then comparethelotto.com);
simulator is only used in Practice Mode."""
import os
import random
import logging
from typing import Optional, Dict, Any, List
import httpx
from bs4 import BeautifulSoup

# Playwright browsers on this pod live at /pw-browsers (v1.58 headless_shell).
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

logger = logging.getLogger(__name__)

# TN Lottery has NO public JSON API. Canonical source is HTML.
# Order: official TN page, then aggregator fallbacks.
TN_CANDIDATE_URLS = []  # no json apis exist

# Each page has its own strict parser (see _PARSERS below). The old generic
# "first 20 numbers on the page" scraper picked up menu badges and returned
# WRONG winning numbers, so it is no longer used for live data.
TN_SCRAPE_PAGES = [
    "https://tnlottery.com/winning-numbers/keno-to-go/",
    "https://www.comparethelotto.com/us/results-tennessee-keno-to-go",
]
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

import time as _time_mod

_feed_state = _initial_feed_state = {
    "last_check_at": None,
    "last_success_at": None,
    "last_error": None,
    "connected": False,
    "attempts": 0,
    "cache_hits": 0,
    "first_live_draw_at": None,
    "first_live_draw_number": None,
    "latest_real_draw_number": None,  # newest draw number seen at the real source
    "source_url": None,
    "stale": True,  # True when the last fetch failed (showing last known draw)
}

# In-memory cache: TTL 45s to avoid hammering the sources for 24/7 polite polling.
_cache = {"draws": None, "expires_at": 0.0}
_CACHE_TTL = 45.0

# Optional persistence hook — server injects this at startup so feed_state survives restarts
_persist_cb = None
def set_persist_hook(cb):
    global _persist_cb
    _persist_cb = cb

def hydrate_feed_state(doc: dict):
    if not doc: return
    for k in _feed_state.keys():
        if k in doc: _feed_state[k] = doc[k]

async def _persist_state():
    if _persist_cb:
        try: await _persist_cb(dict(_feed_state))
        except Exception: pass


def feed_status() -> Dict[str, Any]:
    return dict(_feed_state)


def _valid_draw(d: Dict[str, Any]) -> bool:
    nums = d.get("winning_numbers") or []
    return (isinstance(d.get("draw_number"), int) and d["draw_number"] > 0
            and len(nums) == 20 and len(set(nums)) == 20
            and all(1 <= n <= 80 for n in nums))


def _clean(draws: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate, de-duplicate and sort newest-first."""
    seen = {}
    for d in draws:
        if _valid_draw(d) and d["draw_number"] not in seen:
            seen[d["draw_number"]] = d
    return [seen[k] for k in sorted(seen, reverse=True)]


async def _mark_success(draws: List[Dict[str, Any]], url: str, now: float):
    _feed_state.update(connected=True, stale=False,
                       last_success_at=_feed_state["last_check_at"],
                       last_error=None, source_url=url,
                       latest_real_draw_number=draws[0]["draw_number"])
    _cache["draws"] = draws
    _cache["expires_at"] = now + _CACHE_TTL
    if not _feed_state.get("first_live_draw_number"):
        _feed_state["first_live_draw_number"] = draws[0]["draw_number"]
        _feed_state["first_live_draw_at"] = _feed_state["last_success_at"]
    await _persist_state()


async def fetch_recent_official_draws() -> List[Dict[str, Any]]:
    """Return the real recent TN Keno To Go draws, newest first (up to ~50).
    Empty list when every source fails. Never fakes data. Caches for 45s."""
    import datetime as dt
    now = _time_mod.time()
    if _cache["draws"] and now < _cache["expires_at"]:
        _feed_state["cache_hits"] += 1
        return [dict(d) for d in _cache["draws"]]

    _feed_state["attempts"] += 1
    _feed_state["last_check_at"] = dt.datetime.utcnow().isoformat() + "Z"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True,
                                 headers={"User-Agent": _BROWSER_UA}) as client:
        for url in TN_SCRAPE_PAGES:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    _feed_state["last_error"] = f"{url}: HTTP {r.status_code}"
                    continue
                parser = _parse_all_tn_official if "tnlottery.com" in url else _parse_all_from_ctl
                draws = _clean(parser(r.text))
                if draws:
                    await _mark_success(draws, url, now)
                    return [dict(d) for d in draws]
                _feed_state["last_error"] = f"{url}: no draws parsed"
            except Exception as e:
                _feed_state["last_error"] = f"{url}: {e}"
                continue

    # Last-resort: browser-rendered fetch (only if plain HTTP is blocked).
    # Heavy, so rate-limit to at most once per 3 minutes.
    if now - _last_pw_attempt["at"] >= _PW_MIN_INTERVAL:
        _last_pw_attempt["at"] = now
        draws = _clean(await _fetch_via_playwright())
        if draws:
            await _mark_success(draws, _PW_URL, now)
            return [dict(d) for d in draws]

    # Source down: keep last known draw, flag as stale. Never invent a draw.
    _feed_state.update(connected=False, stale=True)
    await _persist_state()
    return []


async def fetch_latest_official_draw() -> Optional[Dict[str, Any]]:
    """Newest real draw, or None. Kept for existing callers."""
    draws = await fetch_recent_official_draws()
    return draws[0] if draws else None


def _parse_all_tn_official(html: str) -> List[Dict[str, Any]]:
    """Parse tnlottery.com winning-numbers page:
    'Draw Number: 934391  1-4-11-...-70  Bulls Eye: 66' (repeated)."""
    import re as _re
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    out = []
    pat = _re.compile(r"Draw\s*Number\s*:?\s*(\d{5,})\s+((?:\d{1,2}\s*-\s*){19}\d{1,2})"
                      r"(?:\s+Bulls?\s*-?\s*Eye\s*:?\s*(\d{1,2}))?", _re.I)
    for m in pat.finditer(text):
        nums = [int(x) for x in _re.split(r"\s*-\s*", m.group(2))]
        d = {"draw_number": int(m.group(1)), "winning_numbers": sorted(nums), "source": "LIVE"}
        if m.group(3):
            d["bulls_eye"] = int(m.group(3))
        out.append(d)
    return out


# Rate-limit expensive Playwright fetches (module-level state).
_last_pw_attempt = {"at": 0.0}
_PW_MIN_INTERVAL = 180.0
_PW_URL = "https://www.comparethelotto.com/us/results-tennessee-keno-to-go"
_PW_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


async def _fetch_via_playwright() -> List[Dict[str, Any]]:
    """Render comparethelotto.com past the anti-bot challenge and parse all
    recent Tennessee Keno-To-Go draws on the page (newest first)."""
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        logger.warning(f"playwright not available: {e}")
        return []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(user_agent=_PW_UA,
                                                viewport={"width": 1280, "height": 900},
                                                locale="en-US")
                await ctx.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = await ctx.new_page()
                try:
                    await page.goto(_PW_URL, timeout=15_000, wait_until="commit")
                except Exception:
                    pass  # let the poll loop wait through the anti-bot spinner
                html = ""
                title = ""
                for _ in range(30):  # up to ~60s (2s * 30)
                    await page.wait_for_timeout(2000)
                    try:
                        title = await page.title()
                        html = await page.content()
                    except Exception:
                        continue
                    if "Latest Results" in title and len(html) > 100_000:
                        break
                if not html or "Latest Results" not in title:
                    logger.info("playwright: never got real content")
                    return []
            finally:
                await browser.close()
        return _parse_all_from_ctl(html)
    except Exception as e:
        logger.warning(f"playwright fetch err: {e}")
        return []


def _parse_all_from_ctl(html: str) -> List[Dict[str, Any]]:
    """Parse comparethelotto.com HTML and return every draw on the page
    (newest first, ~50 draws)."""
    import re as _re
    soup = BeautifulSoup(html, "lxml")
    hist = soup.find(id="historicalResults")
    if not hist:
        return []
    body = hist.find(class_="card-body")
    if not body:
        return []
    out: List[Dict[str, Any]] = []
    dn: Optional[int] = None
    nums: List[int] = []

    def flush():
        if dn and len(nums) == 20:
            out.append({"draw_number": dn, "winning_numbers": sorted(nums), "source": "LIVE"})

    for el in body.children:
        if getattr(el, "name", None) is None:
            continue
        if el.name == "p":
            m = _re.search(r"Draw\s*#(\d+)", el.get_text(" ", strip=True))
            if m:
                flush()
                dn = int(m.group(1))
                nums = []
        elif el.name == "span" and "results-number" in (el.get("class") or []):
            tail = el.get_text(strip=True).split()[-1] if el.get_text(strip=True) else ""
            nm = _re.search(r"(\d+)$", tail)
            if nm:
                n = int(nm.group(1))
                if 1 <= n <= 80:
                    nums.append(n)
        elif el.name == "hr":
            flush()
            dn, nums = None, []
    flush()
    return out


def _parse_latest_from_ctl(html: str) -> Optional[Dict[str, Any]]:
    """Parse comparethelotto.com HTML and return the newest draw only."""
    draws = _parse_all_from_ctl(html)
    return draws[0] if draws else None


def _extract_numbers(data):
    if isinstance(data, dict):
        for k in ("winningNumbers", "numbers", "results", "picks"):
            v = data.get(k)
            if isinstance(v, list) and len(v) == 20:
                return v
    return None


def _extract_draw_number(data):
    if isinstance(data, dict):
        for k in ("drawNumber", "draw_id", "id", "gameId", "gameNumber"):
            v = data.get(k)
            if v is not None:
                return v
    return None


def _scrape_keno_html(html: str) -> Optional[Dict[str, Any]]:
    """Parse TN Lottery Keno To Go page.
    Strategy: find a 'Draw #<n>' label near a cluster of exactly 20 unique 1..80 numbers."""
    try:
        soup = BeautifulSoup(html, "lxml")
        import re as _re

        # 1) Try structured: look for elements whose text is just a number in 1..80
        candidates_numbers = []
        for el in soup.find_all(["span", "li", "div", "td"]):
            txt = (el.get_text(strip=True) or "")
            if _re.fullmatch(r"[1-9]|[1-7]\d|80", txt):
                candidates_numbers.append(int(txt))

        # Find first window of 20 unique numbers
        winning = _first_20_unique(candidates_numbers)

        # 2) Draw number: look for "Draw #123456", "Game 123456", "Draw 123456"
        page_text = soup.get_text(" ", strip=True)
        dn_match = _re.search(r"(?:Draw|Game)\s*#?\s*(\d{4,})", page_text, _re.I)

        if winning and dn_match:
            return {
                "draw_number": int(dn_match.group(1)),
                "winning_numbers": sorted(winning),
                "source": "LIVE",
            }

        # 3) Fallback: loose scan of all numbers in text
        raw = _re.findall(r"\b(\d{1,2})\b", page_text)
        pool = [int(x) for x in raw if 1 <= int(x) <= 80]
        winning = _first_20_unique(pool)
        if winning and dn_match:
            return {
                "draw_number": int(dn_match.group(1)),
                "winning_numbers": sorted(winning),
                "source": "LIVE",
            }
    except Exception:
        pass
    return None


def _first_20_unique(seq):
    seen = set(); out = []
    for n in seq:
        if n in seen: continue
        seen.add(n); out.append(n)
        if len(out) == 20: return out
    return None


def simulate_draw(next_draw_number: int) -> Dict[str, Any]:
    """Practice/Simulated draw only. Never used in Live Mode."""
    nums = sorted(random.sample(range(1, 81), 20))
    return {"draw_number": next_draw_number, "winning_numbers": nums, "source": "SIMULATED"}
