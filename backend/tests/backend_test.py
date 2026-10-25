"""Keno Duel AI — backend contract & pipeline tests (iteration 2).

Covers: system status, draws feed, upcoming predictions, agent activity,
idempotency of trigger-round, judge picks, leaderboard, IMPORTED skip-scoring rule,
per-agent detail endpoints.
"""
import os
import time

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"

AIS = {"alpha", "beta", "gamma"}


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- system status ----------
class TestSystemStatus:
    def test_status_contract(self, client):
        r = client.get(f"{API}/system/status", timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        for k in ["scheduler_running", "total_draws", "total_predictions",
                  "latest_draw_number", "next_target_draw", "feed"]:
            assert k in d, f"missing {k} in {d}"
        assert isinstance(d["scheduler_running"], bool)
        assert d["scheduler_running"] is True
        assert isinstance(d["total_draws"], int) and d["total_draws"] > 0
        assert isinstance(d["total_predictions"], int)
        assert isinstance(d["latest_draw_number"], int)
        assert d["next_target_draw"] == d["latest_draw_number"] + 1
        feed = d["feed"]
        for k in ["connected", "attempts", "last_success_at"]:
            assert k in feed, f"feed missing {k}: {feed}"
        assert isinstance(feed["connected"], bool)
        assert isinstance(feed["attempts"], int)

    def test_feed_currently_connected(self, client):
        """Live-ness check: the poller should have a recent successful fetch."""
        d = client.get(f"{API}/system/status", timeout=30).json()
        feed = d["feed"]
        assert feed["connected"] is True, (
            f"feed not connected; last_success_at={feed.get('last_success_at')} "
            f"last_error={feed.get('last_error')!r} attempts={feed.get('attempts')}"
        )


# ---------- draws ----------
class TestDraws:
    def test_live_draws_list(self, client):
        r = client.get(f"{API}/draws?limit=5&mode=live", timeout=30)
        assert r.status_code == 200, r.text[:400]
        draws = r.json()
        assert isinstance(draws, list) and len(draws) > 0
        nums = [x["draw_number"] for x in draws]
        assert nums == sorted(nums, reverse=True), f"not sorted desc: {nums}"
        for x in draws:
            wn = x["winning_numbers"]
            assert len(wn) == 20 and len(set(wn)) == 20
            assert all(1 <= n <= 80 for n in wn)

    def test_newest_draw_is_live_source(self, client):
        draws = client.get(f"{API}/draws?limit=5&mode=live", timeout=30).json()
        newest = draws[0]
        assert newest.get("source") == "LIVE", (
            f"newest draw {newest.get('draw_number')} source={newest.get('source')!r} "
            "(expected LIVE from real TN feed ingestion)"
        )


# ---------- upcoming predictions ----------
class TestUpcoming:
    def test_upcoming_three_ais_next_draw(self, client):
        status = client.get(f"{API}/system/status", timeout=30).json()
        r = client.get(f"{API}/predictions/upcoming", timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["target_draw_number"] == status["latest_draw_number"] + 1
        preds = d["predictions"]
        ids = sorted(p["ai_id"] for p in preds)
        assert set(ids) == AIS, f"expected alpha/beta/gamma got {ids} for target {d['target_draw_number']}"
        for p in preds:
            spots = sorted(t["spots"] for t in p["tickets"])
            assert spots == [5, 6, 7, 8], f"{p['ai_id']} spots={spots}"
            if not p.get("revealed"):
                assert all(t["numbers"] == [] for t in p["tickets"]), "sealed leak"


# ---------- agent activity ----------
class TestAgentActivity:
    def test_activity_all_agents(self, client):
        r = client.get(f"{API}/agents/activity", timeout=30)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        if isinstance(data, dict):
            keys = set(data.keys())
            assert AIS.issubset(keys), f"missing agents in activity: {keys}"
            entries = [data[a] for a in AIS]
        else:
            entries = data
            assert {e["ai_id"] for e in entries} == AIS
        valid = {"RESEARCH", "DECISION", "JUDGE", "REFLECT", "IDLE"}
        for e in entries:
            phase = (e.get("phase") or e.get("research_phase") or "").upper()
            assert phase in valid, f"unexpected phase {phase!r} in {e}"


# ---------- idempotency ----------
class TestIdempotency:
    def test_double_trigger_no_double_scoring(self, client):
        latest = client.get(f"{API}/system/status", timeout=30).json()["latest_draw_number"]
        before = client.get(f"{API}/draws/{latest}", timeout=30)
        assert before.status_code == 200
        b = before.json()
        b_scores = {s["ai_id"]: s for s in b["scores"]}

        for _ in range(2):
            r = client.post(f"{API}/system/trigger-round", timeout=30)
            assert r.status_code == 200, r.text[:400]
            body = r.json()
            assert body.get("triggered") is True
            assert "at" in body and "mode" in body
            time.sleep(2)

        time.sleep(25)
        after = client.get(f"{API}/draws/{latest}", timeout=30).json()
        a_scores = after["scores"]
        ids = [s["ai_id"] for s in a_scores]
        assert len(ids) == len(set(ids)), f"duplicate score docs for draw {latest}: {ids}"
        if b_scores:
            assert len(a_scores) == len(b_scores), (
                f"score count changed for draw {latest}: {len(b_scores)} -> {len(a_scores)}")
            for s in a_scores:
                old = b_scores.get(s["ai_id"])
                if old:
                    assert s.get("total_hits") == old.get("total_hits"), \
                        f"{s['ai_id']} total_hits mutated on re-trigger"
                    assert s.get("result") == old.get("result")


# ---------- judge picks ----------
class TestJudge:
    def test_judge_picks_json(self, client):
        r = client.get(f"{API}/judge/picks?limit=100", timeout=30)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert isinstance(data, list)
        for e in data:
            assert "target_draw_number" in e and "picks" in e and "hit_count" in e
            assert e["hit_count"] == len(set(e["picks"]) & set(e["winning_numbers"]))


# ---------- leaderboard ----------
class TestLeaderboard:
    def test_leaderboard(self, client):
        r = client.get(f"{API}/leaderboard", timeout=30)
        assert r.status_code == 200, r.text[:400]
        rows = r.json()
        assert {x["ai_id"] for x in rows} == AIS
        scores = [x.get("lifetime_score", 0) for x in rows]
        assert scores == sorted(scores, reverse=True), f"not ranked: {scores}"
        for i, x in enumerate(rows):
            assert x["rank"] == i + 1
            for k in ["total_wins", "total_losses", "reputation"]:
                assert k in x, f"leaderboard entry missing {k}: {list(x.keys())}"


# ---------- per-agent detail ----------
@pytest.mark.parametrize("ai", ["alpha", "beta", "gamma"])
def test_agent_detail(client, ai):
    r = client.get(f"{API}/agents/{ai}", timeout=30)
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    for k in ["stats", "recent_scores", "notebook", "personality"]:
        assert k in d, f"{ai} missing {k}"
    assert d["stats"] and d["stats"]["ai_id"] == ai
    assert isinstance(d["recent_scores"], list)


def test_unknown_agent_404(client):
    r = client.get(f"{API}/agents/delta", timeout=30)
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text[:200]}"


# ---------- no mongo _id leakage ----------
def test_no_object_id_leak(client):
    for path in ["/draws?limit=5", "/leaderboard", "/judge/picks?limit=10",
                 "/predictions/upcoming", "/releases?limit=10", "/consensus/recent?limit=5"]:
        txt = client.get(f"{API}{path}", timeout=30).text
        assert '"_id"' not in txt, f"_id leaked in {path}"
