from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.learning_policy import LearningRecommendationPolicy, LearningSnapshot
from vocablens.services.learning_session_updater import LearningSessionUpdater
from vocablens.services.learning_state_projector import LearningStateProjector
from vocablens.services.personalization_service import PersonalizationAdaptation, PersonalizationService
from vocablens.services.retention_engine import RetentionAssessment, RetentionEngine
from vocablens.services.spaced_repetition_service import SpacedRepetitionService
from vocablens.services.subscription_service import SubscriptionService

NextAction = Literal["review_word", "learn_new_word", "practice_grammar", "conversation_drill"]
@dataclass
class LearningRecommendation:
    action: NextAction
    target: str | None
    reason: str
    lesson_difficulty: str = "medium"
    review_frequency_multiplier: float = 1.0
    content_type: str = "mixed"
    review_priority: float = 0.0
    skill_focus: str | None = None
    due_items_count: int = 0
    goal_label: str | None = None
    review_window_minutes: int | None = None


@dataclass(frozen=True)
class ReviewedKnowledge:
    item_id: int
    quality: int
    response_accuracy: float | None = None
    mistake_frequency: int = 0
    difficulty_score: float | None = None


@dataclass(frozen=True)
class SessionResult:
    reviewed_items: list[ReviewedKnowledge] = field(default_factory=list)
    learned_item_ids: list[int] = field(default_factory=list)
    skill_scores: dict[str, float] = field(default_factory=dict)
    mistakes: list[dict[str, str]] = field(default_factory=list)
    weak_areas: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeUpdateSummary:
    reviewed_count: int
    learned_count: int
    weak_areas: list[str]
    updated_item_ids: list[int]


