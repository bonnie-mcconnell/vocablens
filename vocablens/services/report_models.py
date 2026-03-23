from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversionMetrics:
    counts_by_event: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RetentionCurve:
    d1: float = 0.0
    d7: float = 0.0
    d30: float = 0.0


@dataclass(frozen=True)
class RetentionCohort:
    cohort_date: str
    size: int
    d1_retention: float
    d7_retention: float
    d30_retention: float
    retention_curve: RetentionCurve


@dataclass(frozen=True)
class RetentionReport:
    cohorts: list[RetentionCohort] = field(default_factory=list)
    churn_rate: float = 0.0


@dataclass(frozen=True)
class UsageEngagementDistribution:
    low: int = 0
    medium: int = 0
    high: int = 0


@dataclass(frozen=True)
class UsageReport:
    dau: int = 0
    mau: int = 0
    dau_mau_ratio: float = 0.0
    avg_session_length_seconds: float = 0.0
    sessions_per_user: float = 0.0
    engagement_distribution: UsageEngagementDistribution = field(default_factory=UsageEngagementDistribution)


@dataclass(frozen=True)
class ExperimentVariantEngagement:
    sessions_per_user: float = 0.0
    messages_per_user: float = 0.0
    learning_actions_per_user: float = 0.0


@dataclass(frozen=True)
class ExperimentVariantResult:
    experiment_key: str
    variant: str
    users: int
    retention_rate: float
    conversion_rate: float
    engagement: ExperimentVariantEngagement


@dataclass(frozen=True)
class ExperimentSignificance:
    z_score: float = 0.0
    is_significant: bool = False


@dataclass(frozen=True)
class ExperimentComparison:
    baseline_variant: str
    candidate_variant: str
    retention_lift: float
    conversion_lift: float
    retention_significance: ExperimentSignificance
    conversion_significance: ExperimentSignificance


@dataclass(frozen=True)
class ExperimentResult:
    experiment_key: str
    variants: list[ExperimentVariantResult] = field(default_factory=list)
    comparisons: list[ExperimentComparison] = field(default_factory=list)


@dataclass(frozen=True)
class ExperimentResultsReport:
    experiments: list[ExperimentResult] = field(default_factory=list)


@dataclass(frozen=True)
class AdaptivePaywallStrategyMetrics:
    strategy: str
    views: int
    upgrades: int
    conversion_rate: float


@dataclass(frozen=True)
class AdaptivePaywallConversionReport:
    strategies: list[AdaptivePaywallStrategyMetrics] = field(default_factory=list)


@dataclass(frozen=True)
class FunnelStageMetrics:
    stage: str
    users: int
    conversion_rate: float
    drop_off_rate: float


@dataclass(frozen=True)
class FunnelMetricsReport:
    stages: list[FunnelStageMetrics] = field(default_factory=list)
    retention_summary: RetentionReport | dict[str, Any] | None = None


@dataclass(frozen=True)
class RevenueMetrics:
    mrr: float
    arpu: float
    arpu_all_users: float
    ltv: float
    paying_users: int
    pricing_assumptions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BusinessFunnelSummary:
    conversion_per_stage: list[FunnelStageMetrics] = field(default_factory=list)


@dataclass(frozen=True)
class RetentionCurvePoint:
    day: int
    retention: float


@dataclass(frozen=True)
class RetentionVisualizationCurve:
    cohort_date: str
    points: list[RetentionCurvePoint] = field(default_factory=list)


@dataclass(frozen=True)
class RetentionVisualization:
    curves: list[RetentionVisualizationCurve] = field(default_factory=list)
    churn_rate: float = 0.0


@dataclass(frozen=True)
class BusinessMetricsDashboard:
    revenue: RevenueMetrics
    funnel: BusinessFunnelSummary
    retention_visualization: RetentionVisualization


@dataclass(frozen=True)
class MonetizationBusinessContext:
    ltv: float = 0.0
    mrr: float = 0.0


@dataclass(frozen=True)
class MonetizationPricing:
    geography: str
    monthly_price: float
    discounted_monthly_price: float
    discount_percent: int
    annual_price: float
    annual_monthly_equivalent: float
    annual_savings_percent: int
    pricing_variant: str
    annual_anchor_message: str
    business_context: MonetizationBusinessContext


@dataclass(frozen=True)
class MonetizationTrigger:
    show_now: bool
    trigger_variant: str
    trigger_reason: str | None
    lifecycle_stage: str
    onboarding_step: str | None
    timing_policy: str


@dataclass(frozen=True)
class MonetizationValueDisplay:
    show_locked_progress: bool
    locked_progress_percent: int
    locked_features: list[str] = field(default_factory=list)
    highlight: str = ""
    usage_percent: int = 0


@dataclass(frozen=True)
class FunnelMessaging:
    urgency_message: str = ""
    anchoring_message: str = ""


@dataclass(frozen=True)
class FunnelPaywallState:
    show: bool
    type: str | None
    reason: str | None
    usage_percent: int


