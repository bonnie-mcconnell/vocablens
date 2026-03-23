from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from vocablens.core.constants import MAX_TEXT_LENGTH
from vocablens.domain.models import VocabularyItem


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    

class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    source_lang: str = Field(..., min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")
    target_lang: str = Field(..., min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")


class VocabularyResponse(BaseModel):
    id: int | None
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    created_at: datetime
    last_reviewed_at: datetime | None
    review_count: int
    ease_factor: float
    interval: int
    repetitions: int
    next_review_due: datetime | None

    @classmethod
    def from_domain(cls, item: VocabularyItem) -> "VocabularyResponse":
        return cls(
            id=item.id,
            source_text=item.source_text,
            translated_text=item.translated_text,
            source_lang=item.source_lang,
            target_lang=item.target_lang,
            created_at=item.created_at,
            last_reviewed_at=item.last_reviewed_at,
            review_count=item.review_count,
            ease_factor=item.ease_factor,
            interval=item.interval,
            repetitions=item.repetitions,
            next_review_due=item.next_review_due,
        )
    


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]


class APIResponse(BaseModel):
    data: Any
    meta: dict[str, Any] = Field(default_factory=dict)


class ConversionMetricsDataResponse(BaseModel):
    conversion_metrics: dict[str, int] = Field(default_factory=dict)


class ConversionMetricsMetaResponse(BaseModel):
    source: Literal["admin.conversions"]


class ConversionMetricsResponse(BaseModel):
    data: ConversionMetricsDataResponse
    meta: ConversionMetricsMetaResponse


class RetentionCurveResponse(BaseModel):
    d1: float = 0.0
    d7: float = 0.0
    d30: float = 0.0


class RetentionCohortResponse(BaseModel):
    cohort_date: str
    size: int = 0
    d1_retention: float = 0.0
    d7_retention: float = 0.0
    d30_retention: float = 0.0
    retention_curve: RetentionCurveResponse = Field(default_factory=RetentionCurveResponse)


class RetentionReportResponse(BaseModel):
    cohorts: list[RetentionCohortResponse] = Field(default_factory=list)
    churn_rate: float = 0.0


class RetentionAnalyticsDataResponse(BaseModel):
    retention: RetentionReportResponse


class RetentionAnalyticsMetaResponse(BaseModel):
    source: Literal["admin.analytics.retention"]


class RetentionAnalyticsResponse(BaseModel):
    data: RetentionAnalyticsDataResponse
    meta: RetentionAnalyticsMetaResponse


class UsageEngagementDistributionResponse(BaseModel):
    low: int = 0
    medium: int = 0
    high: int = 0


class UsageReportResponse(BaseModel):
    dau: int = 0
    mau: int = 0
    dau_mau_ratio: float = 0.0
    avg_session_length_seconds: float = 0.0
    sessions_per_user: float = 0.0
    engagement_distribution: UsageEngagementDistributionResponse = Field(
        default_factory=UsageEngagementDistributionResponse
    )


class UsageAnalyticsDataResponse(BaseModel):
    usage: UsageReportResponse


class UsageAnalyticsMetaResponse(BaseModel):
    source: Literal["admin.analytics.usage"]


class UsageAnalyticsResponse(BaseModel):
    data: UsageAnalyticsDataResponse
    meta: UsageAnalyticsMetaResponse


class ExperimentVariantEngagementResponse(BaseModel):
    sessions_per_user: float = 0.0
    messages_per_user: float = 0.0
    learning_actions_per_user: float = 0.0


class ExperimentVariantResultResponse(BaseModel):
    experiment_key: str | None = None
    variant: str
    users: int = 0
    retention_rate: float = 0.0
    conversion_rate: float = 0.0
    engagement: ExperimentVariantEngagementResponse = Field(default_factory=ExperimentVariantEngagementResponse)


class ExperimentSignificanceResponse(BaseModel):
    z_score: float = 0.0
    is_significant: bool = False


class ExperimentComparisonResponse(BaseModel):
    baseline_variant: str
    candidate_variant: str
    retention_lift: float = 0.0
    conversion_lift: float = 0.0
    retention_significance: ExperimentSignificanceResponse = Field(default_factory=ExperimentSignificanceResponse)
    conversion_significance: ExperimentSignificanceResponse = Field(default_factory=ExperimentSignificanceResponse)


class ExperimentResultItemResponse(BaseModel):
    experiment_key: str
    variants: list[ExperimentVariantResultResponse] = Field(default_factory=list)
    comparisons: list[ExperimentComparisonResponse] = Field(default_factory=list)


class ExperimentResultsPayloadResponse(BaseModel):
    experiments: list[ExperimentResultItemResponse] = Field(default_factory=list)


class ExperimentResultsDataResponse(BaseModel):
    experiment_results: ExperimentResultsPayloadResponse


class ExperimentResultsMetaResponse(BaseModel):
    source: Literal["admin.experiments.results"]


class ExperimentResultsResponse(BaseModel):
    data: ExperimentResultsDataResponse
    meta: ExperimentResultsMetaResponse


class DecisionTraceRecordResponse(BaseModel):
    id: int
    user_id: int
    trace_type: str
    source: str
    reference_id: str | None = None
    policy_version: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    created_at: datetime


class DecisionTraceListDataResponse(BaseModel):
    traces: list[DecisionTraceRecordResponse] = Field(default_factory=list)


class DecisionTraceListFiltersResponse(BaseModel):
    user_id: int | None = None
    trace_type: str | None = None
    reference_id: str | None = None
    limit: int


class DecisionTraceListMetaResponse(BaseModel):
    source: Literal["admin.decision_traces"]
    filters: DecisionTraceListFiltersResponse


class DecisionTraceListResponse(BaseModel):
    data: DecisionTraceListDataResponse
    meta: DecisionTraceListMetaResponse


class SessionDiagnosticsResponse(BaseModel):
    session_id: str
    user_id: int
    status: str
    duration_seconds: int
    mode: str
    weak_area: str
    lesson_target: str | None = None
    goal_label: str
    success_criteria: str
    review_window_minutes: int
    session_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    evaluation_count: int


class SessionAttemptDiagnosticsResponse(BaseModel):
    id: int
    session_id: str
    user_id: int
    learner_response: str
    is_correct: bool
    improvement_score: float
    feedback_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionEventDiagnosticsResponse(BaseModel):
    id: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DecisionTraceDetailDataResponse(BaseModel):
    session: SessionDiagnosticsResponse
    attempts: list[SessionAttemptDiagnosticsResponse] = Field(default_factory=list)
    events: list[SessionEventDiagnosticsResponse] = Field(default_factory=list)
    traces: list[DecisionTraceRecordResponse] = Field(default_factory=list)


class DecisionTraceDetailMetaResponse(BaseModel):
    source: Literal["admin.decision_traces.detail"]
    reference_id: str


class DecisionTraceDetailResponse(BaseModel):
    data: DecisionTraceDetailDataResponse
    meta: DecisionTraceDetailMetaResponse


class OnboardingStartRequest(BaseModel):
    pass


class OnboardingNextRequest(BaseModel):
    motivation: str | None = None
    skill_level: str | None = None
    daily_goal: int | None = None
    learning_intent: str | None = None
    session_snapshot: dict[str, Any] | None = None
    accept_trial: bool | None = None
    skip_paywall: bool | None = None
    preferred_time_of_day: int | None = Field(default=None, ge=0, le=23)
    preferred_channel: Literal["email", "push", "in_app"] | None = None
    frequency_limit: int | None = Field(default=None, ge=1)


class SessionStartRequest(BaseModel):
    pass


class SessionEvaluateRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=128)
    learner_response: str = Field(..., min_length=1, max_length=500)
