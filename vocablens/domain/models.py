from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class VocabularyItem:

    id: Optional[int]

    source_text: str
    translated_text: str

    source_lang: str
    target_lang: str

    created_at: datetime

    # AI enrichment
    example_source_sentence: Optional[str] = None
    example_translated_sentence: Optional[str] = None
    grammar_note: Optional[str] = None
    semantic_cluster: Optional[str] = None

    # spaced repetition (SM-2)
    last_reviewed_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    review_count: int = 0
    ease_factor: float = 2.5
    interval: int = 1
    repetitions: int = 0
    next_review_due: Optional[datetime] = None
    success_rate: float = 0.0
    decay_score: float = 0.0


@dataclass(slots=True)
class UserLearningState:
    user_id: int
    skills: dict[str, float]
    weak_areas: list[str]
    mastery_percent: float
    accuracy_rate: float
    response_speed_seconds: float
    updated_at: datetime


@dataclass(slots=True)
class UserEngagementState:
    user_id: int
    current_streak: int
    longest_streak: int
    momentum_score: float
    total_sessions: int
    sessions_last_3_days: int
    last_session_at: Optional[datetime]
    shields_used_this_week: int
    daily_mission_completed_at: Optional[datetime]
    interaction_stats: dict[str, int]
    updated_at: datetime


@dataclass(slots=True)
class UserProgressState:
    user_id: int
    xp: int
    level: int
    milestones: list[int]
    updated_at: datetime
