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


@dataclass(slots=True)
class LearningSession:
    session_id: str
    user_id: int
    status: str
    contract_version: str
    duration_seconds: int
    mode: str
    weak_area: str
    lesson_target: Optional[str]
    goal_label: str
    success_criteria: str
    review_window_minutes: int
    max_response_words: int
    session_payload: dict
    created_at: datetime
    expires_at: datetime
    completed_at: Optional[datetime]
    last_evaluated_at: Optional[datetime]
    evaluation_count: int


@dataclass(slots=True)
class LearningSessionAttempt:
    id: int
    session_id: str
    user_id: int
    submission_id: str
    learner_response: str
    response_word_count: int
    response_char_count: int
    is_correct: bool
    improvement_score: float
    validation_payload: dict
    feedback_payload: dict
    created_at: datetime


@dataclass(slots=True)
class DecisionTrace:
    id: int
    user_id: int
    trace_type: str
    source: str
    reference_id: Optional[str]
    policy_version: str
    inputs: dict
    outputs: dict
    reason: Optional[str]
    created_at: datetime
