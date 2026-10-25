"""Between-draws life cycle: continuous research heartbeat for each Player AI.
No LLM cost — this is a lightweight ticker so the Arena never looks idle."""
import random
from datetime import datetime, timezone
import db

RESEARCH_ACTIVITIES = {
    "alpha": [  # The Architect
        "Studying structural patterns across last 500 draws...",
        "Testing hypothesis: parity distribution over odd/even splits...",
        "Rebuilding internal model v{v}...",
        "Comparing yesterday's Alpha vs today's Alpha...",
        "Retiring weak hypothesis, promoting stable one...",
        "Cross-referencing hit-rate curves...",
        "Measuring mistake #{n} against the record...",
        "Simplifying model until only evidence survives...",
    ],
    "beta": [  # The Champion
        "Defending rank — auditing last 20 rounds...",
        "Calibrating confidence bands...",
        "Stress-testing model against random baseline...",
        "Refining champion playbook v{v}...",
        "Isolating what worked in last 5 wins...",
        "Reviewing losses without excuses...",
        "Locking discipline: no sloppy heuristics allowed...",
        "Measuring drift against yesterday's Beta...",
    ],
    "gamma": [  # The Rebel
        "Reversing an assumption I never challenged...",
        "Trying wild hypothesis #{n}: what if?",
        "Burning down experiment #{n} for a fresh idea...",
        "Chasing an unexplained signal...",
        "Abandoning ideas that worked yesterday...",
        "Searching for what nobody else has considered...",
        "Running high-variance test on ticket structure...",
        "Beating yesterday's Gamma — accept nothing else...",
    ],
}

PHASE_ROTATION = ["RESEARCH", "RESEARCH", "RESEARCH", "DECISION"]  # 3/4 of ticks are research


async def heartbeat():
    """Advance activity for each AI. Cheap, no LLM."""
    now = datetime.now(timezone.utc).isoformat()
    for aid, msgs in RESEARCH_ACTIVITIES.items():
        # Fetch current tick
        cur = await db.system_col.find_one({"_id": f"activity:{aid}"}) or {"tick": 0}
        tick = int(cur.get("tick", 0)) + 1
        phase = PHASE_ROTATION[tick % len(PHASE_ROTATION)]
        template = random.choice(msgs)
        activity = template.format(v=1 + tick // 20, n=tick)
        await db.system_col.update_one(
            {"_id": f"activity:{aid}"},
            {"$set": {"phase": phase, "activity": activity, "tick": tick, "updated_at": now}},
            upsert=True,
        )


async def set_phase(ai_id: str, phase: str, activity: str):
    now = datetime.now(timezone.utc).isoformat()
    await db.system_col.update_one(
        {"_id": f"activity:{ai_id}"},
        {"$set": {"phase": phase, "activity": activity, "updated_at": now}},
        upsert=True,
    )
    # Career log: permanent diary of every phase transition
    await db.db.keno_career.insert_one({"ai_id": ai_id, "phase": phase, "activity": activity, "at": now})


async def reflect(ai_id: str, draw_number: int, result: str, total_hits: int, personality: str) -> str:
    """Private 2-line reflection stored in ai's own memory."""
    from agents import EMERGENT_LLM_KEY, AGENT_CONFIG
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    import asyncio as _a
    cfg = AGENT_CONFIG[ai_id]
    prompt = f"You just finished draw #{draw_number}. Result: {result}. Total hits: {total_hits}. Write 2 short sentences PRIVATELY answering: why did I {'win' if result=='win' else 'lose' if result=='loss' else 'draw'}? What will I try next? Stay in-character as {personality}. No JSON, plain text only."
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"reflect-{ai_id}-{draw_number}",
                       system_message=cfg["persona"]).with_model(cfg["provider"], cfg["model"])
        r = await _a.wait_for(chat.send_message(UserMessage(text=prompt)), timeout=20.0)
        text = (r if isinstance(r, str) else str(r))[:400]
    except Exception as e:
        text = f"(reflection unavailable: {e})"
    now = datetime.now(timezone.utc).isoformat()
    await db.db.keno_reflections.insert_one({"ai_id": ai_id, "draw_number": draw_number,
                                             "result": result, "text": text, "at": now})
async def get_all():

    docs = await db.system_col.find(
        {"_id": {"$regex": "^activity:"}}, {"_id": 1, "phase": 1, "activity": 1, "updated_at": 1, "tick": 1}
    ).to_list(10)
    out = {}
    for d in docs:
        ai = d["_id"].split(":", 1)[1]
        out[ai] = {"phase": d.get("phase", "RESEARCH"),
                   "activity": d.get("activity", "Warming up..."),
                   "tick": d.get("tick", 0),
                   "updated_at": d.get("updated_at")}
    return out
