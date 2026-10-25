# Keno Duel AI — PRD

## Original Problem Statement
Build an AI system called "Keno Duel AI" that operates as a 24/7 Tennessee Keno research laboratory. Three independent Player AIs (Alpha, Beta, Gamma) compete on every draw. A neutral Judge AI scores predictions against future official draws, maintains lifetime leaderboards, tracks consensus, and decides whether any prediction should be released to the user. System never stops learning, never stops competing.

## Architecture
- **Backend** (FastAPI, Python): scheduler-driven round orchestration; each round = (1) fetch/generate draw, (2) score any prediction targeting that draw, (3) generate three fresh predictions for the next draw in parallel, (4) Judge decides on release.
- **AIs**: Alpha=OpenAI GPT-5.2, Beta=Anthropic Claude Sonnet 4.5, Gamma=Google Gemini 3 Flash, Judge=OpenAI GPT-5.2. Via Emergent Universal LLM Key + emergentintegrations.
- **Persistence**: MongoDB collections — keno_draws, keno_predictions, keno_scores, keno_ai_stats, keno_consensus, keno_releases.
- **Draw source**: TN Lottery Keno (best-effort scraping) with fair simulation fallback.
- **Scheduler**: APScheduler every 60s (demo cadence; real TN Keno is ~5 min).
- **Frontend** (React 19 + Tailwind + shadcn): Bloomberg-terminal / esports-leaderboard aesthetic.

## User Personas
1. **Researcher/observer** — watches the arena, inspects lifetime stats, evaluates whether the Judge finds any AI credibly outperforming random.
2. **Curious ticket-buyer** — checks the Judge's rare "released" recommendations (defaulted to withhold unless evidence supports release).

## Core Requirements (Static)
- Player AIs cannot see each other's predictions until Judge scores the draw.
- Judge is the only entity with full visibility.
- Every draw permanently recorded; no resets.
- Multi-ticket prediction (5/6/7/8-pick).
- Continuous 24/7 operation.

## Implemented (Feb 2026)
- ✅ 4-agent architecture (Alpha, Beta, Gamma, Judge) with distinct models
- ✅ Autonomous scheduler + manual trigger endpoint
- ✅ Deterministic scoring, consensus computation, XP/rep updates
- ✅ Privacy invariant on upcoming predictions
- ✅ Draw source with simulation fallback (TN Lottery URLs attempted first)
- ✅ Frontend pages: Arena, Leaderboard, Draw History, Judge Console, AI Profiles, Judge Picks (verified ledger)
- ✅ 12/12 backend tests passing
- ✅ Historical backfill script `/app/scripts/backfill_history.py` — Playwright-based scraper for comparethelotto.com, inserts ~50 real TN draws (source=IMPORTED) with idempotency (2026-02-22)
- ✅ **"Every draw plays" pipeline (2026-02-22)** — 30s poller now runs the full round pipeline (score → judge → press → next-round predictions) on every new live draw, not just ingests. Added `_catch_up_unscored` watchdog on the 240s scheduler as backup. Idempotent: re-triggering a scored draw is a no-op. IMPORTED backfill draws are skipped from scoring (no predictions ever targeted them).
- ✅ **Manual paste ingest + decoupled scheduler (2026-02-26)** — Added `POST /api/system/import-draws` that accepts raw TN Lottery pasted text or JSON. Parser handles `Draw Number:XXX / nn-nn-nn... / Bulls Eye:N`. Auto-detects LIVE vs IMPORTED per draw (based on whether predictions target it). Split saturated 30s poller into `pipeline_tick` (30s, DB-only, catches up unscored + generates predictions) + `feed_fetch_tick` (180s, heavy Playwright). Pipeline saturation dropped from ~85% skips to 0. 19/19 new tests pass.
- ✅ **Lifespan shutdown hardening (2026-02-26)** — cancels in-flight asyncio tasks (including Playwright fetches) with 3s timeout so uvicorn --reload no longer hangs.
- ⚠️ **Known limitation**: Live scrapers (tnlottery.com + comparethelotto.com) are Cloudflare/JS-gated from container IP. Manual paste is the working escape hatch until an alternate provider is added.

## Backlog (P1/P2)
- P1: Verify JudgePicks JSON error — RESOLVED (2026-02-22): endpoint returns valid JSON `[]` when no picks released; page renders empty-state cleanly
- P1: Real TN Lottery scraper (tnlottery.com is behind Cloudflare; comparethelotto works via Playwright but rate-limits aggressively)
- P1: Player AI performance charts vs random baseline
- P1: Historical export (CSV) for researchers `/api/history.csv`
- P2: Season logic — Season Champion crowning + reset after N draws
- P2: Diary Highlights carousel on homepage
- P2: WebSocket live push (replace polling)
- P2: Championship title assignment logic (weekly/monthly cycles)
- P2: Ticker "match log" component on Arena
- P2: Advanced Judge Elo/Bayesian reputation model
- P2: Refactor `db.py::apply_round_result` cyclomatic complexity
- P2: Split monolithic `PlayerAICard.jsx` and `AIProfile.jsx`
