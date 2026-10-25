"""Mongo helpers and stats update logic. Practice and Live buckets stay separated by mode."""
import os
from typing import Dict, Any, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone

_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = _client[os.environ["DB_NAME"]]

draws_col = db.keno_draws
predictions_col = db.keno_predictions
scores_col = db.keno_scores
stats_col = db.keno_ai_stats
consensus_col = db.keno_consensus
releases_col = db.keno_releases
press_col = db.keno_press
audit_col = db.keno_audit
system_col = db.keno_system

RANK_THRESHOLDS = [
    ("Legend", 1600), ("Grandmaster", 1400), ("Master", 1300),
    ("Diamond", 1200), ("Platinum", 1130), ("Gold", 1070),
    ("Silver", 1020), ("Bronze", 0),
]


def rank_for(reputation: float) -> str:
    for name, thr in RANK_THRESHOLDS:
        if reputation >= thr: return name
    return "Bronze"


async def ensure_indexes():
    await draws_col.create_index([("mode", 1), ("draw_number", 1)], unique=True)
    await predictions_col.create_index([("mode", 1), ("target_draw_number", 1), ("ai_id", 1)])
    await scores_col.create_index([("mode", 1), ("draw_number", 1), ("ai_id", 1)])
    await stats_col.create_index([("mode", 1), ("ai_id", 1)], unique=True)
    await consensus_col.create_index([("mode", 1), ("draw_number", 1)], unique=True)
    await releases_col.create_index([("mode", 1), ("target_draw_number", 1)])
    await press_col.create_index([("mode", 1), ("draw_number", 1)])
    await audit_col.create_index("created_at")


async def get_recent_draws(mode: str, limit: int = 20) -> List[Dict[str, Any]]:
    return await draws_col.find({"mode": mode}, {"_id": 0}).sort("draw_number", -1).limit(limit).to_list(limit)


async def get_latest_draw_number(mode: str) -> Optional[int]:
    doc = await draws_col.find_one({"mode": mode}, {"_id": 0, "draw_number": 1}, sort=[("draw_number", -1)])
    return doc["draw_number"] if doc else None


async def get_ai_recent_scores(ai_id: str, mode: str, limit: int = 10) -> List[Dict[str, Any]]:
    return await scores_col.find({"ai_id": ai_id, "mode": mode}, {"_id": 0}).sort("draw_number", -1).limit(limit).to_list(limit)


async def get_all_stats(mode: str) -> List[Dict[str, Any]]:
    return await stats_col.find({"mode": mode}, {"_id": 0}).to_list(100)


async def get_stats(ai_id: str, mode: str) -> Optional[Dict[str, Any]]:
    return await stats_col.find_one({"ai_id": ai_id, "mode": mode}, {"_id": 0})


async def init_default_stats(defaults: List[Dict[str, Any]], mode: str):
    for d in defaults:
        row = {**d, "mode": mode}
        existing = await stats_col.find_one({"ai_id": d["ai_id"], "mode": mode})
        if not existing:
            await stats_col.insert_one(row)


