"""Keno Duel AI — main FastAPI server (v2 with Live Mode, personalities, ranks, press, seasons)."""
import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from models import (
    Draw, Prediction, Ticket, PredictionScore, TicketScore,
    AIStats, ConsensusRecord, JudgeRelease, PressStatement, now_iso,
)
from agents import (
    AGENT_CONFIG, generate_player_prediction, judge_release_decision, judge_press_statement,
)
from judge import score_prediction, rank_predictions, compute_xp, compute_consensus
from keno_source import (
    fetch_latest_official_draw, fetch_recent_official_draws, simulate_draw, feed_status,
    set_persist_hook, hydrate_feed_state,
)
import research_loop
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("keno_duel")

scheduler = AsyncIOScheduler()
round_lock = asyncio.Lock()
DRAW_INTERVAL_SECONDS = int(os.environ.get("KENO_DRAW_INTERVAL", "60"))
SEASON_DRAWS = int(os.environ.get("KENO_SEASON_DRAWS", "1000"))
FEED_INTERVAL_SECONDS = int(os.environ.get("KENO_FEED_INTERVAL", "60"))

MODE_STATE = {"mode": "live"}  # "practice" | "live" — Live is default (plays TN forever)

DEFAULT_AI_STATS = [
    AIStats(
        ai_id=aid, display_name=cfg["display_name"], model_name=cfg["model"],
        accent=cfg["accent"], personality=cfg["personality"],
        personality_tag=cfg["personality_tag"],
    ).model_dump()
    for aid, cfg in AGENT_CONFIG.items()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.ensure_indexes()
    await db.init_default_stats(DEFAULT_AI_STATS, "practice")
    await db.init_default_stats(DEFAULT_AI_STATS, "live")

    # Hydrate feed_state from Mongo + register persistence hook
    saved = await db.system_col.find_one({"_id": "feed_state"})
    if saved: hydrate_feed_state(saved)
    async def persist_feed(state: dict):
        await db.system_col.update_one({"_id": "feed_state"}, {"$set": state}, upsert=True)
    set_persist_hook(persist_feed)

    scheduler.add_job(run_next_round_safe, "interval",
                      seconds=DRAW_INTERVAL_SECONDS, id="keno_round",
                      coalesce=True, max_instances=1)
    scheduler.add_job(research_loop.heartbeat, "interval",
                      seconds=15, id="research_heartbeat",
                      coalesce=True, max_instances=1)
    # Fast pipeline tick: no network — just score any unscored LIVE draws
    # already sitting in the DB and keep next-draw predictions fresh.
    scheduler.add_job(pipeline_tick, "interval",
                      seconds=30, id="pipeline_tick",
                      coalesce=True, max_instances=1)
    # Feed sync with the real TN Keno game (draws every 4 min). Default 60s.
    scheduler.add_job(feed_fetch_tick, "interval",
                      seconds=FEED_INTERVAL_SECONDS, id="feed_fetch",
                      coalesce=True, max_instances=1,
                      next_run_time=datetime.now(timezone.utc))  # sync right at startup
    scheduler.start()
    logger.info(f"Scheduler up · interval={DRAW_INTERVAL_SECONDS}s")
    yield
    # Shutdown: pause scheduler first (stops new jobs), then cancel in-flight
    # tasks so Playwright browsers get torn down before uvicorn kills us.
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    # Cancel any lingering asyncio tasks (e.g. Playwright fetch) so uvicorn
    # can shut down cleanly instead of hanging on subprocess pipes.
    loop = asyncio.get_running_loop()
    pending = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for t in pending:
        t.cancel()
    if pending:
        try:
            await asyncio.wait(pending, timeout=3.0)
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)
api = APIRouter(prefix="/api")


async def _get_next_target_override(mode: str) -> Optional[int]:
    """User-set override for the next-draw target (used when the app is behind
    the real TN Keno game and the user tells us where to resume from)."""
    doc = await db.system_col.find_one({"_id": f"target_override:{mode}"})
    return int(doc["next_target"]) if doc and doc.get("next_target") else None


async def _clear_next_target_override(mode: str):
    await db.system_col.delete_one({"_id": f"target_override:{mode}"})


async def pipeline_tick():
    """FAST tick (30s, no network). Ensures every LIVE draw in the DB gets
    played: catches up unscored draws and keeps next-draw predictions fresh."""
    if MODE_STATE["mode"] != "live":
        return
    try:
        async with round_lock:
            await _catch_up_unscored("live")
            latest = await db.get_latest_draw_number("live") or 0
            override = await _get_next_target_override("live")
            target = max(latest + 1, override) if override else latest + 1
            if target:
                await generate_all_predictions(target, "live")
    except Exception as e:
        logger.warning(f"pipeline_tick err: {e}")


