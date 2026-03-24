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


class ExperimentRegistryVariantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    weight: int = Field(..., ge=1, le=100000)


class ExperimentRegistryUpsertRequest(BaseModel):
    status: Literal["draft", "active", "paused", "archived"]
    rollout_percentage: int = Field(..., ge=0, le=100)
    is_killed: bool = False
    description: str | None = Field(default=None, max_length=1000)
    variants: list[ExperimentRegistryVariantRequest] = Field(..., min_length=1, max_length=20)
    change_note: str = Field(..., min_length=8, max_length=500)


class ExperimentRegistryVariantResponse(BaseModel):
    name: str
    weight: int


class ExperimentRegistryAuditEntryResponse(BaseModel):
    id: int
    experiment_key: str
    action: str
    changed_by: str
    change_note: str
    previous_config: dict[str, Any] = Field(default_factory=dict)
    new_config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ExperimentRegistryHealthResponse(BaseModel):
    assignment_count: int = 0
    exposure_count: int = 0
    exposure_gap: int = 0
    exposure_coverage_percent: float = 100.0
    assignment_variants: dict[str, int] = Field(default_factory=dict)
    exposure_variants: dict[str, int] = Field(default_factory=dict)


class ExperimentRegistrySummaryResponse(BaseModel):
    experiment_key: str
    status: str
    rollout_percentage: int
    is_killed: bool = False
    description: str | None = None
    variants: list[ExperimentRegistryVariantResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    assignment_count: int = 0
    exposure_count: int = 0
    exposure_gap: int = 0
    assignment_variants: dict[str, int] = Field(default_factory=dict)
    exposure_variants: dict[str, int] = Field(default_factory=dict)
    latest_change: ExperimentRegistryAuditEntryResponse | None = None


class ExperimentRegistryDetailResponseModel(BaseModel):
    experiment_key: str
    status: str
    rollout_percentage: int
    is_killed: bool = False
    description: str | None = None
    variants: list[ExperimentRegistryVariantResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    health: ExperimentRegistryHealthResponse
    audit_entries: list[ExperimentRegistryAuditEntryResponse] = Field(default_factory=list)


class ExperimentRegistryListDataResponse(BaseModel):
    experiments: list[ExperimentRegistrySummaryResponse] = Field(default_factory=list)


class ExperimentRegistryListMetaResponse(BaseModel):
    source: Literal["admin.experiments.registry.list"]


class ExperimentRegistryListResponse(BaseModel):
    data: ExperimentRegistryListDataResponse
    meta: ExperimentRegistryListMetaResponse


class ExperimentRegistryDetailDataResponse(BaseModel):
    experiment: ExperimentRegistryDetailResponseModel


class ExperimentRegistryDetailMetaResponse(BaseModel):
    source: Literal["admin.experiments.registry.detail", "admin.experiments.registry.update"]
    experiment_key: str


class ExperimentRegistryDetailResponse(BaseModel):
    data: ExperimentRegistryDetailDataResponse
    meta: ExperimentRegistryDetailMetaResponse


class ExperimentRegistryAuditDataResponse(BaseModel):
    audit_entries: list[ExperimentRegistryAuditEntryResponse] = Field(default_factory=list)


class ExperimentRegistryAuditMetaResponse(BaseModel):
    source: Literal["admin.experiments.registry.audit"]
    experiment_key: str


class ExperimentRegistryAuditResponse(BaseModel):
    data: ExperimentRegistryAuditDataResponse
    meta: ExperimentRegistryAuditMetaResponse


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


class SessionEvaluationDiagnosticsResponse(BaseModel):
    trace_type: str
    source: str
    is_correct: bool
    improvement_score: float
    highlighted_mistakes: list[str] = Field(default_factory=list)
    recommended_next_step: str | None = None
    reason: str | None = None
    created_at: datetime


class DecisionTraceDetailDataResponse(BaseModel):
    session: SessionDiagnosticsResponse
    evaluation: SessionEvaluationDiagnosticsResponse | None = None
    attempts: list[SessionAttemptDiagnosticsResponse] = Field(default_factory=list)
    events: list[SessionEventDiagnosticsResponse] = Field(default_factory=list)
    traces: list[DecisionTraceRecordResponse] = Field(default_factory=list)


class DecisionTraceDetailMetaResponse(BaseModel):
    source: Literal["admin.decision_traces.detail"]
    reference_id: str


class DecisionTraceDetailResponse(BaseModel):
    data: DecisionTraceDetailDataResponse
    meta: DecisionTraceDetailMetaResponse


class OnboardingDiagnosticsStateResponse(BaseModel):
    current_step: str
    steps_completed: list[str] = Field(default_factory=list)
    identity: dict[str, Any] = Field(default_factory=dict)
    personalization: dict[str, Any] = Field(default_factory=dict)
    wow: dict[str, Any] = Field(default_factory=dict)
    early_success_score: float = 0.0
    progress_illusion: dict[str, Any] = Field(default_factory=dict)
    paywall: dict[str, Any] = Field(default_factory=dict)
    habit_lock_in: dict[str, Any] = Field(default_factory=dict)


class OnboardingTransitionDiagnosticsResponse(BaseModel):
    trace_type: str
    source: str
    from_step: str | None = None
    to_step: str
    reason: str | None = None
    created_at: datetime


class OnboardingPaywallEntryDiagnosticsResponse(BaseModel):
    trace_type: str
    source: str
    next_step: str | None = None
    paywall_strategy: str | None = None
    trial_recommended: bool = False
    reason: str | None = None
    created_at: datetime


class OnboardingDiagnosticsDataResponse(BaseModel):
    state: OnboardingDiagnosticsStateResponse
    latest_transition: OnboardingTransitionDiagnosticsResponse | None = None
    paywall_entry: OnboardingPaywallEntryDiagnosticsResponse | None = None
    events: list[SessionEventDiagnosticsResponse] = Field(default_factory=list)
    traces: list[DecisionTraceRecordResponse] = Field(default_factory=list)


class OnboardingDiagnosticsMetaResponse(BaseModel):
    source: Literal["admin.onboarding.detail"]
    user_id: int


class OnboardingDiagnosticsResponse(BaseModel):
    data: OnboardingDiagnosticsDataResponse
    meta: OnboardingDiagnosticsMetaResponse


class UserLearningStateDiagnosticsResponse(BaseModel):
    user_id: int
    skills: dict[str, float] = Field(default_factory=dict)
    weak_areas: list[str] = Field(default_factory=list)
    mastery_percent: float = 0.0
    accuracy_rate: float = 0.0
    response_speed_seconds: float = 0.0
    updated_at: datetime | None = None


class UserEngagementStateDiagnosticsResponse(BaseModel):
    user_id: int
    current_streak: int = 0
    longest_streak: int = 0
    momentum_score: float = 0.0
    total_sessions: int = 0
    sessions_last_3_days: int = 0
    last_session_at: datetime | None = None
    shields_used_this_week: int = 0
    daily_mission_completed_at: datetime | None = None
    interaction_stats: dict[str, int] = Field(default_factory=dict)
    updated_at: datetime | None = None


class UserProgressStateDiagnosticsResponse(BaseModel):
    user_id: int
    xp: int = 0
    level: int = 1
    milestones: list[int] = Field(default_factory=list)
    updated_at: datetime | None = None


class UserProfileDiagnosticsResponse(BaseModel):
    user_id: int
    learning_speed: float = 0.0
    retention_rate: float = 0.0
    difficulty_preference: str | None = None
    content_preference: str | None = None
    last_active_at: datetime | None = None
    session_frequency: float = 0.0
    current_streak: int = 0
    longest_streak: int = 0
    drop_off_risk: float = 0.0
    preferred_channel: str | None = None
    preferred_time_of_day: int = 0
    frequency_limit: int = 0
    updated_at: datetime | None = None


class SubscriptionDiagnosticsResponse(BaseModel):
    user_id: int
    tier: str
    request_limit: int = 0
    token_limit: int = 0
    renewed_at: datetime | None = None
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    trial_tier: str | None = None
    created_at: datetime | None = None


class MonetizationStateDiagnosticsResponse(BaseModel):
    user_id: int
    current_offer_type: str | None = None
    last_paywall_type: str | None = None
    last_paywall_reason: str | None = None
    current_strategy: str | None = None
    current_geography: str | None = None
    lifecycle_stage: str | None = None
    paywall_impressions: int = 0
    paywall_dismissals: int = 0
    paywall_acceptances: int = 0
    paywall_skips: int = 0
    fatigue_score: int = 0
    cooldown_until: datetime | None = None
    trial_eligible: bool = True
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    trial_offer_days: int | None = None
    conversion_propensity: float = 0.0
    last_offer_at: datetime | None = None
    last_impression_at: datetime | None = None
    last_dismissed_at: datetime | None = None
    last_accepted_at: datetime | None = None
    last_skipped_at: datetime | None = None
    last_pricing: dict[str, Any] = Field(default_factory=dict)
    last_trigger: dict[str, Any] = Field(default_factory=dict)
    last_value_display: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None


class MonetizationOfferEventDiagnosticsResponse(BaseModel):
    id: int
    event_type: str
    offer_type: str | None = None
    paywall_type: str | None = None
    strategy: str | None = None
    geography: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RetentionSuggestedActionResponse(BaseModel):
    kind: str
    reason: str
    target: str | None = None


class RetentionDiagnosticsResponse(BaseModel):
    state: str
    drop_off_risk: float = 0.0
    session_frequency: float = 0.0
    current_streak: int = 0
    longest_streak: int = 0
    last_active_at: datetime | None = None
    is_high_engagement: bool = False
    suggested_actions: list[RetentionSuggestedActionResponse] = Field(default_factory=list)


class LifecycleActionDiagnosticsResponse(BaseModel):
    type: str
    message: str
    target: str | None = None


class LifecyclePaywallDiagnosticsResponse(BaseModel):
    show: bool
    type: str | None = None
    reason: str | None = None
    usage_percent: int = 0
    allow_access: bool = True


class LifecycleDecisionDiagnosticsResponse(BaseModel):
    stage: str
    reasons: list[str] = Field(default_factory=list)
    actions: list[LifecycleActionDiagnosticsResponse] = Field(default_factory=list)
    paywall: LifecyclePaywallDiagnosticsResponse


class AdaptivePaywallDiagnosticsResponse(BaseModel):
    show_paywall: bool
    paywall_type: str | None = None
    reason: str | None = None
    usage_percent: int = 0
    request_usage_percent: int = 0
    token_usage_percent: int = 0
    usage_requests: int = 0
    usage_tokens: int = 0
    request_limit: int = 0
    token_limit: int = 0
    sessions_seen: int = 0
    wow_moment_triggered: bool = False
    trial_active: bool = False
    trial_tier: str | None = None
    trial_ends_at: datetime | None = None
    allow_access: bool = True
    user_segment: str
    strategy: str
    trigger_variant: str
    pricing_variant: str
    trial_days: int = 0
    wow_score: float = 0.0
    trial_recommended: bool = False
    upsell_recommended: bool = False


class MonetizationPricingBusinessContextResponse(BaseModel):
    ltv: float = 0.0
    mrr: float = 0.0


class MonetizationPricingDiagnosticsResponse(BaseModel):
    geography: str
    monthly_price: float
    discounted_monthly_price: float
    discount_percent: int
    annual_price: float
    annual_monthly_equivalent: float
    annual_savings_percent: int
    pricing_variant: str
    annual_anchor_message: str
    business_context: MonetizationPricingBusinessContextResponse


class MonetizationTriggerDiagnosticsResponse(BaseModel):
    show_now: bool
    trigger_variant: str
    trigger_reason: str | None = None
    lifecycle_stage: str
    onboarding_step: str | None = None
    timing_policy: str


class MonetizationValueDisplayDiagnosticsResponse(BaseModel):
    show_locked_progress: bool
    locked_progress_percent: int = 0
    locked_features: list[str] = Field(default_factory=list)
    highlight: str = ""
    usage_percent: int = 0


class MonetizationDecisionDiagnosticsResponse(BaseModel):
    show_paywall: bool
    paywall_type: str | None = None
    offer_type: str
    pricing: MonetizationPricingDiagnosticsResponse
    trigger: MonetizationTriggerDiagnosticsResponse
    value_display: MonetizationValueDisplayDiagnosticsResponse
    strategy: str
    lifecycle_stage: str
    onboarding_step: str | None = None
    user_segment: str
    trial_days: int | None = None


class LifecycleDiagnosticsDataResponse(BaseModel):
    onboarding_state: OnboardingDiagnosticsStateResponse | None = None
    learning_state: UserLearningStateDiagnosticsResponse | None = None
    engagement_state: UserEngagementStateDiagnosticsResponse | None = None
    profile: UserProfileDiagnosticsResponse | None = None
    retention: RetentionDiagnosticsResponse
    lifecycle: LifecycleDecisionDiagnosticsResponse
    adaptive_paywall: AdaptivePaywallDiagnosticsResponse
    events: list[SessionEventDiagnosticsResponse] = Field(default_factory=list)
    traces: list[DecisionTraceRecordResponse] = Field(default_factory=list)


class LifecycleDiagnosticsMetaResponse(BaseModel):
    source: Literal["admin.lifecycle.detail"]
    user_id: int


class LifecycleDiagnosticsResponse(BaseModel):
    data: LifecycleDiagnosticsDataResponse
    meta: LifecycleDiagnosticsMetaResponse


class MonetizationDiagnosticsDataResponse(BaseModel):
    onboarding_state: OnboardingDiagnosticsStateResponse | None = None
    learning_state: UserLearningStateDiagnosticsResponse | None = None
    engagement_state: UserEngagementStateDiagnosticsResponse | None = None
    progress_state: UserProgressStateDiagnosticsResponse | None = None
    profile: UserProfileDiagnosticsResponse | None = None
    subscription: SubscriptionDiagnosticsResponse | None = None
    monetization_state: MonetizationStateDiagnosticsResponse | None = None
    experiments: dict[str, str] = Field(default_factory=dict)
    retention: RetentionDiagnosticsResponse
    lifecycle: LifecycleDecisionDiagnosticsResponse
    adaptive_paywall: AdaptivePaywallDiagnosticsResponse
    monetization: MonetizationDecisionDiagnosticsResponse
    monetization_events: list[MonetizationOfferEventDiagnosticsResponse] = Field(default_factory=list)
    events: list[SessionEventDiagnosticsResponse] = Field(default_factory=list)
    traces: list[DecisionTraceRecordResponse] = Field(default_factory=list)


class MonetizationDiagnosticsMetaResponse(BaseModel):
    source: Literal["admin.monetization.detail"]
    user_id: int
    geography: str | None = None


class MonetizationDiagnosticsResponse(BaseModel):
    data: MonetizationDiagnosticsDataResponse
    meta: MonetizationDiagnosticsMetaResponse


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
