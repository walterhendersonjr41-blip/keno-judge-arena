"""Keno Duel AI — iteration 3: POST /api/system/import-draws contract tests.

Covers: raw TN-Lottery paste parsing, {draws:[...]} JSON form, idempotency,
LIVE-vs-IMPORTED auto-detection + scoring, system status refresh, and the
skip-scoring invariant. Uses synthetic draw numbers 907900-907902 (well beyond
the real feed) and cleans them up afterwards.
"""
import os

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = base_url.rstrip("/") + "/api"

benv = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or benv.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or benv.get("DB_NAME")

TEST_DRAWS = {
    907900: [1, 4, 7, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57],
    907901: [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35, 38, 41, 44, 47, 50, 53, 56, 59],
    907902: [3, 6, 10, 13, 16, 19, 22, 25, 28, 31, 34, 37, 40, 43, 46, 49, 52, 55, 58, 61],
}

RAW_PASTE = """Keno To Go
Draw Number:907900
Draw Date: 07/26/2026 1:05 PM
{nums}
Bulls Eye: 57
Draw Number:907899
Draw Date: 07/26/2026 1:00 PM
""".format(nums="-".join(str(n) for n in TEST_DRAWS[907900]))

STATE = {}


@pytest.fixture(scope="module")
def dbh():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup(dbh):
    yield
    q = {"draw_number": {"$gte": 907890}}
    dbh.keno_draws.delete_many(q)
    dbh.keno_scores.delete_many(q)
    dbh.keno_predictions.delete_many({"target_draw_number": {"$gte": 907890}})
    dbh.keno_releases.delete_many({"target_draw_number": {"$gte": 907890}})
    print("cleanup: removed synthetic draws >= 907890")


def post_import(payload, timeout=120):
    """POST import-draws; tolerate ingress timeout (LLM calls can be slow)."""
    try:
        r = requests.post(f"{API}/system/import-draws", json=payload, timeout=timeout)
        print(f"import-draws -> {r.status_code} {r.text[:300]}")
        return r
    except requests.exceptions.ReadTimeout:
        print("import-draws: ingress read timeout — will verify via DB")
        return None