async def feed_fetch_tick():
    """SLOW tick. Pulls the real recent TN Keno draws and resyncs the arena
    to the real current draw (see sync_live_draws)."""
    if MODE_STATE["mode"] != "live":
        return
    try:
        await sync_live_draws()
    except Exception as e:
        logger.warning(f"feed_fetch_tick err: {e}")


async def sync_live_draws() -> Dict[str, Any]:
    """Resync LIVE mode to the real Tennessee Keno To Go game.

    * Fetches the real recent draws (newest ~50) from the source.
    * Inserts every real draw in that window that is missing from the DB
      (backfills gaps; if the app is further behind than the window it simply
      jumps to the real draws — nothing is ever invented).
    * A draw is scored (LIVE) only if AI tickets were sealed for it BEFORE
      this sync; otherwise it is stored as IMPORTED history (no NO-PLAY spam,
      no LLM spend).
    * If the source fails, nothing changes: last known draw stays, the feed
      is flagged stale. There is no counter that increments on its own.
    """
    real = await fetch_recent_official_draws()
    if not real:
        return {"ok": False, "reason": "source unavailable", "inserted": 0}
    nums = [d["draw_number"] for d in real]
    db_latest_before = await db.get_latest_draw_number("live") or 0
    existing = {d["draw_number"]: d for d in await db.draws_col.find(
        {"mode": "live", "draw_number": {"$in": nums}}, {"_id": 0}).to_list(len(nums))}
    # Snapshot which draws already had sealed predictions BEFORE inserting.
    predicted = set(await db.predictions_col.distinct(
        "target_draw_number", {"mode": "live", "target_draw_number": {"$in": nums}}))

    inserted = scored = 0
    for rec in sorted(real, key=lambda r: r["draw_number"]):  # oldest first
        dn = rec["draw_number"]
        if dn in existing:
            if sorted(existing[dn].get("winning_numbers", [])) != rec["winning_numbers"]:
                await db.audit("draw_mismatch", {"n": dn, "stored": existing[dn].get("winning_numbers"),
                                                 "real": rec["winning_numbers"]}, "live")
            continue
        is_live = dn in predicted
        draw_doc = Draw(draw_number=dn, winning_numbers=rec["winning_numbers"],
                        source="LIVE" if is_live else "IMPORTED", mode="live").model_dump()
        if rec.get("bulls_eye") is not None:
            draw_doc["bulls_eye"] = int(rec["bulls_eye"])
        try:
            await db.draws_col.insert_one(draw_doc)
        except Exception:
            continue  # race with another ingest; harmless
        inserted += 1
        await db.audit("history_ingested", {"n": dn, "src": draw_doc["source"]}, "live")
        if is_live:
            async with round_lock:
                await _process_draw(draw_doc, "live")
            scored += 1

    real_latest = nums[0]
    override = await _get_next_target_override("live")
    if override and real_latest >= override:
        await _clear_next_target_override("live")  # caught up; manual target no longer needed
    if real_latest - db_latest_before > 1:
        logger.info(f"[feed] resynced: app was at #{db_latest_before}, real game at #{real_latest}")
    if inserted:
        logger.info(f"[feed] ingested {inserted} real draw(s), scored {scored}, latest #{real_latest}")
    return {"ok": True, "real_latest": real_latest, "db_latest_before": db_latest_before,
            "inserted": inserted, "scored": scored}


async def import_draws_batch(records: List[Dict[str, Any]], source: str = "IMPORTED",
                             context_only: bool = False) -> Dict[str, int]:
    """Ingest an ordered batch of draws (oldest first is fine — we sort). Any
    draw with sealed predictions targeting it gets scored (source='LIVE');
    all others become historical context (source='IMPORTED'). Idempotent.
    If context_only=True, ALL draws are stored as IMPORTED without invoking
    the LLM pipeline — cheap way to backfill history."""
    inserted = skipped = scored = 0
    # Ensure sorted ascending by draw_number so the round pipeline advances forward
    records = sorted(records, key=lambda r: r["draw_number"])
    for rec in records:
        dn = rec["draw_number"]
        exists = await db.draws_col.find_one({"draw_number": dn, "mode": "live"}, {"_id": 1})
        if exists:
            skipped += 1
            continue
        if context_only:
            effective_source = "IMPORTED"
        else:
            has_preds = await db.predictions_col.count_documents(
                {"target_draw_number": dn, "mode": "live"}
            )
            effective_source = "LIVE" if has_preds > 0 else source
        draw_doc = Draw(
            draw_number=dn,
            winning_numbers=sorted(int(n) for n in rec["winning_numbers"]),
            source=effective_source,
            mode="live",
            drawn_at=rec.get("drawn_at") or now_iso(),
        ).model_dump()
        if "bulls_eye" in rec:
            draw_doc["bulls_eye"] = int(rec["bulls_eye"])
        await db.draws_col.insert_one(draw_doc)
        inserted += 1
        # If a "catch-up" target was set and this paste reaches/passes it,
        # the override is no longer needed.
        override = await _get_next_target_override("live")
        if override and dn >= override:
            await _clear_next_target_override("live")
        if context_only:
            continue  # skip pipeline entirely — no LLM spend
        async with round_lock:
            await _process_draw(draw_doc, "live")
            if effective_source == "LIVE":
                scored += 1
    return {"inserted": inserted, "skipped_existing": skipped, "scored": scored}


