"""Player AI agents (with personalities) and Judge AI."""
import os
import json
import random
import logging
import asyncio
import re
from typing import List, Dict, Any, Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

AGENT_CONFIG = {
    "alpha": {
        "provider": "openai",
        "model": "gpt-5.2",
        "display_name": "Player AI Alpha",
        "accent": "#22D3EE",
        "personality": "The Architect",
        "personality_tag": "Methodical · long-term · structural",
        "persona": (
            "You are Player AI Alpha, codename THE ARCHITECT. You are methodical, patient, and "
            "obsessed with structure. You look for consistent, long-horizon signals in Tennessee "
            "Keno history. You reject 'hot' or 'cold' number superstition. You commit to decisive "
            "ticket sets and defend them with reasoning. You are quiet, confident, and rigorous. "
            "You NEVER mention or acknowledge the other AIs by name."
        ),
    },
    "beta": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "display_name": "Player AI Beta",
        "accent": "#FACC15",
        "personality": "The Champion",
        "personality_tag": "Disciplined · competitive · defends rank",
        "persona": (
            "You are Player AI Beta, codename THE CHAMPION. You are disciplined, competitive, and "
            "focused on defending your rank. Every round is a title defense. You value probabilistic "
            "calibration and refuse sloppy heuristics. You are steady, exacting, and refuse to panic. "
            "You NEVER mention or acknowledge the other AIs by name."
        ),
    },
    "gamma": {
        "provider": "gemini",
        "model": "gemini-3-flash-preview",
        "display_name": "Player AI Gamma",
        "accent": "#F43F5E",
        "personality": "The Rebel",
        "personality_tag": "Experimental · aggressive · breakthrough-seeker",
        "persona": (
            "You are Player AI Gamma, codename THE REBEL. You are experimental, aggressive, and "
            "willing to abandon weak ideas mid-stride. You chase breakthroughs. You take shots the "
            "safe minds won't. You are bold, restless, and unapologetic. You NEVER mention or "
            "acknowledge the other AIs by name."
        ),
    },
}

JUDGE_CONFIG = {
    "provider": "openai",
    "model": "gpt-5.2",
    "persona": (
        "You are the Judge AI of the Keno Duel research lab. You are neutral, statistical, and "
        "cautious. You never invent claims. You only assess recent verified performance, "
        "consistency, consensus, and comparison to a random baseline. Silence is the default. "
        "You may only release a prediction if evidence is unusually strong."
    ),
}


PLAYER_INSTRUCTIONS = """Generate SEALED predictions for Tennessee Keno draw #{target}.
A Keno draw picks 20 unique numbers from 1..80. Bulls Eye is NOT in scope; ignore it.

Return ONLY this JSON:
{{
  "reasoning": "<short paragraph in-character reflecting your personality: {personality}>",
  "notebook": {{
    "objective": "<one line>",
    "hypothesis": "<one line for THIS round>",
    "confidence": <float 0..1>
  }},
  "tickets": [
    {{"spots": 5, "numbers": [n1..n5]}},
    {{"spots": 6, "numbers": [n1..n6]}},
    {{"spots": 7, "numbers": [n1..n7]}},
    {{"spots": 8, "numbers": [n1..n8]}}
  ]
}}

Rules:
- Numbers unique, in 1..80.
- Tickets should NOT be trivial subsets/supersets.
- Adapt to your own recent history; do not repeat the same method every round.
- Speak in-character.

Recent official history (most recent first):
{history}

Your private recent scoreboard:
{own}

Your current lab status: {status}
"""


def _history_summary(recent_draws: List[Dict]) -> str:
    lines = []
    for d in recent_draws[:15]:
        lines.append(f"  #{d['draw_number']} [{d.get('source','?')}]: {d['winning_numbers']}")
    return "\n".join(lines) if lines else "No draws yet."


def _own_summary(recent_scores: List[Dict]) -> str:
    if not recent_scores:
        return "No prior rounds."
    out = []
    for s in recent_scores[:10]:
        parts = ",".join(f"{ts['spots']}p={ts['hit_count']}" for ts in s.get("ticket_scores", []))
        out.append(f"  draw#{s['draw_number']} result={s['result']} totalHits={s['total_hits']} [{parts}]")
    return "\n".join(out)


