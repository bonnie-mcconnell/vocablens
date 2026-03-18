from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.personalization_service import PersonalizationAdaptation, PersonalizationService
from vocablens.services.retention_engine import RetentionAssessment, RetentionEngine

NextAction = Literal["review_word", "learn_new_word", "practice_grammar", "conversation_drill"]


@dataclass
class LearningRecommendation:
    action: NextAction
    target: str | None
    reason: str
    lesson_difficulty: str = "medium"
    review_frequency_multiplier: float = 1.0
    content_type: str = "mixed"


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
    ):
        self._uow_factory = uow_factory
        self._retention = retention_engine or RetentionEngine()
        self._personalization = personalization

    async def recommend(self, user_id: int) -> LearningRecommendation:
        retention = await self._get_retention_assessment(user_id)
        async with self._uow_factory() as uow:
            due_items = await uow.vocab.list_due(user_id)
            total_vocab = await uow.vocab.list_all(user_id, limit=200, offset=0)
            skills = await uow.skill_tracking.latest_scores(user_id)
            grammar_score = skills.get("grammar", 0.5)
            vocab_score = skills.get("vocabulary", 0.5)
            fluency_score = skills.get("fluency", 0.5)
            kg = await uow.knowledge_graph.list_clusters()
            sparse_cluster = None
            if kg:
                populated = {cluster: words for cluster, words in kg.items() if words}
                sparse_cluster = min(populated, key=lambda k: len(populated[k])) if populated else None
            patterns = await uow.mistake_patterns.top_patterns(user_id, limit=3)
            repeated_patterns = await uow.mistake_patterns.repeated_patterns(user_id, threshold=2, limit=3)
            yesterday = utc_now() - timedelta(hours=24)
            recent_events = await uow.learning_events.list_since(user_id, since=yesterday)
            profile = await uow.profiles.get_or_create(user_id)
            await uow.commit()

        adaptation = await self._get_adaptation(user_id, profile)
        difficulty_pref = (profile.difficulty_preference if profile else "medium").lower()
        retention_rate = profile.retention_rate if profile else 0.8

        grammar_thresh = 0.45 if difficulty_pref != "easy" else 0.55
        vocab_thresh = 0.5 if difficulty_pref != "easy" else 0.6
        due_pressure = self._review_pressure(
            due_items,
            retention_rate,
            adaptation.review_frequency_multiplier,
        )
        review_vs_new_bias = self._review_vs_new_bias(total_vocab, recent_events, retention_rate)

        if retention and retention.state in {"at-risk", "churned"} and due_items:
            return self._decorate(
                LearningRecommendation(
                    "review_word",
                    due_items[0].source_text,
                    f"Retention state is {retention.state}; bring back due material first",
                ),
                adaptation,
            )

        if retention and retention.state in {"at-risk", "churned"} and repeated_patterns:
            return self._decorate(
                LearningRecommendation(
                    "conversation_drill",
                    repeated_patterns[0].pattern,
                    f"Retention state is {retention.state}; use a quick targeted drill",
                ),
                adaptation,
            )

        if due_items and (due_pressure >= 0.4 or review_vs_new_bias >= 0.5):
            reason = f"{len(due_items)} items due with retention pressure {due_pressure:.2f}"
            return self._decorate(
                LearningRecommendation("review_word", due_items[0].source_text, reason),
                adaptation,
            )

        if grammar_score < grammar_thresh or any(p.category == "grammar" for p in (patterns or [])):
            return self._decorate(
                LearningRecommendation("practice_grammar", "grammar", "Grammar skill below threshold"),
                adaptation,
            )

        if (
            adaptation.content_type == "vocab"
            or vocab_score < vocab_thresh
            or sparse_cluster
            or any(p.category == "vocabulary" for p in (patterns or []))
        ):
            target = sparse_cluster or "general"
            return self._decorate(
                LearningRecommendation("learn_new_word", target, "Vocabulary coverage low in cluster"),
                adaptation,
            )

        if repeated_patterns:
            top = repeated_patterns[0]
            return self._decorate(
                LearningRecommendation("conversation_drill", top.pattern, "Address repeated errors"),
                adaptation,
            )

        if adaptation.content_type == "conversation" or fluency_score < 0.6:
            return self._decorate(
                LearningRecommendation("conversation_drill", None, "Build fluency through guided practice"),
                adaptation,
            )

        return self._decorate(
            LearningRecommendation("learn_new_word", sparse_cluster or "general", "Balanced progression into new material"),
            adaptation,
        )

    def _review_pressure(self, due_items, retention_rate: float, frequency_multiplier: float) -> float:
        if not due_items:
            return 0.0
        now = utc_now()
        overdue_count = 0
        max_decay = 0.0
        for item in due_items:
            if not item.next_review_due:
                continue
            overdue_days = max(0.0, (now - item.next_review_due).total_seconds() / 86400)
            if overdue_days > 0:
                overdue_count += 1
            max_decay = max(max_decay, min(1.0, overdue_days / max(1, item.interval or 1)))
        base_pressure = min(1.0, len(due_items) / max(6, 10 * frequency_multiplier))
        decay_pressure = min(1.0, (max_decay / max(0.6, frequency_multiplier)) * (1.2 - retention_rate))
        overdue_pressure = min(1.0, overdue_count / max(1, len(due_items)))
        return max(base_pressure, decay_pressure, overdue_pressure)

    def _review_vs_new_bias(self, total_vocab, recent_events, retention_rate: float) -> float:
        total_count = len(total_vocab)
        recent_new = sum(1 for event in recent_events if event.event_type == "word_learned")
        recent_reviews = sum(1 for event in recent_events if event.event_type == "word_reviewed")
        if total_count < 20:
            return 0.25
        if recent_new > recent_reviews and retention_rate < 0.75:
            return 0.7
        if recent_reviews > recent_new:
            return 0.35
        return 0.5

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

    def _decorate(self, recommendation: LearningRecommendation, adaptation: PersonalizationAdaptation):
        recommendation.lesson_difficulty = adaptation.lesson_difficulty
        recommendation.review_frequency_multiplier = adaptation.review_frequency_multiplier
        recommendation.content_type = adaptation.content_type
        return recommendation
