from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository
from vocablens.infrastructure.postgres_translation_cache_repository import PostgresTranslationCacheRepository
from vocablens.infrastructure.postgres_conversation_repository import PostgresConversationRepository
from vocablens.infrastructure.postgres_learning_event_repository import PostgresLearningEventRepository
from vocablens.infrastructure.postgres_skill_tracking_repository import PostgresSkillTrackingRepository
from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository
from vocablens.infrastructure.knowledge_graph_repository import KnowledgeGraphRepository
from vocablens.infrastructure.postgres_usage_repository import PostgresUsageRepository
from vocablens.infrastructure.postgres_subscription_repository import PostgresSubscriptionRepository
from vocablens.infrastructure.postgres_subscription_event_repository import PostgresSubscriptionEventRepository
from vocablens.infrastructure.postgres_mistake_pattern_repository import PostgresMistakePatternRepository
from vocablens.infrastructure.postgres_user_profile_repository import PostgresUserProfileRepository
from vocablens.infrastructure.postgres_notification_delivery_repository import PostgresNotificationDeliveryRepository
from vocablens.infrastructure.postgres_user_notification_state_repository import (
    PostgresUserNotificationStateRepository,
)
from vocablens.infrastructure.postgres_notification_suppression_event_repository import (
    PostgresNotificationSuppressionEventRepository,
)
from vocablens.infrastructure.postgres_notification_policy_registry_repository import (
    PostgresNotificationPolicyRegistryRepository,
)
from vocablens.infrastructure.postgres_notification_policy_audit_repository import (
    PostgresNotificationPolicyAuditRepository,
)
from vocablens.infrastructure.postgres_notification_policy_health_state_repository import (
    PostgresNotificationPolicyHealthStateRepository,
)
from vocablens.infrastructure.postgres_experiment_health_state_repository import (
    PostgresExperimentHealthStateRepository,
)
from vocablens.infrastructure.postgres_monetization_health_state_repository import (
    PostgresMonetizationHealthStateRepository,
)
from vocablens.infrastructure.postgres_lifecycle_health_state_repository import (
    PostgresLifecycleHealthStateRepository,
)
from vocablens.infrastructure.postgres_daily_loop_health_state_repository import (
    PostgresDailyLoopHealthStateRepository,
)
from vocablens.infrastructure.postgres_session_health_state_repository import (
    PostgresSessionHealthStateRepository,
)
from vocablens.infrastructure.postgres_learning_health_state_repository import (
    PostgresLearningHealthStateRepository,
)
from vocablens.infrastructure.postgres_experiment_assignment_repository import (
    PostgresExperimentAssignmentRepository,
)
from vocablens.infrastructure.postgres_experiment_exposure_repository import (
    PostgresExperimentExposureRepository,
)
from vocablens.infrastructure.postgres_experiment_outcome_attribution_repository import (
    PostgresExperimentOutcomeAttributionRepository,
)
from vocablens.infrastructure.postgres_experiment_registry_repository import (
    PostgresExperimentRegistryRepository,
)
from vocablens.infrastructure.postgres_experiment_registry_audit_repository import (
    PostgresExperimentRegistryAuditRepository,
)
from vocablens.infrastructure.postgres_event_repository import PostgresEventRepository
from vocablens.infrastructure.postgres_decision_trace_repository import PostgresDecisionTraceRepository
from vocablens.infrastructure.postgres_learning_session_repository import PostgresLearningSessionRepository
from vocablens.infrastructure.postgres_user_learning_state_repository import PostgresUserLearningStateRepository
from vocablens.infrastructure.postgres_user_engagement_state_repository import PostgresUserEngagementStateRepository
from vocablens.infrastructure.postgres_user_progress_state_repository import PostgresUserProgressStateRepository
from vocablens.infrastructure.postgres_onboarding_flow_state_repository import (
    PostgresOnboardingFlowStateRepository,
)
from vocablens.infrastructure.postgres_user_monetization_state_repository import (
    PostgresUserMonetizationStateRepository,
)
from vocablens.infrastructure.postgres_monetization_offer_event_repository import (
    PostgresMonetizationOfferEventRepository,
)
from vocablens.infrastructure.postgres_daily_mission_repository import (
    PostgresDailyMissionRepository,
)
from vocablens.infrastructure.postgres_reward_chest_repository import (
    PostgresRewardChestRepository,
)
from vocablens.infrastructure.postgres_user_lifecycle_state_repository import (
    PostgresUserLifecycleStateRepository,
)
from vocablens.infrastructure.postgres_lifecycle_transition_repository import (
    PostgresLifecycleTransitionRepository,
)