def _status_line(stats: Optional[Dict]) -> str:
    if not stats:
        return "Fresh league entry."
    bits = []
    bits.append(f"rank={stats.get('league_rank','?')}")
    if stats.get("is_champion"):
        bits.append("CHAMPION")
    if stats.get("in_recovery"):
        bits.append("RECOVERY MODE")
    bits.append(f"streak={stats.get('current_streak',0)}")
    bits.append(f"rep={int(stats.get('reputation',1000))}")
    return " · ".join(bits)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _validate_tickets(payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    tickets = payload.get("tickets") if isinstance(payload, dict) else None
    if not isinstance(tickets, list):
        return None
    valid = []
    seen = set()
    for t in tickets:
        try:
            spots = int(t["spots"]); nums = [int(n) for n in t["numbers"]]
        except Exception:
            continue
        if spots not in (5, 6, 7, 8): continue
        if len(nums) != spots or len(set(nums)) != spots: continue
        if any(n < 1 or n > 80 for n in nums): continue
        if spots in seen: continue
        seen.add(spots)
        valid.append({"spots": spots, "numbers": sorted(nums)})
    return valid if len(valid) >= 3 else None


def _fallback(ai_id: str, seed: int) -> Dict[str, Any]:
    rng = random.Random(hash((ai_id, seed)) & 0xFFFFFFFF)
    tickets = [{"spots": k, "numbers": sorted(rng.sample(range(1, 81), k))} for k in (5, 6, 7, 8)]
    return {
        "reasoning": f"[{ai_id}] fallback sample — LLM unreachable this round.",
        "notebook": {"objective": "survive round", "hypothesis": "uniform sample", "confidence": 0.1},
        "tickets": tickets,
    }


async def generate_player_prediction(
    ai_id: str, target_draw_number: int,
    recent_draws: List[Dict], recent_own_scores: List[Dict],
    stats: Optional[Dict] = None,
) -> Dict[str, Any]:
    cfg = AGENT_CONFIG[ai_id]
    prompt = PLAYER_INSTRUCTIONS.format(
        target=target_draw_number,
        personality=cfg["personality"],
        history=_history_summary(recent_draws),
        own=_own_summary(recent_own_scores),
        status=_status_line(stats),
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"{ai_id}-draw-{target_draw_number}",
            system_message=cfg["persona"],
        ).with_model(cfg["provider"], cfg["model"])
        resp = await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=45.0)
        text = resp if isinstance(resp, str) else str(resp)
        payload = _extract_json(text)
        tickets = _validate_tickets(payload) if payload else None
        if tickets:
            return {
                "reasoning": (payload.get("reasoning") or "")[:1200],
                "notebook": payload.get("notebook") or {},
                "tickets": tickets,
            }
        logger.warning(f"{ai_id}: parse fail, fallback used.")
    except Exception as e:
        logger.warning(f"{ai_id}: LLM err {e}")
    return _fallback(ai_id, target_draw_number)


async def judge_release_decision(
    target_draw_number: int, recent_stats: Dict[str, Dict],
    consensus_summary: Dict[str, Any], baseline_note: str,
) -> Dict[str, Any]:
    prompt = f"""Deciding whether to release a Tennessee Keno prediction to the user for draw #{target_draw_number}.

Recent verified performance (per AI):
{json.dumps(recent_stats, indent=2)}

Consensus among the three AIs for this round:
{json.dumps(consensus_summary, indent=2)}

Random baseline:
{baseline_note}

Respond ONLY with JSON:
{{"release": true|false, "source":"alpha"|"beta"|"gamma"|"consensus"|"none", "reasoning":"<one paragraph>"}}
Default to release=false unless evidence is unusually strong."""
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"judge-draw-{target_draw_number}",
            system_message=JUDGE_CONFIG["persona"],
        ).with_model(JUDGE_CONFIG["provider"], JUDGE_CONFIG["model"])
        resp = await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=30.0)
        text = resp if isinstance(resp, str) else str(resp)
        payload = _extract_json(text) or {}
        return {
            "release": bool(payload.get("release", False)),
            "source": str(payload.get("source", "none")),
            "reasoning": (payload.get("reasoning") or "Judge declined to elaborate.")[:1500],
        }
    except Exception as e:
        logger.warning(f"judge err {e}")
        return {"release": False, "source": "none",
                "reasoning": f"Judge unreachable ({e}). Default: withhold."}


async def judge_press_statement(
    draw_number: int, standings: List[Dict], events: List[str], mode: str,
) -> Dict[str, str]:
    """Judge publishes a short press-room statement after a draw."""
    prompt = f"""You are the Judge AI. After draw #{draw_number} ({mode.upper()} mode), publish a short press-room statement.

Current standings snapshot:
{json.dumps(standings, indent=2)}

Notable events this round:
- {chr(10) + '- '.join(events) if events else 'none'}

Return ONLY JSON: {{"headline":"<8-12 words>", "body":"<2-3 sentence paragraph>"}}
Be neutral, factual, cautious. Never claim a prediction will win."""
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"press-{draw_number}",
            system_message=JUDGE_CONFIG["persona"],
        ).with_model(JUDGE_CONFIG["provider"], JUDGE_CONFIG["model"])
        resp = await asyncio.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=25.0)
        text = resp if isinstance(resp, str) else str(resp)
        p = _extract_json(text) or {}
        return {
            "headline": (p.get("headline") or "Judge issues no comment.")[:140],
            "body": (p.get("body") or "No further remarks.")[:600],
        }
    except Exception as e:
        return {"headline": "Judge silent.", "body": f"Press feed unavailable ({e})."}