@dataclass(frozen=True)
class AdaptivePaywallViewedEvent:
    source: str
    type: str | None
    reason: str | None
    usage_percent: int
    user_segment: str
    strategy: str
    trigger_variant: str
    pricing_variant: str
    trial_days: int
    wow_score: float
    trial_recommended: bool
    upsell_recommended: bool


@dataclass(frozen=True)
class LifecycleAction:
    type: str
    message: str
    target: str | None = None


@dataclass(frozen=True)
class LifecycleNotification:
    should_send: bool
    reason: str
    channel: str | None = None
    send_at: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class LifecyclePaywallState:
    show: bool
    type: str | None
    reason: str | None
    usage_percent: int
    allow_access: bool


@dataclass(frozen=True)
class HabitTrigger:
    type: str
    channel: str | None
    send_at: str | None
    category: str
    reason: str
    streak_reminder: bool


@dataclass(frozen=True)
class HabitAction:
    type: str
    duration_minutes: int
    target: str
    reason: str


@dataclass(frozen=True)
class HabitReward:
    progress_increase: int
    streak_boost: int
    feedback: str


@dataclass(frozen=True)
class HabitRepeat:
    should_repeat: bool
    next_best_trigger: str
    cadence: str


@dataclass(frozen=True)
class VariableReward:
    type: str
    bonus_xp: int
    surprise_streak_boost: int
    progress_increase: int
    feedback: str | None


@dataclass(frozen=True)
class LossAversionPlan:
    show_streak_decay_warning: bool
    will_lose_progress: bool
    warning_message: str


@dataclass(frozen=True)
class IdentityReinforcement:
    message: str
    identity_state: str


@dataclass(frozen=True)
class RitualHook:
    daily_ritual_hour: int
    daily_ritual_message: str
    streak_anchor: int


@dataclass(frozen=True)
class OnboardingGuidedStep:
    type: str
    message: str


@dataclass(frozen=True)
class OnboardingFirstWin:
    ensure_success: bool
    target_accuracy: float
    message: str


@dataclass(frozen=True)
class OnboardingWowPayload:
    score: float
    qualifies: bool
    triggered: bool
    understood_percent: float | None = None
    triggers: dict[str, bool] = field(default_factory=dict)
    session_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OnboardingHabitHook:
    show_streak_starting: bool
    show_progress_jump: bool
    engagement_action: str
    message: str


@dataclass(frozen=True)
class OnboardingUiDirectives:
    show_identity_picker: bool
    show_personalization_form: bool
    show_wow_meter: bool
    show_progress_boost: bool
    show_streak_animation: bool
    show_relative_ranking: bool
    show_paywall: bool
    show_trial_offer: bool
    show_notification_scheduler: bool


@dataclass(frozen=True)
class OnboardingFlowMessageSet:
    encouragement_message: str
    urgency_message: str
    reward_message: str


@dataclass(frozen=True)
class OnboardingNextAction:
    action: str
    target: Any
    reason: str


@dataclass
class OnboardingIdentityState:
    motivation: str | None = None


@dataclass
class OnboardingPersonalizationState:
    skill_level: str | None = None
    daily_goal: int | None = None
    learning_intent: str | None = None


@dataclass
class OnboardingProgressIllusionState:
    xp_gain: int = 0
    initial_streak: int = 0
    relative_ranking_percentile: int = 0
    reward: dict[str, Any] = field(default_factory=dict)
    identity: dict[str, Any] = field(default_factory=dict)


@dataclass
class OnboardingPaywallState:
    show: bool = False
    type: str | None = None
    reason: str | None = None
    usage_percent: int = 0
    allow_access: bool = True
    trial_recommended: bool = False
    trial_days: int | None = None
    wow_score: float = 0.0
    strategy: str | None = None
    trial_started: bool = False


@dataclass
class OnboardingScheduledNotificationState:
    should_send: bool
    send_at: str | None
    channel: str | None
    reason: str


@dataclass
class OnboardingHabitLockInState:
    preferred_time_of_day: int | None = None
    preferred_channel: str | None = None
    frequency_limit: int | None = None
    scheduled_notification: OnboardingScheduledNotificationState | None = None
    ritual: dict[str, Any] = field(default_factory=dict)
    pressure: dict[str, Any] = field(default_factory=dict)


@dataclass
class OnboardingFlowState:
    current_step: str
    steps_completed: list[str] = field(default_factory=list)
    identity: OnboardingIdentityState = field(default_factory=OnboardingIdentityState)
    personalization: OnboardingPersonalizationState = field(default_factory=OnboardingPersonalizationState)
    wow: OnboardingWowPayload = field(default_factory=lambda: OnboardingWowPayload(score=0.0, qualifies=False, triggered=False, understood_percent=0.0))
    early_success_score: float = 0.0
    progress_illusion: OnboardingProgressIllusionState = field(default_factory=OnboardingProgressIllusionState)
    paywall: OnboardingPaywallState = field(default_factory=OnboardingPaywallState)
    habit_lock_in: OnboardingHabitLockInState = field(default_factory=OnboardingHabitLockInState)
