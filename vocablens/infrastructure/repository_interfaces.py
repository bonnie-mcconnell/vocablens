from typing import Protocol, List, Optional, Any, Dict
from datetime import datetime

from vocablens.domain.models import (
    DecisionTrace,
    LearningSession,
    LearningSessionAttempt,
    UserEngagementState,
    UserLearningState,
    UserProgressState,
    VocabularyItem,
)
from vocablens.services.report_models import OnboardingFlowState
from vocablens.domain.user import User


class VocabularyRepository(Protocol):
    async def add(self, user_id: int, item: VocabularyItem) -> VocabularyItem: ...
    async def list_all(self, user_id: int, limit: int, offset: int) -> List[VocabularyItem]: ...
    async def list_due(self, user_id: int) -> List[VocabularyItem]: ...
    async def get(self, user_id: int, item_id: int) -> Optional[VocabularyItem]: ...
    async def exists(self, user_id: int, source_text: str, source_lang: str, target_lang: str) -> bool: ...
    async def update(self, item: VocabularyItem) -> VocabularyItem: ...
    async def update_enrichment(
        self,
        item_id: int,
        example_source: str | None,
        example_translation: str | None,
        grammar: str | None,
        cluster: str | None,
    ) -> None: ...


class UserRepository(Protocol):
    async def create(self, email: str, password_hash: str) -> User: ...
    async def get_by_email(self, email: str) -> Optional[User]: ...
    async def get_by_id(self, user_id: int) -> Optional[User]: ...
    async def list_all(self) -> List[User]: ...


class TranslationCacheRepository(Protocol):
    async def get(self, text: str, source_lang: str, target_lang: str) -> Optional[str]: ...
    async def save(self, text: str, source_lang: str, target_lang: str, translation: str) -> None: ...


class ConversationRepository(Protocol):
    async def save_turn(self, user_id: int, role: str, message: str, created_at: datetime | None = None) -> None: ...


class LearningEventRepository(Protocol):
    async def record(self, user_id: int, event_type: str, payload_json: str) -> None: ...


class EventRepository(Protocol):
    async def record(
        self,
        *,
        user_id: int,
        event_type: str,
        payload: Dict[str, Any],
        created_at: datetime | None = None,
    ) -> None: ...
    async def list_by_user(self, user_id: int, limit: int = 1000) -> List[Any]: ...
    async def list_by_type(self, event_type: str, limit: int = 1000) -> List[Any]: ...
    async def list_since(self, since: datetime, event_types: List[str] | None = None, limit: int = 5000) -> List[Any]: ...


class SkillTrackingRepository(Protocol):
    async def record(self, user_id: int, skill: str, score: float, created_at: datetime | None = None) -> None: ...
    async def latest_scores(self, user_id: int) -> Dict[str, float]: ...


class KnowledgeGraphRepository(Protocol):
    async def add_edge(self, source_node: str, target_node: str, relation_type: str, weight: float = 1.0) -> None: ...
    async def list_edges(self) -> List[Dict]: ...


class EmbeddingRepository(Protocol):
    async def store(self, word: str, embedding: List[float]) -> None: ...
    async def get(self, word: str) -> Optional[List[float]]: ...


class ExperimentAssignmentRepository(Protocol):
    async def get(self, user_id: int, experiment_key: str) -> Optional[Any]: ...
    async def list_all(self, experiment_key: str | None = None) -> List[Any]: ...
    async def create(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assigned_at: datetime | None = None,
    ) -> Any: ...


class ExperimentExposureRepository(Protocol):
    async def get(self, user_id: int, experiment_key: str) -> Optional[Any]: ...
    async def list_all(self, experiment_key: str | None = None) -> List[Any]: ...
    async def create(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        exposed_at: datetime | None = None,
    ) -> Any: ...


class ExperimentOutcomeAttributionRepository(Protocol):
    async def get(self, user_id: int, experiment_key: str) -> Optional[Any]: ...
    async def create(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assignment_reason: str,
        attribution_version: str,
        exposed_at: datetime,
        window_end_at: datetime,
    ) -> Any: ...
    async def update(self, user_id: int, experiment_key: str, **kwargs) -> Any: ...
    async def list_all(self, experiment_key: str | None = None) -> List[Any]: ...
    async def list_active_by_user(self, user_id: int, occurred_at: datetime) -> List[Any]: ...