async def audit(event: str, payload: Dict[str, Any], mode: str):
    await audit_col.insert_one({
        "event": event, "payload": payload, "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


AWARD_RULES = [
    ("5_of_5_master", "best_5pick", 5),
    ("6_of_6_elite", "best_6pick", 6),
    ("7_of_7_legend", "best_7pick", 7),
    ("8_of_8_titan", "best_8pick", 8),
]


async def apply_round_result(
    ai_id: str, mode: str, result: str, total_hits: int,
    ticket_scores: List[Dict[str, Any]], xp_awarded: int,
    opponents: List[str],
):
    stats = await stats_col.find_one({"ai_id": ai_id, "mode": mode}, {"_id": 0})
    if not stats:
        return

    stats["rounds_played"] = stats.get("rounds_played", 0) + 1

    if result == "win":
        stats["total_wins"] = stats.get("total_wins", 0) + 1
        cs = stats.get("current_streak", 0)
        stats["current_streak"] = cs + 1 if cs >= 0 else 1
        stats["longest_win_streak"] = max(stats.get("longest_win_streak", 0), stats["current_streak"])
        stats["reputation"] = round(stats.get("reputation", 1000.0) + 12.0, 2)
        stats["trophies"] = stats.get("trophies", 0) + 1
    elif result == "loss":
        stats["total_losses"] = stats.get("total_losses", 0) + 1
        cs = stats.get("current_streak", 0)
        stats["current_streak"] = cs - 1 if cs <= 0 else -1
        stats["longest_loss_streak"] = max(stats.get("longest_loss_streak", 0), abs(stats["current_streak"]))
        stats["reputation"] = round(max(0.0, stats.get("reputation", 1000.0) - 8.0), 2)
    elif result == "draw":
        stats["total_draws"] = stats.get("total_draws", 0) + 1
        stats["current_streak"] = 0
        stats["reputation"] = round(stats.get("reputation", 1000.0) + 2.0, 2)
    elif result == "no_play":
        stats["total_no_play"] = stats.get("total_no_play", 0) + 1
        # no reputation change on missing data

    if result != "no_play":
        stats["total_hits"] = stats.get("total_hits", 0) + total_hits
        stats["total_ticket_spots"] = stats.get("total_ticket_spots", 0) + sum(ts["spots"] for ts in ticket_scores)
        for ts in ticket_scores:
            key = f"best_{ts['spots']}pick"
            if ts["hit_count"] > stats.get(key, 0):
                stats[key] = ts["hit_count"]

    stats["xp"] = stats.get("xp", 0) + xp_awarded
    stats["lifetime_score"] = stats.get("lifetime_score", 0) + total_hits * 10 + (100 if result == "win" else 0)
    rp = stats["rounds_played"]
    stats["confidence"] = round(stats.get("total_wins", 0) / rp if rp else 0.0, 3)
    stats["league_rank"] = rank_for(stats["reputation"])

    # Recovery mode heuristics
    cur_streak = stats.get("current_streak", 0)
    hit_rate = (stats.get("total_hits", 0) / stats.get("total_ticket_spots", 1)) if stats.get("total_ticket_spots") else 0
    stats["in_recovery"] = (
        cur_streak <= -4 or stats["reputation"] < 950 or (rp >= 10 and hit_rate < 0.20)
    )

    # Mood
    if result == "no_play":
        mood = "Held out — no sealed ticket for this draw."
    elif stats.get("is_champion"):
        mood = "Defending the crown."
    elif stats["in_recovery"]:
        mood = "Rebuilding after unstable run."
    elif cur_streak >= 3:
        mood = "Riding a hot streak."
    elif cur_streak <= -2:
        mood = "Searching for the next breakthrough."
    else:
        mood = "Analyzing evidence."
    stats["mood"] = mood

    # Head-to-head
    h2h = stats.get("h2h", {})
    for opp_id, opp_result in opponents:
        row = h2h.get(opp_id, {"wins": 0, "losses": 0, "draws": 0})
        row[opp_result] = row.get(opp_result, 0) + 1
        h2h[opp_id] = row
    stats["h2h"] = h2h

    # Badges + Awards
    badges = set(stats.get("badges", []))
    if stats["total_wins"] >= 1: badges.add("first_win")
    if stats["longest_win_streak"] >= 3: badges.add("triple_streak")
    if stats["longest_win_streak"] >= 5: badges.add("penta_streak")
    if stats["longest_win_streak"] >= 10: badges.add("longest_streak_award")
    for key, field, need in AWARD_RULES:
        if stats.get(field, 0) >= need:
            badges.add(key)
    stats["badges"] = sorted(badges)

    stats["updated_at"] = datetime.now(timezone.utc).isoformat()
    await stats_col.update_one({"ai_id": ai_id, "mode": mode}, {"$set": stats}, upsert=True)


async def update_champion_and_dynasty(mode: str) -> Dict[str, Any]:
    """Determine current leader (by lifetime_score) and update reign counters."""
    stats = await stats_col.find({"mode": mode}, {"_id": 0}).to_list(100)
    if not stats: return {}
    stats.sort(key=lambda s: (-s.get("lifetime_score", 0), -s.get("total_wins", 0)))
    leader_id = stats[0]["ai_id"]
    events = []
    for s in stats:
        was_champ = s.get("is_champion", False)
        is_champ = s["ai_id"] == leader_id
        if is_champ and not was_champ:
            s["times_became_leader"] = s.get("times_became_leader", 0) + 1
            s["reign_current"] = 1
            s["championship_titles"] = s.get("championship_titles", 0) + 1
            events.append(f"{s['display_name']} claimed the championship.")
        elif is_champ:
            s["reign_current"] = s.get("reign_current", 0) + 1
        else:
            if was_champ:
                events.append(f"{s['display_name']} lost the championship.")
            s["reign_current"] = 0
        s["reign_longest"] = max(s.get("reign_longest", 0), s.get("reign_current", 0))
        s["is_champion"] = is_champ
        await stats_col.update_one({"ai_id": s["ai_id"], "mode": mode}, {"$set": s})
    return {"leader": leader_id, "events": events}
