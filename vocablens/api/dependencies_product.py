from fastapi import Depends

from vocablens.api.dependencies_core import (
    get_job_queue,
    get_notification_decision_engine,
    get_notification_sink,
    get_personalization_service,
    get_uow_factory,
)
from vocablens.services.addiction_engine import AddictionEngine
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.business_metrics_service import BusinessMetricsService
from vocablens.services.conversion_funnel_service import ConversionFunnelService
from vocablens.services.daily_loop_service import DailyLoopService
from vocablens.services.decision_trace_service import DecisionTraceService
from vocablens.services.event_processors.knowledge_graph_processor import KnowledgeGraphProcessor
from vocablens.services.event_processors.retention_processor import RetentionProcessor
from vocablens.services.event_processors.skill_update_processor import SkillUpdateProcessor
from vocablens.services.event_service import EventService
from vocablens.services.experiment_results_service import ExperimentResultsService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.habit_engine import HabitEngine
from vocablens.services.knowledge_graph_service import KnowledgeGraphService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.learning_event_service import LearningEventService
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.monetization_engine import MonetizationEngine
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.onboarding_flow_service import OnboardingFlowService
from vocablens.services.onboarding_service import OnboardingService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.session_engine import SessionEngine
from vocablens.services.skill_tracking_service import SkillTrackingService
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.wow_engine import WowEngine


async def get_skill_tracking_service(uow_factory=Depends(get_uow_factory)):
    return SkillTrackingService(uow_factory)


async def get_learning_event_service(
    uow_factory=Depends(get_uow_factory),
    skill_tracker=Depends(get_skill_tracking_service),
    job_queue=Depends(get_job_queue),
    personalization=Depends(get_personalization_service),
    notifier=Depends(get_notification_sink),
    notification_decision_engine=Depends(get_notification_decision_engine),
):
    retention = RetentionEngine(uow_factory)
    kg_service = KnowledgeGraphService(uow_factory)
    from vocablens.services.event_processors.embedding_dispatcher import EmbeddingDispatchProcessor
    from vocablens.services.event_processors.enrichment_dispatcher import EnrichmentDispatchProcessor
    from vocablens.services.event_processors.personalization_update_processor import PersonalizationUpdateProcessor
    from vocablens.services.event_processors.retention_notification_processor import RetentionNotificationProcessor
    from vocablens.services.event_processors.skill_snapshot_dispatcher import SkillSnapshotDispatcher

    processors = [
        SkillUpdateProcessor(skill_tracker),
        RetentionProcessor(retention, uow_factory),
        RetentionNotificationProcessor(retention, notifier, notification_decision_engine),
        KnowledgeGraphProcessor(kg_service),
        PersonalizationUpdateProcessor(personalization),
        EnrichmentDispatchProcessor(job_queue),
        EmbeddingDispatchProcessor(job_queue),
        SkillSnapshotDispatcher(job_queue),
    ]
    return LearningEventService(processors=processors, uow_factory=uow_factory)


def get_event_service(uow_factory=Depends(get_uow_factory)) -> EventService:
    return EventService(uow_factory)


def get_progress_service(uow_factory=Depends(get_uow_factory)) -> ProgressService:
    return ProgressService(uow_factory)


def get_wow_engine(uow_factory=Depends(get_uow_factory)) -> WowEngine:
    return WowEngine(uow_factory)


def get_analytics_service(uow_factory=Depends(get_uow_factory)) -> AnalyticsService:
    return AnalyticsService(uow_factory)


def get_experiment_results_service(uow_factory=Depends(get_uow_factory)) -> ExperimentResultsService:
    return ExperimentResultsService(uow_factory)


def get_decision_trace_service(uow_factory=Depends(get_uow_factory)) -> DecisionTraceService:
    return DecisionTraceService(uow_factory)


async def get_experiment_service(
    uow_factory=Depends(get_uow_factory),
    learning_events=Depends(get_learning_event_service),
):
    return ExperimentService(uow_factory, learning_events)


def get_paywall_service(
    uow_factory=Depends(get_uow_factory),
    event_service=Depends(get_event_service),
    experiment_service=Depends(get_experiment_service),
) -> PaywallService:
    return AdaptivePaywallService(uow_factory, event_service, experiment_service)


def get_conversion_funnel_service(
    uow_factory=Depends(get_uow_factory),
    paywall_service=Depends(get_paywall_service),
    analytics_service=Depends(get_analytics_service),
    experiment_service=Depends(get_experiment_service),
) -> ConversionFunnelService:
    return ConversionFunnelService(uow_factory, paywall_service, analytics_service, experiment_service)


def get_business_metrics_service(
    uow_factory=Depends(get_uow_factory),
    analytics_service=Depends(get_analytics_service),
    conversion_funnel_service=Depends(get_conversion_funnel_service),
) -> BusinessMetricsService:
    return BusinessMetricsService(uow_factory, analytics_service, conversion_funnel_service)


def get_subscription_service(
    uow_factory=Depends(get_uow_factory),
    experiment_service=Depends(get_experiment_service),
    event_service=Depends(get_event_service),
    paywall_service=Depends(get_paywall_service),
) -> SubscriptionService:
    return SubscriptionService(uow_factory, experiment_service, event_service, paywall_service)