class ExperimentRegistryRepository(Protocol):
    async def get(self, experiment_key: str) -> Optional[Any]: ...
    async def list_all(self) -> List[Any]: ...
    async def upsert(
        self,
        *,
        experiment_key: str,
        status: str,
        rollout_percentage: int,
        holdout_percentage: int,
        is_killed: bool,
        baseline_variant: str,
        description: str | None,
        variants: List[Dict[str, Any]],
        eligibility: Dict[str, Any],
        mutually_exclusive_with: List[str],
        prerequisite_experiments: List[str],
    ) -> Any: ...


class ExperimentRegistryAuditRepository(Protocol):
    async def create(
        self,
        *,
        experiment_key: str,
        action: str,
        changed_by: str,
        change_note: str,
        previous_config: Dict[str, Any],
        new_config: Dict[str, Any],
    ) -> Any: ...
    async def list_by_experiment(self, experiment_key: str, limit: int = 50) -> List[Any]: ...
    async def latest_for_experiment(self, experiment_key: str) -> Optional[Any]: ...


class UserMonetizationStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> Any: ...
    async def update(self, user_id: int, **kwargs) -> Any: ...


class UserNotificationStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> Any: ...
    async def update(self, user_id: int, **kwargs) -> Any: ...


class NotificationSuppressionEventRepository(Protocol):
    async def create(
        self,
        *,
        user_id: int,
        event_type: str,
        source: str,
        reference_id: str | None,
        policy_key: str | None,
        policy_version: str | None,
        lifecycle_stage: str | None,
        suppression_reason: str | None,
        suppressed_until: datetime | None,
        payload: Dict[str, Any],
        created_at: datetime | None = None,
    ) -> Any: ...
    async def list_by_user(self, user_id: int, limit: int = 50) -> List[Any]: ...


class NotificationPolicyRegistryRepository(Protocol):
    async def get(self, policy_key: str) -> Optional[Any]: ...
    async def list_all(self) -> List[Any]: ...
    async def upsert(
        self,
        *,
        policy_key: str,
        status: str,
        is_killed: bool,
        description: str | None,
        policy: Dict[str, Any],
    ) -> Any: ...


class NotificationPolicyAuditRepository(Protocol):
    async def create(
        self,
        *,
        policy_key: str,
        action: str,
        changed_by: str,
        change_note: str,
        previous_config: Dict[str, Any],
        new_config: Dict[str, Any],
    ) -> Any: ...
    async def list_by_policy(self, policy_key: str, limit: int = 50) -> List[Any]: ...
    async def latest_for_policy(self, policy_key: str) -> Optional[Any]: ...


class NotificationDeliveryRepository(Protocol):
    async def create_attempt(
        self,
        *,
        user_id: int,
        category: str,
        provider: str,
        policy_key: str | None,
        policy_version: str | None,
        source_context: str | None,
        reference_id: str | None,
        title: str,
        body: str,
        payload: Dict[str, Any] | None = None,
    ) -> Any: ...
    async def mark_status(self, delivery_id: int, status: str, error_message: str | None = None) -> None: ...
    async def list_recent(self, user_id: int, limit: int = 20) -> List[Any]: ...
    async def list_since(self, user_id: int, since: datetime, limit: int = 100) -> List[Any]: ...
    async def list_by_policy(self, policy_key: str, limit: int = 100) -> List[Any]: ...


class MonetizationOfferEventRepository(Protocol):
    async def record(
        self,
        *,
        user_id: int,
        event_type: str,
        offer_type: str | None,
        paywall_type: str | None,
        strategy: str | None,
        geography: str | None,
        payload: Dict[str, Any],
        created_at: datetime | None = None,
    ) -> Any: ...
    async def list_by_user(self, user_id: int, limit: int = 100) -> List[Any]: ...


class DailyMissionRepository(Protocol):
    async def get_by_user_date(self, user_id: int, mission_date: str) -> Optional[Any]: ...
    async def create(
        self,
        *,
        user_id: int,
        mission_date: str,
        weak_area: str,
        mission_max_sessions: int,
        steps: List[Dict[str, Any]],
        loss_aversion_message: str,
        streak_at_issue: int,
        momentum_score: float,
        notification_preview: Dict[str, Any],
    ) -> Any: ...
    async def mark_completed(self, mission_id: int, *, completed_at: datetime) -> Any: ...