# --- baseline -----------------------------------------------------------
def test_00_status_baseline():
    r = requests.get(f"{API}/system/status", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "live"
    assert isinstance(d["total_draws"], int)
    STATE["total_draws"] = d["total_draws"]
    STATE["latest"] = d["latest_draw_number"]
    print(f"baseline total_draws={d['total_draws']} latest={d['latest_draw_number']}")


# --- raw paste form -----------------------------------------------------
def test_01_import_raw_paste(dbh):
    r = post_import({"raw": RAW_PASTE})
    if r is not None:
        assert r.status_code == 200, r.text
        body = r.json()
        assert "error" not in body, body
        for k in ("inserted", "skipped_existing", "scored", "received"):
            assert k in body, f"missing key {k} in {body}"
        assert body["received"] == 1, body
        assert body["inserted"] == 1, body
        STATE["first_body"] = body
    doc = dbh.keno_draws.find_one({"draw_number": 907900, "mode": "live"}, {"_id": 0})
    assert doc is not None, "907900 not persisted"
    assert doc["winning_numbers"] == sorted(TEST_DRAWS[907900])
    assert doc["mode"] == "live"
    assert doc.get("bulls_eye") == 57, f"bulls_eye not parsed: {doc.get('bulls_eye')}"
    print(f"907900 stored source={doc['source']}")


def test_02_idempotent_repost(dbh):
    r = post_import({"raw": RAW_PASTE})
    if r is not None:
        body = r.json()
        assert body.get("skipped_existing") == 1, body
        assert body.get("inserted") == 0, body
    assert dbh.keno_draws.count_documents({"draw_number": 907900, "mode": "live"}) == 1


# --- JSON form ----------------------------------------------------------
def test_03_import_json_form(dbh):
    payload = {"draws": [
        {"draw_number": 907902, "winning_numbers": TEST_DRAWS[907902], "bulls_eye": 61},
        {"draw_number": 907901, "winning_numbers": TEST_DRAWS[907901], "bulls_eye": 59},
    ]}
    r = post_import(payload)
    if r is not None:
        body = r.json()
        assert body.get("received") == 2, body
        assert body.get("inserted") == 2, body
        STATE["json_body"] = body
    for dn in (907901, 907902):
        doc = dbh.keno_draws.find_one({"draw_number": dn, "mode": "live"}, {"_id": 0})
        assert doc is not None, f"{dn} not persisted"
        assert doc["winning_numbers"] == sorted(TEST_DRAWS[dn])
        print(f"{dn} stored source={doc['source']}")


def test_04_live_vs_imported_scoring(dbh):
    """A draw with sealed predictions must be LIVE + exactly 3 scores (alpha/beta/gamma);
    a draw with no predictions must be IMPORTED + 0 scores."""
    problems = []
    for dn in (907900, 907901, 907902):
        doc = dbh.keno_draws.find_one({"draw_number": dn, "mode": "live"}, {"_id": 0})
        npred = dbh.keno_predictions.count_documents({"target_draw_number": dn, "mode": "live"})
        scores = list(dbh.keno_scores.find({"draw_number": dn, "mode": "live"}, {"_id": 0}))
        print(f"draw {dn}: source={doc['source']} preds={npred} scores={len(scores)} "
              f"ais={sorted(s['ai_id'] for s in scores)}")
        if doc["source"] == "IMPORTED" and scores:
            problems.append(f"{dn} IMPORTED but has {len(scores)} scores")
        if doc["source"] == "LIVE":
            if len(scores) != 3:
                problems.append(f"{dn} LIVE but has {len(scores)} scores (expected 3)")
            if sorted(s["ai_id"] for s in scores) != ["alpha", "beta", "gamma"]:
                problems.append(f"{dn} LIVE scores AI set wrong: {[s['ai_id'] for s in scores]}")
    assert not problems, problems


def test_05_predictions_generated_for_next(dbh):
    """After importing up to 907902 the AIs must hold sealed tickets for 907903."""
    n = dbh.keno_predictions.count_documents({"target_draw_number": 907903, "mode": "live"})
    assert n == 3, f"expected 3 sealed predictions for 907903, got {n}"


def test_06_status_reflects_import():
    r = requests.get(f"{API}/system/status", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["latest_draw_number"] == 907902, d
    assert d["next_target_draw"] == 907903, d
    assert d["total_draws"] >= STATE["total_draws"] + 3, (d["total_draws"], STATE["total_draws"])


def test_07_invalid_payload():
    r = requests.post(f"{API}/system/import-draws", json={"raw": "nothing useful here"}, timeout=30)
    assert r.status_code == 200
    assert "error" in r.json(), r.text


def test_08_invalid_numbers_rejected(dbh):
    r = requests.post(f"{API}/system/import-draws", json={"draws": [
        {"draw_number": 907890, "winning_numbers": [1, 2, 3]},
        {"draw_number": 907891, "winning_numbers": list(range(70, 90))},
    ]}, timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert "error" in body, f"invalid draws were accepted: {body}"
    assert dbh.keno_draws.count_documents({"draw_number": {"$in": [907890, 907891]}}) == 0


# --- existing endpoints still healthy -----------------------------------
@pytest.mark.parametrize("path", [
    "/draws?limit=5&mode=live",
    "/predictions/upcoming",
    "/leaderboard",
    "/judge/picks",
    "/agents/activity",
])
def test_09_existing_endpoints(path):
    r = requests.get(f"{API}{path}", timeout=45)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    data = r.json()
    assert isinstance(data, (list, dict))
    print(f"{path} -> {type(data).__name__} len={len(data)}")


def test_10_upcoming_has_three_sealed():
    r = requests.get(f"{API}/predictions/upcoming", timeout=45)
    assert r.status_code == 200
    data = r.json()
    preds = data.get("predictions") if isinstance(data, dict) else data
    assert isinstance(preds, list), data
    assert len(preds) == 3, f"expected 3 upcoming predictions, got {len(preds)}"
    assert sorted(p["ai_id"] for p in preds) == ["alpha", "beta", "gamma"]


def test_11_no_mongo_object_id():
    def walk(obj, path):
        if isinstance(obj, dict):
            assert "_id" not in obj, f"{path} leaks mongo _id"
            for v in obj.values():
                walk(v, path)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, path)

    for path in ("/draws?limit=3&mode=live", "/leaderboard", "/agents/activity"):
        r = requests.get(f"{API}{path}", timeout=45)
        walk(r.json(), path)


# --- global invariants --------------------------------------------------
def test_12_imported_draws_never_scored(dbh):
    nums = [d["draw_number"] for d in dbh.keno_draws.find({"source": "IMPORTED", "mode": "live"}, {"draw_number": 1})]
    bad = list(dbh.keno_scores.find({"draw_number": {"$in": nums}, "mode": "live"}, {"_id": 0, "draw_number": 1, "ai_id": 1}))
    assert bad == [], f"IMPORTED draws scored: {bad[:10]}"


def test_13_live_draws_have_three_scores(dbh):
    bad = []
    for d in dbh.keno_draws.find({"source": "LIVE", "mode": "live"}, {"draw_number": 1}):
        c = dbh.keno_scores.count_documents({"draw_number": d["draw_number"], "mode": "live"})
        if c != 3:
            bad.append((d["draw_number"], c))
    assert not bad, f"LIVE draws without exactly 3 scores: {bad}"


def test_14_no_duplicate_draw_numbers(dbh):
    dupes = list(dbh.keno_draws.aggregate([
        {"$group": {"_id": {"n": "$draw_number", "m": "$mode"}, "c": {"$sum": 1}}},
        {"$match": {"c": {"$gt": 1}}},
    ]))
    assert dupes == [], f"duplicate draws: {dupes[:10]}"
