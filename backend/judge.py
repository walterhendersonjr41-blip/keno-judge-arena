"""Judge scoring logic — deterministic, verifiable, independent of any LLM."""
from typing import List, Dict, Any
from collections import Counter


def score_ticket(ticket: Dict[str, Any], winning: List[int]) -> Dict[str, Any]:
    wset = set(winning)
    nums = ticket["numbers"]
    hits = sorted([n for n in nums if n in wset])
    return {
        "spots": int(ticket["spots"]),
        "numbers": nums,
        "hits": hits,
        "hit_count": len(hits),
        "label": ticket.get("label"),
    }


def score_prediction(prediction: Dict[str, Any], winning: List[int]) -> Dict[str, Any]:
    ticket_scores = [score_ticket(t, winning) for t in prediction["tickets"]]
    total_hits = sum(ts["hit_count"] for ts in ticket_scores)
    # best_hit_rate over the tickets
    best = 0.0
    for ts in ticket_scores:
        rate = ts["hit_count"] / ts["spots"] if ts["spots"] else 0.0
        if rate > best:
            best = rate
    return {
        "ai_id": prediction["ai_id"],
        "ticket_scores": ticket_scores,
        "total_hits": total_hits,
        "best_hit_rate": best,
    }


def rank_predictions(scored: List[Dict[str, Any]]) -> Dict[str, str]:
    """Assign win/loss/draw. Winner = highest total_hits (ties = draw)."""
    if not scored:
        return {}
    max_hits = max(s["total_hits"] for s in scored)
    winners = [s["ai_id"] for s in scored if s["total_hits"] == max_hits]
    result = {}
    if len(winners) == 1:
        for s in scored:
            result[s["ai_id"]] = "win" if s["ai_id"] == winners[0] else "loss"
    else:
        for s in scored:
            result[s["ai_id"]] = "draw" if s["ai_id"] in winners else "loss"
    return result


def compute_xp(score: Dict[str, Any], result: str) -> int:
    """XP formula: hits * 10 + best-rate bonus + win bonus."""
    xp = score["total_hits"] * 10
    xp += int(score["best_hit_rate"] * 50)
    if result == "win":
        xp += 100
    elif result == "draw":
        xp += 40
    return xp


def compute_consensus(predictions: List[Dict[str, Any]], winning: List[int]) -> Dict[str, Any]:
    """Count how many AIs picked each number across ALL their tickets combined."""
    counts = Counter()
    for p in predictions:
        picked = set()
        for t in p["tickets"]:
            picked.update(t["numbers"])
        for n in picked:
            counts[n] += 1
    unanimous = sorted([n for n, c in counts.items() if c >= 3])
    consensus = sorted([n for n, c in counts.items() if c >= 2])
    total_picks = sum(1 for c in counts.values() if c >= 2)
    # score = fraction of unanimous vs consensus set
    denom = max(1, len(consensus))
    score = len(unanimous) / denom
    wset = set(winning)
    consensus_hits = len([n for n in consensus if n in wset])
    return {
        "consensus_numbers": consensus,
        "unanimous_numbers": unanimous,
        "consensus_score": round(score, 3),
        "consensus_hits": consensus_hits,
    }