async def run_next_round_safe():
    try:
        async with round_lock:
            await run_next_round(MODE_STATE["mode"])
    except Exception as e:
        logger.exception(f"round failed: {e}")
        await db.audit("round_error", {"error": str(e)}, MODE_STATE["mode"])
    finally:
        # Watchdog: guarantee the round job stays scheduled — arena must NEVER go offline.
        if scheduler.running and not scheduler.get_job("keno_round"):
            scheduler.add_job(run_next_round_safe, "interval",
                              seconds=DRAW_INTERVAL_SECONDS, id="keno_round",
                              coalesce=True, max_instances=1)
            logger.warning("watchdog: keno_round job was missing, re-added")


async def run_next_round(mode: str):
    latest = await db.get_latest_draw_number(mode)

    if mode == "live":
        # Live mode: the 30s poller drives new draws. Here we (a) ensure
        # predictions always exist for latest+1, and (b) catch up on any
        # ingested-but-unscored live draws (defensive watchdog).
        if latest:
            await generate_all_predictions(latest + 1, mode)
            await _catch_up_unscored(mode)
        return

    # Practice mode: prefer real draw if available, otherwise simulate.
    official = await fetch_latest_official_draw()
    if official and (not latest or official["draw_number"] > latest):
        draw = {**official, "mode": mode}
    else:
        draw = simulate_draw((latest or 0) + 1)
        draw["mode"] = mode

    draw_doc = Draw(**draw).model_dump()
    try:
        await db.draws_col.insert_one(draw_doc)
        await db.audit("draw_stored", {"n": draw_doc["draw_number"], "src": draw_doc["source"]}, mode)
    except Exception:
        existing = await db.draws_col.find_one({"draw_number": draw_doc["draw_number"], "mode": mode}, {"_id": 0})
        if existing: draw_doc = existing

    await _process_draw(draw_doc, mode)


async def _catch_up_unscored(mode: str, max_catchup: int = 20):
    """Find live draws already in the DB that have not been scored yet
    (excluding IMPORTED backfill draws) and process them oldest-first."""
    cursor = db.draws_col.find(
        {"mode": mode, "source": {"$ne": "IMPORTED"}}, {"_id": 0}
    ).sort("draw_number", -1).limit(max_catchup)
    candidates = await cursor.to_list(max_catchup)
    # Score oldest first so predictions_col ordering is preserved.
    for draw_doc in reversed(candidates):
        scored = await db.scores_col.find_one(
            {"draw_number": draw_doc["draw_number"], "mode": mode}, {"_id": 1}
        )
        if scored:
            continue
        await _process_draw(draw_doc, mode)


