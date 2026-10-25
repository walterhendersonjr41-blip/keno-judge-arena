# Keno Judge Arena

A 24/7 research lab that tests whether AI can beat random chance on Tennessee Keno. Three independent Player AIs (Alpha, Beta, Gamma) predict every upcoming draw. A neutral Judge AI scores them against the official result, keeps lifetime leaderboards and consensus stats, and only releases a pick if the evidence ever shows a player doing better than random (by default it withholds). Keno draws are random: this is a research/entertainment project, not betting advice.

`index.html` at the repo root is an overview page for GitHub Pages. The app itself needs its backend.

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
