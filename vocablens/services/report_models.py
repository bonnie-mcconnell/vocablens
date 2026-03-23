from __future__ import annotations

from dataclasses import dataclass, field


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