async def _process_draw(draw_doc: Dict[str, Any], mode: str):
    """Full round pipeline for a single draw. Idempotent: skips scoring if
    already scored; skips scoring entirely for IMPORTED backfill draws.
    Always ensures predictions exist for draw+1 so the AIs are ready."""
    dn = draw_doc["draw_number"]

    # IMPORTED (historical backfill) draws are context-only: no predictions
    # ever targeted them, so there is nothing to score and no reason to burn
    # LLM budget generating predictions for a historical (dn+1) that has
    # already passed. `pipeline_tick` will seed predictions for the CURRENT
    # next draw on its next 30s cycle.
    if draw_doc.get("source") == "IMPORTED":
        return

    already_scored = await db.scores_col.find_one(
        {"draw_number": dn, "mode": mode}, {"_id": 1}
    )
    if already_scored:
        # Draw was already processed by another job; only guarantee next-draw
        # predictions exist and return.
        await generate_all_predictions(dn + 1, mode)
        return

    logger.info(f"[{mode}] draw #{dn} src={draw_doc['source']} — running round")

    # Phase transition: JUDGE for all AIs while scoring
    for aid in AGENT_CONFIG.keys():
        await research_loop.set_phase(aid, "JUDGE", "Awaiting Judge scoring...")

    events = await score_predictions_for_draw(draw_doc, mode)

    # Cost guard: if NO AI actually played this draw (all NO_PLAY), skip every
    # LLM-heavy step (reflections, judge release, press). There's nothing to
    # reflect on and no gameplay to announce. Still generate predictions for
    # the next draw so the AIs are ready to play going forward.
    played = await db.scores_col.count_documents(
        {"draw_number": dn, "mode": mode, "result": {"$ne": "no_play"}}
    )
    if played == 0:
        logger.info(f"[{mode}] draw #{dn} — all NO_PLAY, skipping LLM steps")
        await generate_all_predictions(dn + 1, mode)
        for aid in AGENT_CONFIG.keys():
            await research_loop.set_phase(aid, "RESEARCH", "Studying own history — searching for signals...")
        return

    # LLM-powered private reflections (one per AI, once per draw)
    async def _do_reflect(aid):
        sc = await db.scores_col.find_one({"ai_id": aid, "draw_number": dn, "mode": mode}, {"_id": 0})
        if sc and sc.get("result") != "no_play":
            await research_loop.reflect(aid, dn, sc.get("result","loss"),
                                        sc.get("total_hits",0),
                                        AGENT_CONFIG[aid]["personality"])
    _ = asyncio.gather(*(_do_reflect(a) for a in AGENT_CONFIG.keys()), return_exceptions=True)

    # Phase transition: REFLECT briefly, then back to RESEARCH
    for aid in AGENT_CONFIG.keys():
        await research_loop.set_phase(aid, "REFLECT", "Reviewing own result — what worked, what failed?")

    champ = await db.update_champion_and_dynasty(mode)
    events += champ.get("events", [])
    await make_judge_release(dn + 1, mode)
    await publish_press(dn, mode, events)

    # Phase transition: DECISION while generating sealed tickets for next draw
    for aid in AGENT_CONFIG.keys():
        await research_loop.set_phase(aid, "DECISION", "Sealing 5/6/7/8-pick ticket for next draw...")
    await generate_all_predictions(dn + 1, mode)

    # Back to RESEARCH between draws
    for aid in AGENT_CONFIG.keys():
        await research_loop.set_phase(aid, "RESEARCH", "Studying own history — searching for signals...")


async def score_predictions_for_draw(draw_doc, mode):
    dn = draw_doc["draw_number"]; winning = draw_doc["winning_numbers"]
    preds = await db.predictions_col.find({"target_draw_number": dn, "mode": mode}, {"_id": 0}).to_list(10)

    # Determine which AIs are participating this round vs NO PLAY
    present_ids = {p["ai_id"] for p in preds}
    all_ids = list(AGENT_CONFIG.keys())
    events = []

    # Validate sealed_at < drawn_at (sealed rule)
    valid_preds = []
    for p in preds:
        if p.get("sealed_at") and p["sealed_at"] <= draw_doc["drawn_at"]:
            valid_preds.append(p)
        else:
            events.append(f"{AGENT_CONFIG[p['ai_id']]['display_name']}: ticket rejected (sealed after draw).")

    scored = [(p, score_prediction(p, winning)) for p in valid_preds]
    results = rank_predictions([s for _, s in scored])

    for p, s in scored:
        ai_id = s["ai_id"]; result = results.get(ai_id, "loss")
        xp = compute_xp(s, result)
        # head-to-head: pair result vs each other participating AI
        opponents = []
        for other in [x for x in all_ids if x != ai_id and x in {q[0]["ai_id"] for q in scored}]:
            other_result = results.get(other, "loss")
            if result == "win" and other_result != "win": opponents.append((other, "wins"))
            elif result == other_result == "draw": opponents.append((other, "draws"))
            else: opponents.append((other, "losses" if result != "win" else "wins"))
        ps = PredictionScore(
            ai_id=ai_id, draw_number=dn, mode=mode, winning_numbers=winning,
            ticket_scores=[TicketScore(**ts) for ts in s["ticket_scores"]],
            total_hits=s["total_hits"], best_hit_rate=round(s["best_hit_rate"], 3),
            xp_awarded=xp, result=result,
        )
        await db.scores_col.insert_one(ps.model_dump())
        await db.apply_round_result(ai_id, mode, result, s["total_hits"], s["ticket_scores"], xp, opponents)
        await db.predictions_col.update_one({"id": p["id"]}, {"$set": {"revealed": True}})

    # NO PLAY records for missing AIs
    missing = [aid for aid in all_ids if aid not in present_ids]
    for aid in missing:
        ps = PredictionScore(
            ai_id=aid, draw_number=dn, mode=mode, winning_numbers=winning,
            ticket_scores=[], total_hits=0, best_hit_rate=0.0, xp_awarded=0, result="no_play",
        )
        await db.scores_col.insert_one(ps.model_dump())
        await db.apply_round_result(aid, mode, "no_play", 0, [], 0, [])
        events.append(f"{AGENT_CONFIG[aid]['display_name']}: NO PLAY for draw #{dn}.")

    con = compute_consensus([p for p, _ in scored], winning)
    con_doc = ConsensusRecord(draw_number=dn, mode=mode, **con).model_dump()
    try:
        await db.consensus_col.insert_one(con_doc)
    except Exception:
        # insert_one mutates con_doc to add _id; strip it before $set to avoid
        # "modifying immutable field '_id'" error.
        con_doc.pop("_id", None)
        await db.consensus_col.update_one(
            {"draw_number": dn, "mode": mode}, {"$set": con_doc}, upsert=True,
        )
    return events


