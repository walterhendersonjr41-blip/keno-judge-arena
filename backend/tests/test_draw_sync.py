"""Offline tests for the Keno draw-sync fix (mongomock, no real Mongo/LLM)."""
import os, sys, types, asyncio
from pathlib import Path
import pytest

BACKEND = Path(os.environ.get("KENO_BACKEND", str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "keno_test")
# Stub the Emergent LLM SDK (not installed here; never called in these tests)
m = types.ModuleType("emergentintegrations"); ml = types.ModuleType("emergentintegrations.llm")
mc = types.ModuleType("emergentintegrations.llm.chat")
mc.LlmChat = object; mc.UserMessage = object
sys.modules.update({"emergentintegrations": m, "emergentintegrations.llm": ml,
                    "emergentintegrations.llm.chat": mc})

from mongomock_motor import AsyncMongoMockClient
import db, server, keno_source  # noqa: E402

FIXTURE = Path(__file__).with_name("ctl_fixture.html").read_text()


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    mdb = AsyncMongoMockClient()["t"]
    for name in ["draws_col", "predictions_col", "scores_col", "stats_col", "consensus_col",
                 "releases_col", "press_col", "audit_col", "system_col"]:
        coll = getattr(mdb, getattr(db, name).name)
        monkeypatch.setattr(db, name, coll)
    processed = []
    async def fake_process(draw_doc, mode):
        processed.append(draw_doc["draw_number"])
    monkeypatch.setattr(server, "_process_draw", fake_process)
    async def fake_gen(target, mode):
        pass
    monkeypatch.setattr(server, "generate_all_predictions", fake_gen)
    keno_source._cache.update(draws=None, expires_at=0.0)
    yield processed


def run(c): return asyncio.get_event_loop().run_until_complete(c) if False else asyncio.run(c)


def nums(k):  # deterministic valid 20-number set
    return sorted({(k * 7 + i * 3) % 80 + 1 for i in range(40)})[:20]


def real_window(latest, n=50):
    return [{"draw_number": latest - i, "winning_numbers": nums(latest - i), "source": "LIVE"}
            for i in range(n)]


def use_source(monkeypatch, draws):
    async def fake():
        return [dict(d) for d in draws]
    monkeypatch.setattr(server, "fetch_recent_official_draws", fake)


async def seed_live(upto, count=5):
    for dn in range(upto - count + 1, upto + 1):
        await db.draws_col.insert_one({"draw_number": dn, "winning_numbers": nums(dn),
                                       "source": "LIVE", "mode": "live", "drawn_at": "2026-01-01"})


# ---------- parsers ----------
def test_ctl_parser_reads_all_draws_exactly():
    draws = keno_source._clean(keno_source._parse_all_from_ctl(FIXTURE))
    assert len(draws) == 50
    assert draws[0]["draw_number"] == 934549
    assert draws[0]["winning_numbers"] == [4, 7, 10, 11, 17, 18, 20, 23, 28, 29, 30, 32,
                                           36, 41, 43, 54, 57, 68, 74, 79]
    assert [d["draw_number"] for d in draws] == list(range(934549, 934499, -1))


def test_old_generic_scraper_was_wrong_on_same_page():
    # documents the bug: it grabbed a stray "5" (menu badge) and dropped 79
    bad = keno_source._scrape_keno_html(FIXTURE)
    assert bad["winning_numbers"] != keno_source._parse_latest_from_ctl(FIXTURE)["winning_numbers"]


def test_tn_official_parser():
    html = ("<div>Draw Number: 934391 1-4-11-12-13-14-19-22-25-29-36-43-45-48-55-60-62-66-67-70 "
            "Bulls Eye: 66</div><div>Draw Number:934390</div><div>3-5-8-9-12-13-17-18-19-22-30-32"
            "-35-42-43-46-49-51-60-62</div><div>Bulls Eye:32</div>")
    d = keno_source._clean(keno_source._parse_all_tn_official(html))
    assert [x["draw_number"] for x in d] == [934391, 934390]
    assert d[0]["bulls_eye"] == 66 and len(d[1]["winning_numbers"]) == 20


# ---------- sync ----------
def test_behind_by_200_resyncs_to_real_latest(monkeypatch, fresh_db):
    real_latest = 934549
    async def go():
        await seed_live(real_latest - 200)                     # app stuck 200 draws behind
        await db.predictions_col.insert_one({"ai_id": "alpha", "mode": "live",
                                             "target_draw_number": real_latest - 199})
        use_source(monkeypatch, real_window(real_latest))
        res = await server.sync_live_draws()
        latest = await db.get_latest_draw_number("live")
        status = await server.system_status("live")
        up = await server.upcoming_predictions("live")
        between = await db.draws_col.count_documents(
            {"mode": "live", "draw_number": {"$gt": real_latest - 200, "$lt": real_latest - 49}})
        imported = await db.draws_col.count_documents({"mode": "live", "source": "IMPORTED"})
        return res, latest, status, up, between, imported
    res, latest, status, up, between, imported = run(go())
    assert res["inserted"] == 50 and res["db_latest_before"] == real_latest - 200
    assert latest == real_latest
    assert status["next_target_draw"] == real_latest + 1
    assert up["target_draw_number"] == real_latest + 1
    assert between == 0          # nothing invented for draws the source didn't give us
    assert imported == 50        # nobody predicted them -> history only, not scored
    assert fresh_db == []        # no NO-PLAY rounds run for missed draws


def test_predicted_draw_is_scored_live(monkeypatch, fresh_db):
    async def go():
        await seed_live(934548)
        await db.predictions_col.insert_one({"ai_id": "alpha", "mode": "live",
                                             "target_draw_number": 934549})
        use_source(monkeypatch, real_window(934549, 3))
        res = await server.sync_live_draws()
        doc = await db.draws_col.find_one({"draw_number": 934549})
        return res, doc
    res, doc = run(go())
    assert res["inserted"] == 1 and res["scored"] == 1
    assert doc["source"] == "LIVE" and fresh_db == [934549]


def test_source_down_keeps_last_known_and_never_increments(monkeypatch, fresh_db):
    async def go():
        await seed_live(907553)
        use_source(monkeypatch, [])
        for _ in range(3):
            res = await server.sync_live_draws()
        return res, await db.get_latest_draw_number("live"), await db.draws_col.count_documents({})
    res, latest, count = run(go())
    assert res["ok"] is False and latest == 907553 and count == 5


def test_override_cleared_and_mismatch_audited(monkeypatch, fresh_db):
    async def go():
        await seed_live(934540)
        await db.draws_col.update_one({"draw_number": 934540}, {"$set": {"winning_numbers": list(range(1, 21))}})
        await db.system_col.insert_one({"_id": "target_override:live", "next_target": 934545})
        use_source(monkeypatch, real_window(934549, 20))
        await server.sync_live_draws()
        ov = await server._get_next_target_override("live")
        mm = await db.audit_col.count_documents({"event": "draw_mismatch"})
        return ov, mm
    ov, mm = run(go())
    assert ov is None and mm == 1


def test_fetch_failure_marks_stale(monkeypatch):
    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise RuntimeError("offline")
    monkeypatch.setattr(keno_source.httpx, "AsyncClient", Boom)
    async def no_pw(): return []
    monkeypatch.setattr(keno_source, "_fetch_via_playwright", no_pw)
    assert asyncio.run(keno_source.fetch_recent_official_draws()) == []
    st = keno_source.feed_status()
    assert st["stale"] is True and st["connected"] is False


@pytest.mark.skipif(not os.environ.get("KENO_LIVE"), reason="set KENO_LIVE=1 for network test")
def test_live_source():
    keno_source._cache.update(draws=None, expires_at=0.0)
    d = asyncio.run(keno_source.fetch_recent_official_draws())
    print("LIVE latest:", d[0] if d else None, keno_source.feed_status().get("source_url"))
    assert d and d[0]["draw_number"] > 900000 and len(d[0]["winning_numbers"]) == 20
