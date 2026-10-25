# Keno Judge Arena

A 24/7 research lab that tests whether AI can beat random chance on Tennessee Keno. Three independent Player AIs (Alpha, Beta, Gamma) predict every upcoming draw. A neutral Judge AI scores them against the official result, keeps lifetime leaderboards and consensus stats, and only releases a pick if the evidence ever shows a player doing better than random (by default it withholds). Keno draws are random: this is a research/entertainment project, not betting advice.

## Live version (GitHub Pages, free)
**https://walterhendersonjr41-blip.github.io/keno-judge-arena/** runs the arena live with no server and no paid services:

- `.github/workflows/draws.yml` runs `scripts/arena-tick.mjs` about every 4 minutes (the draw cadence). Each Actions run loops for about 55 minutes and then dispatches the next run itself. A 15-minute cron restarts the chain if it ever breaks (GitHub's cron is often late). Each tick:
  - reads real Tennessee Keno To Go results from comparethelotto.com (direct, with a free allorigins.win fallback),
  - scores any newly published draw against tickets that were sealed *before* the draw was first seen (LIVE). Draws with no earlier tickets are IMPORTED and not scored,
  - updates wins/losses, reputation, ranks, streaks, XP, head-to-head, badges, the champion, consensus, Judge press statements and private reflections,
  - has Alpha, Beta and Gamma seal tickets for the next 3 draws and asks the Judge to release or withhold (it defaults to withhold),
  - force-pushes the shared `state.json` to the orphan `data` branch, so the Pages site isn't rebuilt on every tick.
- `index.html` (with `engine.js`, the JS port of the backend scoring and stats logic) reads `state.json` from the `data` branch every 60 s.
- The LLM is the free, keyless Pollinations text API (`openai` model). If it can't be reached, the ticket is a clearly labelled fallback sample.
- Draw numbers are never invented. Every draw comes from the source page.
- Options: `?live=1` also checks the source page from the browser through a free CORS proxy. `?state=<url>` loads a different state file.
- `index.html.bak` is the previous static overview page.

The original FastAPI/React app below still needs its own backend.

## Layout
- `backend/` – FastAPI server (`server.py`), players (`agents.py`), judge (`judge.py`), MongoDB layer (`db.py`), draw source + paste import (`keno_source.py`), reflection loop (`research_loop.py`), `requirements.txt`, `.env.example`
- `backend/tests/` – pytest suite (`test_draw_sync.py` runs offline with mongomock; the others expect a running stack and read `/app/...` env paths from the original container)
- `frontend/` – React + Tailwind + shadcn/ui (pages: Arena, Leaderboard, Draw History, Judge Console, Judge Picks, AI Profiles, Hall of Fame, Press Room), `.env.example`
- `scripts/backfill_history.py` – Playwright backfill of past draws
- `docs/PRD.md`, `docs/design_guidelines.json` – product notes and design system

## Run
```
cd backend && cp .env.example .env   # set MONGO_URL and your own EMERGENT_LLM_KEY
pip install -r requirements.txt && uvicorn server:app --port 8001
cd ../frontend && cp .env.example .env && yarn install && yarn start
```
The LLM calls use the `emergentintegrations` package from the Emergent platform.

Not included: `.env` files, `node_modules`, the Python venv, caches, test-account notes, and the Emergent/PostHog analytics snippet from `frontend/public/index.html`.

Created by Walter Henderson Jr.