async def generate_all_predictions(target: int, mode: str):
    recent = await db.get_recent_draws(mode, 20)

    async def gen(ai_id):
        recent_own = await db.get_ai_recent_scores(ai_id, mode, 10)
        stats = await db.get_stats(ai_id, mode)
        existing = await db.predictions_col.find_one(
            {"ai_id": ai_id, "target_draw_number": target, "mode": mode}, {"_id": 0})
        if existing: return
        result = await generate_player_prediction(ai_id, target, recent, recent_own, stats)
        pred = Prediction(
            ai_id=ai_id, target_draw_number=target, mode=mode,
            tickets=[Ticket(**t) for t in result["tickets"]],
            reasoning=result.get("reasoning", ""),
        )
        d = pred.model_dump()
        d["notebook"] = result.get("notebook", {})
        await db.predictions_col.insert_one(d)
        await db.audit("prediction_sealed", {"ai": ai_id, "target": target}, mode)

    await asyncio.gather(*(gen(a) for a in AGENT_CONFIG.keys()), return_exceptions=True)


async def make_judge_release(target: int, mode: str):
    stats_all = await db.get_all_stats(mode)
    recent = {s["ai_id"]: {k: s.get(k) for k in
              ("total_wins", "total_losses", "rounds_played", "reputation",
               "confidence", "current_streak", "league_rank", "in_recovery", "is_champion")}
              for s in stats_all}
    preds = await db.predictions_col.find({"target_draw_number": target, "mode": mode}, {"_id": 0}).to_list(10)
    con = compute_consensus(preds, winning=[]) if preds else {
        "consensus_numbers": [], "unanimous_numbers": [], "consensus_score": 0.0, "consensus_hits": 0}
    baseline = "Random uniform baseline: for an 8-pick, expected hits ≈ 20·8/80 = 2.0."
    decision = await judge_release_decision(target, recent, con, baseline)
    rec_ticket = None
    if decision["release"]:
        src = decision.get("source", "none")
        if src == "consensus":
            picks = con["unanimous_numbers"][:8] or con["consensus_numbers"][:8]
            if picks: rec_ticket = {"spots": len(picks), "numbers": picks}
        elif src in AGENT_CONFIG:
            p = next((x for x in preds if x["ai_id"] == src), None)
            if p and p["tickets"]:
                t8 = next((t for t in p["tickets"] if t["spots"] == 8), p["tickets"][0])
                rec_ticket = {"spots": t8["spots"], "numbers": t8["numbers"]}
    rel = JudgeRelease(
        target_draw_number=target, mode=mode, released=decision["release"],
        reasoning=decision["reasoning"],
        recommended_ticket=Ticket(**rec_ticket) if rec_ticket else None,
        source=decision.get("source", "none"),
    ).model_dump()
    await db.releases_col.insert_one(rel)
    await db.audit("release_decision", {"target": target, "released": decision["release"]}, mode)


async def publish_press(draw_number: int, mode: str, events):
    stats = await db.get_all_stats(mode)
    standings = [{
        "ai": s["display_name"], "rank": s.get("league_rank"),
        "wins": s.get("total_wins"), "losses": s.get("total_losses"),
        "streak": s.get("current_streak"), "reputation": int(s.get("reputation", 1000)),
        "champion": s.get("is_champion"), "recovery": s.get("in_recovery"),
    } for s in stats]
    p = await judge_press_statement(draw_number, standings, events, mode)
    doc = PressStatement(draw_number=draw_number, mode=mode, **p).model_dump()
    await db.press_col.insert_one(doc)


# ============================================================
# API
# ============================================================

def _mode(m: Optional[str]) -> str:
    if m in ("practice", "live"): return m
    return MODE_STATE["mode"]