class LearningEngine:
    """
    Decides the next best learning action using vocabulary mastery, skills,
    recent learning events, and the knowledge graph.
    """

    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        retention_engine: RetentionEngine | None = None,
        personalization: PersonalizationService | None = None,
        subscription_service: SubscriptionService | None = None,
        experiment_service: ExperimentService | None = None,
        event_service: EventService | None = None,
        global_decision_engine: GlobalDecisionEngine | None = None,
    ):
        self._uow_factory = uow_factory
        self._retention = retention_engine or RetentionEngine()
        self._personalization = personalization
        self._subscription_service = subscription_service
        self._experiments = experiment_service
        self._event_service = event_service
        self._global_decision = global_decision_engine
        self._scheduler = SpacedRepetitionService()
        self._policy = LearningRecommendationPolicy(self._scheduler)
        self._state_projector = LearningStateProjector()
        self._session_updater = LearningSessionUpdater(
            scheduler=self._scheduler,
            state_projector=self._state_projector,
        )

    async def recommend(self, user_id: int) -> LearningRecommendation:
        return await self.get_next_lesson(user_id)

    async def get_next_lesson(self, user_id: int) -> LearningRecommendation:
        if self._global_decision:
            return await self._recommend_from_global_decision(user_id)
        retention = await self._get_retention_assessment(user_id)
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            due_items = await uow.vocab.list_due(user_id)
            total_vocab = await uow.vocab.list_all(user_id, limit=200, offset=0)
            skills = dict(learning_state.skills or {})
            if not skills:
                skills = await uow.skill_tracking.latest_scores(user_id)
                learning_state.skills = dict(skills)
            kg = await uow.knowledge_graph.list_clusters(user_id)
            weak_clusters = await uow.knowledge_graph.get_weak_clusters(user_id) if not learning_state.weak_areas else [
                {"cluster": area, "words": []} for area in learning_state.weak_areas[:3]
            ]
            sparse_cluster = None
            if kg:
                populated = {
                    cluster: cluster_data.get("words", [])
                    for cluster, cluster_data in kg.items()
                    if cluster_data.get("words")
                }
                sparse_cluster = min(populated, key=lambda k: len(populated[k])) if populated else None
            patterns = await uow.mistake_patterns.top_patterns(user_id, limit=3)
            repeated_patterns = await uow.mistake_patterns.repeated_patterns(user_id, threshold=2, limit=3)
            yesterday = utc_now() - timedelta(hours=24)
            recent_events = await uow.learning_events.list_since(user_id, since=yesterday)
            profile = await uow.profiles.get_or_create(user_id)
            await uow.commit()

        adaptation = await self._get_adaptation(user_id, profile)
        feature_level = await self._personalization_level(user_id)
        learning_variant = await self._learning_variant(user_id)
        snapshot = LearningSnapshot(
            learning_state=learning_state,
            due_items=due_items,
            total_vocab=total_vocab,
            patterns=patterns,
            repeated_patterns=repeated_patterns,
            weak_clusters=weak_clusters,
            sparse_cluster=sparse_cluster,
            recent_events=recent_events,
            profile=profile,
            retention=retention,
            feature_level=feature_level,
            learning_variant=learning_variant,
            adaptation=adaptation,
        )
        recommendation = self._policy.choose(snapshot, LearningRecommendation)
        return await self._finalize_recommendation(user_id, recommendation, adaptation)

    async def update_knowledge(self, user_id: int, session_result: SessionResult) -> KnowledgeUpdateSummary:
        summary = await self.apply_session_result(
            user_id,
            session_result,
            source="learning_engine",
        )
        if self._event_service:
            await self._event_service.track_event(
                user_id=user_id,
                event_type="knowledge_updated",
                payload={
                    "source": "learning_engine",
                    "reviewed_count": summary.reviewed_count,
                    "learned_count": summary.learned_count,
                    "updated_item_ids": summary.updated_item_ids,
                    "weak_areas": list(session_result.weak_areas),
                },
            )
        return summary

    async def apply_session_result(
        self,
        user_id: int,
        session_result: SessionResult,
        *,
        source: str,
        uow=None,
        reference_id: str | None = None,
    ) -> KnowledgeUpdateSummary:
        if uow is None:
            async with self._uow_factory() as managed_uow:
                summary = await self._apply_session_result(
                    managed_uow,
                    user_id,
                    session_result,
                    source=source,
                    reference_id=reference_id,
                )
                await managed_uow.commit()
                return summary
        return await self._apply_session_result(
            uow,
            user_id,
            session_result,
            source=source,
            reference_id=reference_id,
        )

    async def _apply_session_result(
        self,
        uow,
        user_id: int,
        session_result: SessionResult,
        *,
        source: str,
        reference_id: str | None,
    ) -> KnowledgeUpdateSummary:
        profile = await uow.profiles.get_or_create(user_id)
        applied = await self._session_updater.apply(
            uow=uow,
            user_id=user_id,
            session_result=session_result,
            review_multiplier=self._review_multiplier(profile),
        )
        await uow.events.record(
            user_id=user_id,
            event_type="knowledge_updated",
            payload={
                "source": source,
                "reviewed_count": applied.reviewed_count,
                "learned_count": applied.learned_count,
                "updated_item_ids": applied.updated_item_ids,
                "weak_areas": list(session_result.weak_areas),
            },
        )
        await uow.decision_traces.create(
            user_id=user_id,
            trace_type="knowledge_update",
            source=source,
            reference_id=reference_id,
            policy_version="v1",
            inputs={
                "reviewed_item_count": len(session_result.reviewed_items),
                "learned_item_count": len(session_result.learned_item_ids),
                "skill_scores": dict(session_result.skill_scores),
                "mistakes": list(session_result.mistakes),
                "weak_areas": list(session_result.weak_areas),
            },
            outputs={
                "reviewed_count": applied.reviewed_count,
                "learned_count": applied.learned_count,
                "updated_item_ids": applied.updated_item_ids,
                "interaction_stats": dict(applied.interaction_stats),
            },
            reason="Applied session result to canonical learning, engagement, and progress state.",
        )

        return KnowledgeUpdateSummary(
            reviewed_count=applied.reviewed_count,
            learned_count=applied.learned_count,
            weak_areas=list(session_result.weak_areas),
            updated_item_ids=applied.updated_item_ids,
        )

    async def _get_adaptation(self, user_id: int, profile) -> PersonalizationAdaptation:
        if self._personalization:
            return await self._personalization.get_adaptation(user_id)
        difficulty = profile.difficulty_preference if profile else "medium"
        retention_rate = profile.retention_rate if profile else 0.8
        content_type = profile.content_preference if profile else "mixed"
        return PersonalizationAdaptation(
            lesson_difficulty=difficulty,
            review_frequency_multiplier=1.0 if retention_rate >= 0.75 else 0.8,
            content_type=content_type,
        )

    async def _get_retention_assessment(self, user_id: int) -> RetentionAssessment | None:
        if not self._retention or not hasattr(self._retention, "assess_user"):
            return None
        return await self._retention.assess_user(user_id)

    async def _personalization_level(self, user_id: int) -> str:
        if not self._subscription_service:
            return "premium"
        features = await self._subscription_service.get_features(user_id)
        await self._subscription_service.record_feature_gate(
            user_id=user_id,
            feature_name="personalization_level",
            allowed=True,
            current_tier=features.tier,
            required_tier=features.tier,
        )
        return features.personalization_level

    async def _learning_variant(self, user_id: int) -> str | None:
        if not self._experiments or not self._experiments.has_experiment("learning_strategy"):
            return None
        return await self._experiments.assign(user_id, "learning_strategy")

    async def _finalize_recommendation(
        self,
        user_id: int,
        recommendation: LearningRecommendation,
        adaptation: PersonalizationAdaptation,
    ) -> LearningRecommendation:
        decorated = self._decorate(recommendation, adaptation)
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="lesson_recommendation",
                source="learning_engine",
                reference_id=None,
                policy_version="v1",
                inputs={
                    "action": decorated.action,
                    "target": decorated.target,
                    "difficulty": decorated.lesson_difficulty,
                    "content_type": decorated.content_type,
                    "skill_focus": decorated.skill_focus,
                    "due_items_count": decorated.due_items_count,
                },
                outputs={
                    "action": decorated.action,
                    "target": decorated.target,
                    "goal_label": decorated.goal_label,
                    "review_window_minutes": decorated.review_window_minutes,
                    "review_priority": decorated.review_priority,
                },
                reason=decorated.reason,
            )
            await uow.commit()

        if self._event_service:
            await self._event_service.track_event(
                user_id=user_id,
                event_type="lesson_recommended",
                payload={
                    "source": "learning_engine",
                    "action": decorated.action,
                    "target": decorated.target,
                    "difficulty": decorated.lesson_difficulty,
                    "content_type": decorated.content_type,
                    "reason": decorated.reason,
                    "review_priority": decorated.review_priority,
                    "skill_focus": decorated.skill_focus,
                    "due_items_count": decorated.due_items_count,
                    "goal_label": decorated.goal_label,
                    "review_window_minutes": decorated.review_window_minutes,
                },
            )
        return decorated

    async def _recommend_from_global_decision(self, user_id: int) -> LearningRecommendation:
        decision = await self._global_decision.decide(user_id)
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            due_items = await uow.vocab.list_due(user_id)
            weak_clusters = await uow.knowledge_graph.get_weak_clusters(user_id)
            repeated_patterns = await uow.mistake_patterns.repeated_patterns(user_id, threshold=2, limit=3)
            profile = await uow.profiles.get_or_create(user_id)
            await uow.commit()
        adaptation = await self._get_adaptation(user_id, profile)
        adaptation = PersonalizationAdaptation(
            lesson_difficulty=decision.difficulty_level,
            review_frequency_multiplier=adaptation.review_frequency_multiplier,
            content_type=adaptation.content_type,
        )

        if decision.primary_action == "review":
            prioritized_due = self._policy.prioritize_due_items(due_items, getattr(profile, "retention_rate", 0.8), [])
            recommendation = LearningRecommendation(
                "review_word",
                getattr(prioritized_due[0], "source_text", None) if prioritized_due else None,
                decision.reason,
                due_items_count=len(prioritized_due),
                review_priority=1.0 if prioritized_due else 0.0,
            )
        elif decision.primary_action == "conversation":
            target = getattr(repeated_patterns[0], "pattern", None) if repeated_patterns else None
            recommendation = LearningRecommendation(
                "conversation_drill",
                target,
                decision.reason,
                skill_focus="fluency",
            )
        else:
            target = (learning_state.weak_areas[0] if getattr(learning_state, "weak_areas", None) else None) or (
                weak_clusters[0]["cluster"] if weak_clusters else "general"
            )
            recommendation = LearningRecommendation(
                "learn_new_word",
                target,
                decision.reason,
                skill_focus="vocabulary",
            )
        return await self._finalize_recommendation(user_id, recommendation, adaptation)

    def _decorate(self, recommendation: LearningRecommendation, adaptation: PersonalizationAdaptation):
        recommendation.lesson_difficulty = adaptation.lesson_difficulty
        recommendation.review_frequency_multiplier = adaptation.review_frequency_multiplier
        recommendation.content_type = adaptation.content_type
        recommendation.goal_label = recommendation.goal_label or self._goal_label(recommendation)
        recommendation.review_window_minutes = recommendation.review_window_minutes or self._review_window_minutes(recommendation)
        return recommendation

    def _goal_label(self, recommendation: LearningRecommendation) -> str:
        if recommendation.action == "review_word":
            return "Bring a due word back into active memory"
        if recommendation.action == "practice_grammar":
            return "Fix one grammar pattern cleanly"
        if recommendation.action == "conversation_drill":
            return "Say one idea clearly without drift"
        return "Add one useful word without losing review momentum"

    def _review_window_minutes(self, recommendation: LearningRecommendation) -> int:
        if recommendation.action == "review_word":
            return 5
        if recommendation.action == "practice_grammar":
            return 15
        if recommendation.action == "conversation_drill":
            return 20
        return 30

    def _review_multiplier(self, profile) -> float:
        preference = (getattr(profile, "difficulty_preference", "medium") or "medium").lower()
        if preference == "easy":
            return 0.9
        if preference == "hard":
            return 1.1
        return 1.0