def get_retention_engine(
    uow_factory=Depends(get_uow_factory),
    experiment_service=Depends(get_experiment_service),
    event_service=Depends(get_event_service),
) -> RetentionEngine:
    return RetentionEngine(uow_factory, experiment_service, event_service)


def get_gamification_service(
    uow_factory=Depends(get_uow_factory),
    progress_service=Depends(get_progress_service),
    retention_engine=Depends(get_retention_engine),
    event_service=Depends(get_event_service),
) -> GamificationService:
    return GamificationService(uow_factory, progress_service, retention_engine, event_service)


def get_global_decision_engine(
    uow_factory=Depends(get_uow_factory),
    retention_engine=Depends(get_retention_engine),
    progress_service=Depends(get_progress_service),
    subscription_service=Depends(get_subscription_service),
    paywall_service=Depends(get_paywall_service),
) -> GlobalDecisionEngine:
    return GlobalDecisionEngine(
        uow_factory,
        retention_engine,
        progress_service,
        subscription_service,
        paywall_service,
    )


def get_onboarding_service(
    uow_factory=Depends(get_uow_factory),
    progress_service=Depends(get_progress_service),
    wow_engine=Depends(get_wow_engine),
    global_decision_engine=Depends(get_global_decision_engine),
) -> OnboardingService:
    return OnboardingService(uow_factory, progress_service, wow_engine, global_decision_engine)


def get_habit_engine(
    retention_engine=Depends(get_retention_engine),
    notification_decision_engine: NotificationDecisionEngine = Depends(get_notification_decision_engine),
    progress_service=Depends(get_progress_service),
    global_decision_engine=Depends(get_global_decision_engine),
) -> HabitEngine:
    return HabitEngine(retention_engine, notification_decision_engine, progress_service, global_decision_engine)


def get_addiction_engine(
    habit_engine=Depends(get_habit_engine),
    retention_engine=Depends(get_retention_engine),
    notification_decision_engine=Depends(get_notification_decision_engine),
    progress_service=Depends(get_progress_service),
) -> AddictionEngine:
    return AddictionEngine(habit_engine, retention_engine, notification_decision_engine, progress_service)


def get_lifecycle_service(
    uow_factory=Depends(get_uow_factory),
    retention_engine=Depends(get_retention_engine),
    progress_service=Depends(get_progress_service),
    notification_decision_engine=Depends(get_notification_decision_engine),
    paywall_service=Depends(get_paywall_service),
    global_decision_engine=Depends(get_global_decision_engine),
    onboarding_service=Depends(get_onboarding_service),
) -> LifecycleService:
    return LifecycleService(
        uow_factory,
        retention_engine,
        progress_service,
        notification_decision_engine,
        paywall_service,
        global_decision_engine,
        onboarding_service,
    )


def get_onboarding_flow_service(
    uow_factory=Depends(get_uow_factory),
    wow_engine=Depends(get_wow_engine),
    addiction_engine=Depends(get_addiction_engine),
    lifecycle_service=Depends(get_lifecycle_service),
    paywall_service=Depends(get_paywall_service),
    notification_decision_engine=Depends(get_notification_decision_engine),
    retention_engine=Depends(get_retention_engine),
) -> OnboardingFlowService:
    return OnboardingFlowService(
        uow_factory,
        wow_engine,
        addiction_engine,
        lifecycle_service,
        paywall_service,
        notification_decision_engine,
        retention_engine,
    )


def get_monetization_engine(
    uow_factory=Depends(get_uow_factory),
    paywall_service=Depends(get_paywall_service),
    business_metrics_service=Depends(get_business_metrics_service),
    onboarding_flow_service=Depends(get_onboarding_flow_service),
    lifecycle_service=Depends(get_lifecycle_service),
) -> MonetizationEngine:
    return MonetizationEngine(
        uow_factory,
        paywall_service,
        business_metrics_service,
        onboarding_flow_service,
        lifecycle_service,
    )


def get_learning_engine(
    uow_factory=Depends(get_uow_factory),
    retention_engine=Depends(get_retention_engine),
    personalization=Depends(get_personalization_service),
    subscription_service=Depends(get_subscription_service),
    experiment_service=Depends(get_experiment_service),
    event_service=Depends(get_event_service),
    global_decision_engine=Depends(get_global_decision_engine),
):
    return LearningEngine(
        uow_factory,
        retention_engine,
        personalization,
        subscription_service,
        experiment_service,
        event_service,
        global_decision_engine,
    )


def get_session_engine(
    uow_factory=Depends(get_uow_factory),
    learning_engine=Depends(get_learning_engine),
    wow_engine=Depends(get_wow_engine),
    gamification_service=Depends(get_gamification_service),
    event_service=Depends(get_event_service),
) -> SessionEngine:
    return SessionEngine(
        uow_factory,
        learning_engine,
        wow_engine,
        gamification_service,
        event_service,
    )


def get_daily_loop_service(
    uow_factory=Depends(get_uow_factory),
    learning_engine=Depends(get_learning_engine),
    gamification_service=Depends(get_gamification_service),
    notification_decision_engine=Depends(get_notification_decision_engine),
    retention_engine=Depends(get_retention_engine),
    event_service=Depends(get_event_service),
) -> DailyLoopService:
    return DailyLoopService(
        uow_factory,
        learning_engine,
        gamification_service,
        notification_decision_engine,
        retention_engine,
        event_service,
    )