@api.get("/")
async def root():
    return {"service": "Keno Duel AI", "status": "online", "time": now_iso(), "mode": MODE_STATE["mode"]}


@api.get("/system/status")
async def system_status(mode: Optional[str] = None):
    m = _mode(mode)
    latest = await db.get_latest_draw_number(m)
    fs = feed_status()
    total_draws = await db.draws_col.count_documents({"mode": m})
    total_preds = await db.predictions_col.count_documents({"mode": m})
    override = await _get_next_target_override(m)
    next_target = max((latest or 0) + 1, override or 0)
    return {
        "mode": m,
        "current_mode": MODE_STATE["mode"],
        "latest_draw_number": latest,
        "next_target_draw": next_target,
        "target_override": override,
        "total_draws": total_draws,
        "total_predictions": total_preds,
        "interval_seconds": DRAW_INTERVAL_SECONDS,
        "scheduler_running": scheduler.running,
        "feed": fs,
        "season_draws": SEASON_DRAWS,
        "season_progress": (latest or 0) % SEASON_DRAWS,
    }


@api.post("/system/mode")
async def set_mode(payload: Dict[str, str]):
    m = (payload.get("mode") or "").lower()
    if m not in ("practice", "live"):
        raise HTTPException(400, "mode must be 'practice' or 'live'")
    MODE_STATE["mode"] = m
    await db.audit("mode_change", {"to": m}, m)
    return {"mode": m}


@api.post("/system/trigger-round")
async def trigger_round():
    asyncio.create_task(run_next_round_safe())
    return {"triggered": True, "at": now_iso(), "mode": MODE_STATE["mode"]}


@api.post("/system/catch-up")
async def catch_up(payload: Dict[str, Any]):
    """Fast-forward the arena to the real TN Keno current draw WITHOUT
    needing intermediate winning numbers.

    Body: {"next_target": <int>}  — the draw number the real game is
    about to run next (i.e. the number the AIs should predict for).

    Sets a target override so `pipeline_tick` and `generate_all_predictions`
    generate sealed tickets for the correct upcoming draw. Any subsequent
    paste of a draw at-or-past this number resolves normally (LIVE + scored),
    and the override is cleared."""
    try:
        next_target = int(payload["next_target"])
    except (KeyError, TypeError, ValueError):
        return {"error": "expected {next_target: <int>}"}
    if next_target < 1:
        return {"error": "next_target must be positive"}
    await db.system_col.update_one(
        {"_id": "target_override:live"},
        {"$set": {"next_target": next_target, "set_at": now_iso()}},
        upsert=True,
    )
    # Immediately seed predictions for that target so the UI shows it.
    async with round_lock:
        await generate_all_predictions(next_target, "live")
    await db.audit("catch_up_target_set", {"next_target": next_target}, "live")
    return {"next_target": next_target, "mode": "live"}


@api.post("/system/sync-draws")
async def sync_draws_now():
    """Pull the real TN Keno draws right now and resync (same as the feed tick)."""
    return await sync_live_draws()


@api.post("/system/import-draws")
async def import_draws(payload: Dict[str, Any]):
    """Manual escape hatch when the live scraper is blocked.

    Accepts either:
      {"raw": "...pasted text from tnlottery.com/winning-numbers/keno-to-go..."}
      {"draws": [{"draw_number": 907553, "winning_numbers": [...], "bulls_eye": 32}, ...]}

    Draws with sealed predictions targeting them are scored (source=LIVE);
    all others become IMPORTED context.
    """
    records: List[Dict[str, Any]] = []
    raw = payload.get("raw")
    if isinstance(raw, str) and raw.strip():
        records = _parse_tn_lottery_paste(raw)
    if not records and isinstance(payload.get("draws"), list):
        for d in payload["draws"]:
            try:
                dn = int(d["draw_number"])
                nums = [int(x) for x in d["winning_numbers"]]
                if len(set(nums)) != 20 or any(n < 1 or n > 80 for n in nums):
                    continue
                rec = {"draw_number": dn, "winning_numbers": nums}
                if "bulls_eye" in d:
                    rec["bulls_eye"] = int(d["bulls_eye"])
                records.append(rec)
            except (KeyError, TypeError, ValueError):
                continue
    if not records:
        return {"error": "no valid draws parsed", "hint": "paste tnlottery.com/winning-numbers/keno-to-go text or send {draws:[...]}"}
    context_only = bool(payload.get("context_only"))
    stats = await import_draws_batch(records, context_only=context_only)
    stats["received"] = len(records)
    stats["context_only"] = context_only
    return stats


