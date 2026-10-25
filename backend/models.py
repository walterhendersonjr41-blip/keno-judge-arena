"""Pydantic models for Keno Duel AI."""
from datetime import datetime, timezone
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# Draw source labels
SOURCE_LIVE = "LIVE"
SOURCE_PRACTICE = "PRACTICE"
SOURCE_SIMULATED = "SIMULATED"
SOURCE_IMPORTED = "IMPORTED"


class Draw(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    draw_number: int
    winning_numbers: List[int]
    drawn_at: str = Field(default_factory=now_iso)
    source: str = SOURCE_SIMULATED  # LIVE | PRACTICE | SIMULATED | IMPORTED
    mode: str = "practice"  # "practice" | "live" — logical bucket
    bulls_eye: Optional[int] = None  # stored but never used


class Ticket(BaseModel):
    spots: int
    numbers: List[int]
    label: Optional[str] = None


class Prediction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    ai_id: str
    target_draw_number: int
    mode: str = "practice"  # locked at creation
    tickets: List[Ticket]
    reasoning: str = ""
    generated_at: str = Field(default_factory=now_iso)
    sealed_at: str = Field(default_factory=now_iso)  # cannot be edited after this
    revealed: bool = False


class TicketScore(BaseModel):
    spots: int
    numbers: List[int]
    hits: List[int]
    hit_count: int
    label: Optional[str] = None


class PredictionScore(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    ai_id: str
    draw_number: int
    mode: str = "practice"
    winning_numbers: List[int]
    ticket_scores: List[TicketScore]
    total_hits: int
    best_hit_rate: float
    xp_awarded: int
    result: str  # "win" | "loss" | "draw" | "no_play"
    scored_at: str = Field(default_factory=now_iso)


class AIStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    ai_id: str
    display_name: str
    model_name: str
    accent: str
    personality: str = ""  # e.g. "The Architect"
    personality_tag: str = ""  # short line
    mode: str = "practice"  # this stats bucket

    total_wins: int = 0
    total_losses: int = 0
    total_draws: int = 0
    total_no_play: int = 0
    rounds_played: int = 0

    current_streak: int = 0
    longest_win_streak: int = 0
    longest_loss_streak: int = 0

    total_hits: int = 0
    total_ticket_spots: int = 0

    best_5pick: int = 0
    best_6pick: int = 0
    best_7pick: int = 0
    best_8pick: int = 0

    lifetime_score: int = 0
    xp: int = 0
    trophies: int = 0
    championship_titles: int = 0
    reign_current: int = 0        # consecutive draws as champion right now
    reign_longest: int = 0        # longest reign ever
    times_became_leader: int = 0

    reputation: float = 1000.0
    confidence: float = 0.5

    league_rank: str = "Bronze"
    is_champion: bool = False
    in_recovery: bool = False
    mood: str = "Waiting to compete."

    badges: List[str] = Field(default_factory=list)  # includes awards
    # head-to-head: {"beta": {"wins":x,"losses":y,"draws":z}}
    h2h: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=now_iso)


class ConsensusRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    draw_number: int
    mode: str = "practice"
    consensus_numbers: List[int]
    unanimous_numbers: List[int]
    consensus_score: float
    consensus_hits: int
    scored_at: str = Field(default_factory=now_iso)


class JudgeRelease(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    target_draw_number: int
    mode: str = "practice"
    released: bool
    reasoning: str
    recommended_ticket: Optional[Ticket] = None
    source: str
    created_at: str = Field(default_factory=now_iso)


class PressStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    draw_number: int
    mode: str
    headline: str
    body: str
    created_at: str = Field(default_factory=now_iso)


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    event: str
    payload: Dict = Field(default_factory=dict)
    mode: str = "practice"
    created_at: str = Field(default_factory=now_iso)
