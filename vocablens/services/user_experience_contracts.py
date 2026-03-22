from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProgressMetrics(BaseModel):
    vocabulary_mastery_percent: float = 0.0
    accuracy_rate: float = 0.0
    response_speed_seconds: float = 0.0
    fluency_score: float = 0.0


class ProgressPeriod(BaseModel):
    words_learned: int = 0
    reviews_completed: int = 0
    messages_sent: int = 0
    accuracy_rate: float | None = None


class ProgressTrends(BaseModel):
    weekly_words_learned_delta: int | None = None
    weekly_reviews_completed_delta: int | None = None
    weekly_messages_sent_delta: int | None = None
    weekly_accuracy_rate_delta: float | None = None
    fluency_score: float | None = None


class SkillBreakdown(BaseModel):
    grammar: float = 0.0
    vocabulary: float = 0.0
    fluency: float = 0.0


class DashboardProgress(BaseModel):
    vocabulary_total: int
    due_reviews: int
    streak: int
    session_frequency: float
    retention_state: str
    metrics: ProgressMetrics
    daily: ProgressPeriod
    weekly: ProgressPeriod
    trends: ProgressTrends
    skill_breakdown: SkillBreakdown


class SubscriptionSnapshot(BaseModel):
    tier: str
    tutor_depth: str
    explanation_quality: str
    personalization_level: str
    trial_active: bool
    trial_ends_at: str | None = None
    usage_percent: int


class PaywallSnapshot(BaseModel):
    show: bool
    type: str | None = None
    reason: str | None = None
    usage_percent: int
    allow_access: bool = True
    trial_active: bool = False
    trial_ends_at: str | None = None
    request_usage_percent: int | None = None
    token_usage_percent: int | None = None
    trial_tier: str | None = None


class NextActionSnapshot(BaseModel):
    action: str
    target: str | None = None
    reason: str
    difficulty: str
    content_type: str


class RetentionActionSnapshot(BaseModel):
    kind: str
    reason: str
    target: str | None = None


class RetentionSnapshot(BaseModel):
    state: str
    drop_off_risk: float
    actions: list[RetentionActionSnapshot]


class WeakAreaMistake(BaseModel):
    category: str | None = None
    pattern: str | None = None
    count: int | None = None


class WeakAreasSnapshot(BaseModel):
    clusters: list[dict[str, Any]]
    mistakes: list[WeakAreaMistake]


class UiDirectivesSnapshot(BaseModel):
    show_streak_animation: bool
    show_progress_boost: bool
    show_paywall: bool
    show_celebration: bool


class SessionConfigSnapshot(BaseModel):
    session_length: int
    difficulty: str
    mode: str


class EmotionHooksSnapshot(BaseModel):
    encouragement_message: str
    urgency_message: str
    reward_message: str


class FrontendDashboardResponse(BaseModel):
    progress: DashboardProgress
    subscription: SubscriptionSnapshot
    paywall: PaywallSnapshot
    skills: dict[str, float]
    next_action: NextActionSnapshot
    retention: RetentionSnapshot
    weak_areas: WeakAreasSnapshot
    ui: UiDirectivesSnapshot
    session_config: SessionConfigSnapshot
    emotion_hooks: EmotionHooksSnapshot
    roadmap: dict[str, Any]


class FrontendRecommendationsResponse(BaseModel):
    next_action: NextActionSnapshot
    retention_actions: list[RetentionActionSnapshot]
    paywall: PaywallSnapshot
    ui: UiDirectivesSnapshot
    session_config: SessionConfigSnapshot
    emotion_hooks: EmotionHooksSnapshot


class WeakSkillSnapshot(BaseModel):
    skill: str
    score: float


class FrontendWeakAreasResponse(BaseModel):
    weak_skills: list[WeakSkillSnapshot]
    weak_clusters: list[dict[str, Any]]
    mistake_patterns: list[WeakAreaMistake]


class OnboardingMessaging(BaseModel):
    encouragement_message: str
    urgency_message: str
    reward_message: str


class OnboardingResponse(BaseModel):
    current_step: str
    onboarding_state: dict[str, Any]
    ui_directives: dict[str, Any]
    messaging: OnboardingMessaging
    next_action: dict[str, Any] = Field(default_factory=dict)