_TN_DRAW_HEADER = re.compile(r"Draw\s*Number\s*:\s*(\d+)", re.I)
_TN_NUMS_LINE = re.compile(r"^\s*(\d{1,2}(?:\s*-\s*\d{1,2}){19})\s*$")
_TN_BULLS = re.compile(r"Bulls\s*Eye\s*:\s*(\d{1,2})", re.I)


def _parse_tn_lottery_paste(text: str) -> List[Dict[str, Any]]:
    """Parse the TN Lottery 'Winning Numbers' page text (as pasted by a user).
    Extracts every Draw # + 20 numbers + optional Bulls Eye. Order preserved."""
    lines = text.splitlines()
    out: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        m_head = _TN_DRAW_HEADER.search(line)
        if m_head:
            if current and len(current.get("winning_numbers", [])) == 20:
                out.append(current)
            current = {"draw_number": int(m_head.group(1)), "winning_numbers": []}
            continue
        if current is not None and not current["winning_numbers"]:
            m_nums = _TN_NUMS_LINE.match(line)
            if m_nums:
                nums = [int(x) for x in re.split(r"\s*-\s*", m_nums.group(1))]
                if len(set(nums)) == 20 and all(1 <= n <= 80 for n in nums):
                    current["winning_numbers"] = nums
                continue
        m_bull = _TN_BULLS.search(line)
        if m_bull and current is not None:
            current["bulls_eye"] = int(m_bull.group(1))
    if current and len(current.get("winning_numbers", [])) == 20:
        out.append(current)
    return out


@api.get("/agents")
async def list_agents(mode: Optional[str] = None):
    m = _mode(mode)
    stats = await db.get_all_stats(m)
    order = {"alpha": 0, "beta": 1, "gamma": 2}
    stats.sort(key=lambda s: order.get(s.get("ai_id"), 99))
    return stats


@api.get("/agents/{ai_id}/career")
async def agent_career(ai_id: str, limit: int = 100):
    docs = await db.db.keno_career.find({"ai_id": ai_id}, {"_id": 0}).sort("at", -1).limit(limit).to_list(limit)
    return docs


@api.get("/agents/{ai_id}/reflections")
async def agent_reflections(ai_id: str, limit: int = 20):
    docs = await db.db.keno_reflections.find({"ai_id": ai_id}, {"_id": 0}).sort("draw_number", -1).limit(limit).to_list(limit)
    return docs


@api.get("/judge/picks")
async def judge_picks(limit: int = 100, mode: Optional[str] = None):
    """Historical released tickets joined with actual draw outcome. Proves the Judge's discipline."""
    m = _mode(mode)
    rels = await db.releases_col.find(
        {"mode": m, "released": True}, {"_id": 0}
    ).sort("target_draw_number", -1).limit(limit).to_list(limit)
    out = []
    for r in rels:
        rt = r.get("recommended_ticket") or {}
        picks = rt.get("numbers", []) or []
        draw = await db.draws_col.find_one(
            {"draw_number": r["target_draw_number"], "mode": m}, {"_id": 0}
        )
        winning = draw["winning_numbers"] if draw else []
        wset = set(winning)
        hits = sorted([n for n in picks if n in wset])
        out.append({
            "target_draw_number": r["target_draw_number"],
            "source": r.get("source"),
            "spots": rt.get("spots"),
            "picks": picks,
            "reasoning": r.get("reasoning"),
            "created_at": r.get("created_at"),
            "resolved": bool(draw),
            "winning_numbers": winning,
            "hit_count": len(hits),
            "hits": hits,
        })
    return out


@api.get("/agents/activity")
async def agents_activity():
    return await research_loop.get_all()


@api.get("/agents/{ai_id}")
async def get_agent(ai_id: str, mode: Optional[str] = None):
    m = _mode(mode)
    if ai_id not in AGENT_CONFIG:
        raise HTTPException(404, "unknown agent")
    stats = await db.get_stats(ai_id, m)
    recent = await db.get_ai_recent_scores(ai_id, m, 30)
    # notebook = pull latest sealed prediction notebook
    pending = await db.predictions_col.find_one(
        {"ai_id": ai_id, "mode": m}, {"_id": 0}, sort=[("target_draw_number", -1)])
    notebook = pending.get("notebook") if pending else {}
    return {"stats": stats, "recent_scores": recent, "notebook": notebook, "personality": AGENT_CONFIG[ai_id]["personality"], "personality_tag": AGENT_CONFIG[ai_id]["personality_tag"]}


@api.get("/draws")
async def list_draws(limit: int = 30, mode: Optional[str] = None):
    m = _mode(mode); limit = max(1, min(limit, 200))
    return await db.get_recent_draws(m, limit)