class UnitOfWork:
    """
    Coordinates a shared AsyncSession and repositories in a single transaction.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self.session: Optional[AsyncSession] = None
        self._committed = False
        self._vocab: Optional[PostgresVocabularyRepository] = None
        self._cache: Optional[PostgresTranslationCacheRepository] = None
        self._conversation: Optional[PostgresConversationRepository] = None
        self._learning_events: Optional[PostgresLearningEventRepository] = None
        self._events: Optional[PostgresEventRepository] = None
        self._decision_traces: Optional[PostgresDecisionTraceRepository] = None
        self._skill_tracking: Optional[PostgresSkillTrackingRepository] = None
        self._users: Optional[PostgresUserRepository] = None
        self._knowledge_graph: Optional[KnowledgeGraphRepository] = None
        self._usage: Optional[PostgresUsageRepository] = None
        self._subscriptions: Optional[PostgresSubscriptionRepository] = None
        self._subscription_events: Optional[PostgresSubscriptionEventRepository] = None
        self._mistakes: Optional[PostgresMistakePatternRepository] = None
        self._profiles: Optional[PostgresUserProfileRepository] = None
        self._notification_deliveries: Optional[PostgresNotificationDeliveryRepository] = None
        self._notification_states: Optional[PostgresUserNotificationStateRepository] = None
        self._notification_suppression_events: Optional[PostgresNotificationSuppressionEventRepository] = None
        self._notification_policy_registries: Optional[PostgresNotificationPolicyRegistryRepository] = None
        self._notification_policy_audits: Optional[PostgresNotificationPolicyAuditRepository] = None
        self._notification_policy_health_states: Optional[PostgresNotificationPolicyHealthStateRepository] = None
        self._experiment_health_states: Optional[PostgresExperimentHealthStateRepository] = None
        self._monetization_health_states: Optional[PostgresMonetizationHealthStateRepository] = None
        self._lifecycle_health_states: Optional[PostgresLifecycleHealthStateRepository] = None
        self._daily_loop_health_states: Optional[PostgresDailyLoopHealthStateRepository] = None
        self._session_health_states: Optional[PostgresSessionHealthStateRepository] = None
        self._learning_health_states: Optional[PostgresLearningHealthStateRepository] = None
        self._experiment_assignments: Optional[PostgresExperimentAssignmentRepository] = None
        self._experiment_exposures: Optional[PostgresExperimentExposureRepository] = None
        self._experiment_outcome_attributions: Optional[PostgresExperimentOutcomeAttributionRepository] = None
        self._experiment_registries: Optional[PostgresExperimentRegistryRepository] = None
        self._experiment_registry_audits: Optional[PostgresExperimentRegistryAuditRepository] = None
        self._learning_sessions: Optional[PostgresLearningSessionRepository] = None
        self._learning_states: Optional[PostgresUserLearningStateRepository] = None
        self._engagement_states: Optional[PostgresUserEngagementStateRepository] = None
        self._progress_states: Optional[PostgresUserProgressStateRepository] = None
        self._onboarding_states: Optional[PostgresOnboardingFlowStateRepository] = None
        self._monetization_states: Optional[PostgresUserMonetizationStateRepository] = None
        self._monetization_offer_events: Optional[PostgresMonetizationOfferEventRepository] = None
        self._daily_missions: Optional[PostgresDailyMissionRepository] = None
        self._reward_chests: Optional[PostgresRewardChestRepository] = None
        self._lifecycle_states: Optional[PostgresUserLifecycleStateRepository] = None
        self._lifecycle_transitions: Optional[PostgresLifecycleTransitionRepository] = None

    async def __aenter__(self):
        self.session = self._session_factory()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if not self.session:
            return
        if exc:
            await self.session.rollback()
        elif not self._committed:
            await self.session.rollback()
        await self.session.close()

    async def commit(self):
        if self.session:
            await self.session.commit()
            self._committed = True

    # Repository accessors (lazy, shared session)
    @property
    def vocab(self) -> PostgresVocabularyRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._vocab is None:
            self._vocab = PostgresVocabularyRepository(self.session)
        return self._vocab

    @property
    def translation_cache(self) -> PostgresTranslationCacheRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._cache is None:
            self._cache = PostgresTranslationCacheRepository(self.session)
        return self._cache

    @property
    def conversation(self) -> PostgresConversationRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._conversation is None:
            self._conversation = PostgresConversationRepository(self.session)
        return self._conversation

    @property
    def learning_events(self) -> PostgresLearningEventRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._learning_events is None:
            self._learning_events = PostgresLearningEventRepository(self.session)
        return self._learning_events

    @property
    def events(self) -> PostgresEventRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._events is None:
            self._events = PostgresEventRepository(self.session)
        return self._events

    @property
    def decision_traces(self) -> PostgresDecisionTraceRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._decision_traces is None:
            self._decision_traces = PostgresDecisionTraceRepository(self.session)
        return self._decision_traces

    @property
    def skill_tracking(self) -> PostgresSkillTrackingRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._skill_tracking is None:
            self._skill_tracking = PostgresSkillTrackingRepository(self.session)
        return self._skill_tracking

    @property
    def users(self) -> PostgresUserRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._users is None:
            self._users = PostgresUserRepository(self.session)
        return self._users

    @property
    def knowledge_graph(self) -> KnowledgeGraphRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._knowledge_graph is None:
            self._knowledge_graph = KnowledgeGraphRepository(self.session)
        return self._knowledge_graph

    @property
    def usage_logs(self) -> PostgresUsageRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._usage is None:
            self._usage = PostgresUsageRepository(self.session)
        return self._usage

    @property
    def subscriptions(self) -> PostgresSubscriptionRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._subscriptions is None:
            self._subscriptions = PostgresSubscriptionRepository(self.session)
        return self._subscriptions

    @property
    def mistake_patterns(self) -> PostgresMistakePatternRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._mistakes is None:
            self._mistakes = PostgresMistakePatternRepository(self.session)
        return self._mistakes

    @property
    def subscription_events(self) -> PostgresSubscriptionEventRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._subscription_events is None:
            self._subscription_events = PostgresSubscriptionEventRepository(self.session)
        return self._subscription_events

    @property
    def profiles(self) -> PostgresUserProfileRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._profiles is None:
            self._profiles = PostgresUserProfileRepository(self.session)
        return self._profiles

    @property
    def notification_deliveries(self) -> PostgresNotificationDeliveryRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._notification_deliveries is None:
            self._notification_deliveries = PostgresNotificationDeliveryRepository(self.session)
        return self._notification_deliveries

    @property
    def notification_states(self) -> PostgresUserNotificationStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._notification_states is None:
            self._notification_states = PostgresUserNotificationStateRepository(self.session)
        return self._notification_states

    @property
    def notification_suppression_events(self) -> PostgresNotificationSuppressionEventRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._notification_suppression_events is None:
            self._notification_suppression_events = PostgresNotificationSuppressionEventRepository(self.session)
        return self._notification_suppression_events

    @property
    def notification_policy_registries(self) -> PostgresNotificationPolicyRegistryRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._notification_policy_registries is None:
            self._notification_policy_registries = PostgresNotificationPolicyRegistryRepository(self.session)
        return self._notification_policy_registries

    @property
    def notification_policy_audits(self) -> PostgresNotificationPolicyAuditRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._notification_policy_audits is None:
            self._notification_policy_audits = PostgresNotificationPolicyAuditRepository(self.session)
        return self._notification_policy_audits

    @property
    def notification_policy_health_states(self) -> PostgresNotificationPolicyHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._notification_policy_health_states is None:
            self._notification_policy_health_states = PostgresNotificationPolicyHealthStateRepository(self.session)
        return self._notification_policy_health_states

    @property
    def experiment_health_states(self) -> PostgresExperimentHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._experiment_health_states is None:
            self._experiment_health_states = PostgresExperimentHealthStateRepository(self.session)
        return self._experiment_health_states

    @property
    def monetization_health_states(self) -> PostgresMonetizationHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._monetization_health_states is None:
            self._monetization_health_states = PostgresMonetizationHealthStateRepository(self.session)
        return self._monetization_health_states

    @property
    def lifecycle_health_states(self) -> PostgresLifecycleHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._lifecycle_health_states is None:
            self._lifecycle_health_states = PostgresLifecycleHealthStateRepository(self.session)
        return self._lifecycle_health_states

    @property
    def daily_loop_health_states(self) -> PostgresDailyLoopHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._daily_loop_health_states is None:
            self._daily_loop_health_states = PostgresDailyLoopHealthStateRepository(self.session)
        return self._daily_loop_health_states

    @property
    def session_health_states(self) -> PostgresSessionHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._session_health_states is None:
            self._session_health_states = PostgresSessionHealthStateRepository(self.session)
        return self._session_health_states

    @property
    def learning_health_states(self) -> PostgresLearningHealthStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._learning_health_states is None:
            self._learning_health_states = PostgresLearningHealthStateRepository(self.session)
        return self._learning_health_states

    @property
    def experiment_assignments(self) -> PostgresExperimentAssignmentRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._experiment_assignments is None:
            self._experiment_assignments = PostgresExperimentAssignmentRepository(self.session)
        return self._experiment_assignments

    @property
    def experiment_exposures(self) -> PostgresExperimentExposureRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._experiment_exposures is None:
            self._experiment_exposures = PostgresExperimentExposureRepository(self.session)
        return self._experiment_exposures

    @property
    def experiment_outcome_attributions(self) -> PostgresExperimentOutcomeAttributionRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._experiment_outcome_attributions is None:
            self._experiment_outcome_attributions = PostgresExperimentOutcomeAttributionRepository(self.session)
        return self._experiment_outcome_attributions

    @property
    def experiment_registries(self) -> PostgresExperimentRegistryRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._experiment_registries is None:
            self._experiment_registries = PostgresExperimentRegistryRepository(self.session)
        return self._experiment_registries

    @property
    def experiment_registry_audits(self) -> PostgresExperimentRegistryAuditRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._experiment_registry_audits is None:
            self._experiment_registry_audits = PostgresExperimentRegistryAuditRepository(self.session)
        return self._experiment_registry_audits

    @property
    def learning_sessions(self) -> PostgresLearningSessionRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._learning_sessions is None:
            self._learning_sessions = PostgresLearningSessionRepository(self.session)
        return self._learning_sessions

    @property
    def learning_states(self) -> PostgresUserLearningStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._learning_states is None:
            self._learning_states = PostgresUserLearningStateRepository(self.session)
        return self._learning_states

    @property
    def engagement_states(self) -> PostgresUserEngagementStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._engagement_states is None:
            self._engagement_states = PostgresUserEngagementStateRepository(self.session)
        return self._engagement_states

    @property
    def progress_states(self) -> PostgresUserProgressStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._progress_states is None:
            self._progress_states = PostgresUserProgressStateRepository(self.session)
        return self._progress_states

    @property
    def onboarding_states(self) -> PostgresOnboardingFlowStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._onboarding_states is None:
            self._onboarding_states = PostgresOnboardingFlowStateRepository(self.session)
        return self._onboarding_states

    @property
    def monetization_states(self) -> PostgresUserMonetizationStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._monetization_states is None:
            self._monetization_states = PostgresUserMonetizationStateRepository(self.session)
        return self._monetization_states

    @property
    def monetization_offer_events(self) -> PostgresMonetizationOfferEventRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._monetization_offer_events is None:
            self._monetization_offer_events = PostgresMonetizationOfferEventRepository(self.session)
        return self._monetization_offer_events

    @property
    def daily_missions(self) -> PostgresDailyMissionRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._daily_missions is None:
            self._daily_missions = PostgresDailyMissionRepository(self.session)
        return self._daily_missions

    @property
    def reward_chests(self) -> PostgresRewardChestRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._reward_chests is None:
            self._reward_chests = PostgresRewardChestRepository(self.session)
        return self._reward_chests

    @property
    def lifecycle_states(self) -> PostgresUserLifecycleStateRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._lifecycle_states is None:
            self._lifecycle_states = PostgresUserLifecycleStateRepository(self.session)
        return self._lifecycle_states

    @property
    def lifecycle_transitions(self) -> PostgresLifecycleTransitionRepository:
        if not self.session:
            raise RuntimeError("UnitOfWork session not initialized")
        if self._lifecycle_transitions is None:
            self._lifecycle_transitions = PostgresLifecycleTransitionRepository(self.session)
        return self._lifecycle_transitions


def UnitOfWorkFactory(session_factory: async_sessionmaker[AsyncSession]):
    def _factory():
        return UnitOfWork(session_factory)

    return _factory