class RewardChestRepository(Protocol):
    async def get_by_mission_id(self, mission_id: int) -> Optional[Any]: ...
    async def create(
        self,
        *,
        user_id: int,
        mission_id: int,
        xp_reward: int,
        badge_hint: str,
        payload: Dict[str, Any],
    ) -> Any: ...
    async def mark_unlocked(self, chest_id: int, *, unlocked_at: datetime) -> Any: ...


class UserLifecycleStateRepository(Protocol):
    async def get(self, user_id: int) -> Any | None: ...
    async def create(
        self,
        *,
        user_id: int,
        current_stage: str,
        previous_stage: str | None,
        current_reasons: List[str],
        entered_at: datetime,
        last_transition_at: datetime,
        last_transition_source: str,
        last_transition_reference_id: str | None,
        transition_count: int,
    ) -> Any: ...
    async def update(self, user_id: int, **kwargs) -> Any: ...


class LifecycleTransitionRepository(Protocol):
    async def create(
        self,
        *,
        user_id: int,
        from_stage: str | None,
        to_stage: str,
        reasons: List[str],
        source: str,
        reference_id: str | None,
        payload: Dict[str, Any],
        created_at: datetime,
    ) -> Any: ...
    async def list_by_user(self, user_id: int, limit: int = 50) -> List[Any]: ...


class UserLearningStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> UserLearningState: ...
    async def update(
        self,
        user_id: int,
        *,
        skills: Dict[str, float] | None = None,
        weak_areas: List[str] | None = None,
        mastery_percent: float | None = None,
        accuracy_rate: float | None = None,
        response_speed_seconds: float | None = None,
    ) -> UserLearningState: ...


class UserEngagementStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> UserEngagementState: ...
    async def update(
        self,
        user_id: int,
        *,
        current_streak: int | None = None,
        longest_streak: int | None = None,
        momentum_score: float | None = None,
        total_sessions: int | None = None,
        sessions_last_3_days: int | None = None,
        last_session_at: datetime | None = None,
        shields_used_this_week: int | None = None,
        daily_mission_completed_at: datetime | None = None,
        interaction_stats: Dict[str, int] | None = None,
    ) -> UserEngagementState: ...


class UserProgressStateRepository(Protocol):
    async def get_or_create(self, user_id: int) -> UserProgressState: ...
    async def update(
        self,
        user_id: int,
        *,
        xp: int | None = None,
        level: int | None = None,
        milestones: List[int] | None = None,
    ) -> UserProgressState: ...


class LearningSessionRepository(Protocol):
    async def create(
        self,
        *,
        session_id: str,
        user_id: int,
        contract_version: str,
        duration_seconds: int,
        mode: str,
        weak_area: str,
        lesson_target: str | None,
        goal_label: str,
        success_criteria: str,
        review_window_minutes: int,
        max_response_words: int,
        session_payload: Dict[str, Any],
        expires_at: datetime,
    ) -> LearningSession: ...
    async def get(self, *, user_id: int, session_id: str) -> Optional[LearningSession]: ...
    async def get_attempt_by_submission(
        self,
        *,
        session_id: str,
        user_id: int,
        submission_id: str,
    ) -> Optional[LearningSessionAttempt]: ...
    async def mark_completed(
        self,
        *,
        user_id: int,
        session_id: str,
        completed_at: datetime,
    ) -> LearningSession: ...
    async def record_attempt(
        self,
        *,
        session_id: str,
        user_id: int,
        submission_id: str,
        learner_response: str,
        response_word_count: int,
        response_char_count: int,
        is_correct: bool,
        improvement_score: float,
        validation_payload: Dict[str, Any],
        feedback_payload: Dict[str, Any],
    ) -> LearningSessionAttempt: ...


class DecisionTraceRepository(Protocol):
    async def create(
        self,
        *,
        user_id: int,
        trace_type: str,
        source: str,
        reference_id: str | None,
        policy_version: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        reason: str | None = None,
    ) -> DecisionTrace: ...


class OnboardingFlowStateRepository(Protocol):
    async def get(self, user_id: int) -> OnboardingFlowState | None: ...
    async def upsert(self, user_id: int, state: OnboardingFlowState) -> OnboardingFlowState: ...