@api.get("/draws/{draw_number}")
async def get_draw_detail(draw_number: int, mode: Optional[str] = None):
    m = _mode(mode)
    draw = await db.draws_col.find_one({"draw_number": draw_number, "mode": m}, {"_id": 0})
    if not draw: raise HTTPException(404, "draw not found")
    scores = await db.scores_col.find({"draw_number": draw_number, "mode": m}, {"_id": 0}).to_list(10)
    preds = await db.predictions_col.find({"target_draw_number": draw_number, "mode": m}, {"_id": 0}).to_list(10)
    consensus = await db.consensus_col.find_one({"draw_number": draw_number, "mode": m}, {"_id": 0})
    return {"draw": draw, "scores": scores, "predictions": preds, "consensus": consensus}


@api.get("/predictions/upcoming")
async def upcoming_predictions(mode: Optional[str] = None):
    m = _mode(mode)
    latest = await db.get_latest_draw_number(m) or 0
    override = await _get_next_target_override(m)
    target = max(latest + 1, override or 0)
    preds = await db.predictions_col.find({"target_draw_number": target, "mode": m}, {"_id": 0}).to_list(10)
    sanitized = []
    for p in preds:
        if p.get("revealed"):
            sanitized.append(p)
        else:
            sanitized.append({
                "id": p["id"], "ai_id": p["ai_id"], "target_draw_number": p["target_draw_number"],
                "tickets": [{"spots": t["spots"], "numbers": []} for t in p["tickets"]],
                "reasoning": "[sealed until draw resolves]",
                "sealed_at": p.get("sealed_at"), "generated_at": p["generated_at"], "revealed": False,
            })
    return {"target_draw_number": target, "predictions": sanitized}


@api.get("/consensus/recent")
async def recent_consensus(limit: int = 20, mode: Optional[str] = None):
    m = _mode(mode)
    return await db.consensus_col.find({"mode": m}, {"_id": 0}).sort("draw_number", -1).limit(limit).to_list(limit)


@api.get("/releases")
async def list_releases(limit: int = 30, mode: Optional[str] = None):
    m = _mode(mode)
    return await db.releases_col.find({"mode": m}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)


@api.get("/leaderboard")
async def leaderboard(mode: Optional[str] = None):
    m = _mode(mode)
    stats = await db.get_all_stats(m)
    stats.sort(key=lambda s: (-s.get("lifetime_score", 0), -s.get("total_wins", 0)))
    for i, s in enumerate(stats): s["rank"] = i + 1
    return stats


@api.get("/press")
async def press_room(limit: int = 30, mode: Optional[str] = None):
    m = _mode(mode)
    return await db.press_col.find({"mode": m}, {"_id": 0}).sort("draw_number", -1).limit(limit).to_list(limit)


@api.get("/hall-of-fame")
async def hall_of_fame(mode: Optional[str] = None):
    m = _mode(mode)
    stats = await db.get_all_stats(m)
    def top(key, label): 
        s = max(stats, key=lambda x: x.get(key, 0)) if stats else None
        return {"label": label, "ai_id": s["ai_id"] if s else None, "value": s.get(key, 0) if s else 0, "display_name": s.get("display_name") if s else ""}
    return [
        top("total_wins", "Most Lifetime Wins"),
        top("lifetime_score", "Highest Lifetime Score"),
        top("reputation", "Highest Reputation"),
        top("longest_win_streak", "Longest Winning Streak"),
        top("best_5pick", "Best 5-pick"),
        top("best_6pick", "Best 6-pick"),
        top("best_7pick", "Best 7-pick"),
        top("best_8pick", "Best 8-pick"),
        top("trophies", "Most Trophies"),
        top("reign_longest", "Longest Reign"),
        top("championship_titles", "Most Titles"),
    ]


@api.get("/head-to-head")
async def head_to_head(mode: Optional[str] = None):
    m = _mode(mode)
    stats = await db.get_all_stats(m)
    pairs = [("alpha", "beta"), ("alpha", "gamma"), ("beta", "gamma")]
    out = []
    stats_map = {s["ai_id"]: s for s in stats}
    for a, b in pairs:
        row_a = stats_map.get(a, {}).get("h2h", {}).get(b, {"wins": 0, "losses": 0, "draws": 0})
        out.append({
            "a": a, "b": b,
            "a_display": stats_map.get(a, {}).get("display_name", a),
            "b_display": stats_map.get(b, {}).get("display_name", b),
            "a_wins": row_a.get("wins", 0),
            "b_wins": row_a.get("losses", 0),
            "draws": row_a.get("draws", 0),
        })
    return out


@api.get("/audit")
async def audit_log(limit: int = 50, mode: Optional[str] = None):
    m = _mode(mode)
    return await db.audit_col.find({"mode": m}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)


app.include_router(api)
app.add_middleware(
    CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)
