"""DB-level invariants: IMPORTED draws must be context-only (never scored)."""
import os

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or env.get("DB_NAME")


@pytest.fixture(scope="module")
def dbh():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def test_imported_draws_not_scored(dbh):
    imported = list(dbh.keno_draws.find({"source": "IMPORTED"}, {"_id": 0, "draw_number": 1, "mode": 1}))
    assert len(imported) > 0, "no IMPORTED draws found — backfill missing"
    print(f"IMPORTED draws: {len(imported)}")
    nums = [d["draw_number"] for d in imported]
    scored = list(dbh.keno_scores.find({"draw_number": {"$in": nums}}, {"_id": 0, "draw_number": 1, "ai_id": 1, "result": 1}))
    assert scored == [], f"IMPORTED draws were scored: {scored[:10]}"


def test_no_no_play_scores(dbh):
    bad = list(dbh.keno_scores.find({"result": "NO_PLAY"}, {"_id": 0}).limit(50))
    assert bad == [], f"NO_PLAY scores exist: {bad[:5]}"


def test_live_draws_all_scored(dbh):
    """Every LIVE draw should have 3 scores (one per AI)."""
    live = list(dbh.keno_draws.find({"source": "LIVE", "mode": "live"}, {"_id": 0, "draw_number": 1}).sort("draw_number", -1))
    print(f"LIVE draws: {len(live)}")
    unscored = []
    for d in live:
        c = dbh.keno_scores.count_documents({"draw_number": d["draw_number"], "mode": "live"})
        if c != 3:
            unscored.append((d["draw_number"], c))
    assert not unscored, f"LIVE draws with != 3 scores: {unscored[:20]} (total {len(unscored)}/{len(live)})"


def test_source_distribution(dbh):
    pipeline = [{"$group": {"_id": {"mode": "$mode", "source": "$source"}, "n": {"$sum": 1}}}]
    print("draw source distribution:", list(dbh.keno_draws.aggregate(pipeline)))
    print("scores count:", dbh.keno_scores.count_documents({}))
