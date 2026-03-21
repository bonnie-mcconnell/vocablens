import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.personalization_service import PersonalizationAdaptation, PersonalizationService
from vocablens.services.retention_engine import RetentionAssessment, RetentionEngine
from vocablens.services.spaced_repetition_service import SpacedRepetitionService
from vocablens.services.subscription_service import SubscriptionService

NextAction = Literal["review_word", "learn_new_word", "practice_grammar", "conversation_drill"]
XP_PER_LEVEL = 250
PROGRESS_MILESTONES: tuple[int, ...] = (2, 3, 5, 10)


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
            grammar_score = skills.get("grammar", 0.5)
            vocab_score = skills.get("vocabulary", 0.5)
            fluency_score = skills.get("fluency", 0.5)
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
        difficulty_pref = (profile.difficulty_preference if profile else "medium").lower()
        retention_rate = profile.retention_rate if profile else 0.8

        grammar_thresh = 0.45 if difficulty_pref != "easy" else 0.55
        vocab_thresh = 0.5 if difficulty_pref != "easy" else 0.6
        due_pressure = self._review_pressure(
            due_items,
            retention_rate,
            adaptation.review_frequency_multiplier,
            patterns,
        )
        review_vs_new_bias = self._review_vs_new_bias(total_vocab, recent_events, retention_rate)
        prioritized_due = self._prioritize_due_items(due_items, retention_rate, patterns)
        weak_areas = list(learning_state.weak_areas or [])
        if learning_variant == "review_heavy":
            review_vs_new_bias = max(review_vs_new_bias, 0.7)
        if learning_variant == "vocab_focus":
            adaptation.content_type = "vocab"

        if retention and retention.state in {"at-risk", "churned"} and prioritized_due:
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "review_word",
                    prioritized_due[0].source_text,
                    f"Retention state is {retention.state}; bring back due material first",
                    review_priority=due_pressure,
                    due_items_count=len(prioritized_due),
                ),
                adaptation,
            )

        if retention and retention.state in {"at-risk", "churned"} and repeated_patterns:
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "conversation_drill",
                    repeated_patterns[0].pattern,
                    f"Retention state is {retention.state}; use a quick targeted drill",
                    skill_focus="fluency",
                ),
                adaptation,
            )

        if prioritized_due and (due_pressure >= 0.4 or review_vs_new_bias >= 0.5):
            top_due = prioritized_due[0]
            reason = (
                f"{len(prioritized_due)} items due with retention pressure {due_pressure:.2f}; "
                f"'{top_due.source_text}' has the highest decay"
            )
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "review_word",
                    top_due.source_text,
                    reason,
                    review_priority=self._item_review_priority(top_due, retention_rate, patterns),
                    due_items_count=len(prioritized_due),
                ),
                adaptation,
            )

        if grammar_score < grammar_thresh or "grammar" in weak_areas or any(p.category == "grammar" for p in (patterns or [])):
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "practice_grammar",
                    "grammar",
                    "Grammar skill below threshold",
                    skill_focus="grammar",
                ),
                adaptation,
            )

        if (
            adaptation.content_type == "vocab"
            or vocab_score < vocab_thresh
            or (feature_level != "basic" and weak_areas)
            or (feature_level != "basic" and weak_clusters)
            or sparse_cluster
            or any(p.category == "vocabulary" for p in (patterns or []))
        ):
            target = None
            reason = "Vocabulary coverage low in cluster"
            if feature_level != "basic" and weak_areas:
                target = weak_areas[0]
                reason = f"Canonical learning state marks '{target}' as weak and due for reinforcement"
            elif feature_level != "basic" and weak_clusters:
                target = weak_clusters[0]["cluster"]
                related = ", ".join(weak_clusters[0].get("words", [])[:3])
                reason = f"Weak cluster '{target}' should be reinforced with related words: {related or 'general set'}"
            elif sparse_cluster:
                target = sparse_cluster
            else:
                target = "general"
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "learn_new_word",
                    target,
                    reason,
                    skill_focus="vocabulary",
                ),
                adaptation,
            )

        if repeated_patterns:
            top = repeated_patterns[0]
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "conversation_drill",
                    top.pattern,
                    "Address repeated errors",
                    skill_focus="fluency",
                ),
                adaptation,
            )

        if learning_variant == "conversation_focus" and fluency_score < 0.75:
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "conversation_drill",
                    None,
                    "Conversation experiment variant prioritizes fluency practice",
                    skill_focus="fluency",
                ),
                adaptation,
            )

        if adaptation.content_type == "conversation" or fluency_score < 0.6:
            return await self._finalize_recommendation(
                user_id,
                LearningRecommendation(
                    "conversation_drill",
                    None,
                    "Build fluency through guided practice",
                    skill_focus="fluency",
                ),
                adaptation,
            )

        return await self._finalize_recommendation(
            user_id,
            LearningRecommendation(
                "learn_new_word",
                sparse_cluster or "general",
                "Balanced progression into new material",
                skill_focus="vocabulary",
            ),
            adaptation,
        )

    async def update_knowledge(self, user_id: int, session_result: SessionResult) -> KnowledgeUpdateSummary:
        updated_item_ids: list[int] = []
        reviewed_count = 0
        learned_count = 0
        now = utc_now()

        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            retention_rate = getattr(profile, "retention_rate", 0.8)
            review_multiplier = self._review_multiplier(profile)

            for review in session_result.reviewed_items:
                item = await uow.vocab.get(user_id, review.item_id)
                if not item:
                    continue
                accuracy = max(0.0, min(1.0, review.response_accuracy if review.response_accuracy is not None else review.quality / 5.0))
                difficulty_score = review.difficulty_score
                if difficulty_score is None:
                    difficulty_score = min(1.0, max(0.0, len(item.source_text or "") / 12.0))
                previous_reviews = int(getattr(item, "review_count", 0) or 0)
                previous_success = float(getattr(item, "success_rate", 0.0) or 0.0)

                updated = self._scheduler.review(
                    item,
                    review.quality,
                    retention_rate=retention_rate,
                    mistake_frequency=review.mistake_frequency,
                    difficulty_score=difficulty_score,
                    review_frequency_multiplier=review_multiplier,
                )
                updated.last_seen_at = now
                updated.success_rate = self._rolling_success_rate(previous_success, previous_reviews, accuracy)
                updated.decay_score = self._scheduler.decay_score(
                    updated,
                    retention_rate=retention_rate,
                    mistake_frequency=review.mistake_frequency,
                    difficulty_score=difficulty_score,
                    as_of=now,
                )
                await uow.vocab.update(updated)
                await uow.learning_events.record(
                    user_id,
                    "word_reviewed",
                    json.dumps(
                        {
                            "item_id": updated.id,
                            "quality": review.quality,
                            "response_accuracy": accuracy,
                            "success_rate": updated.success_rate,
                            "decay_score": updated.decay_score,
                            "next_review_due": updated.next_review_due.isoformat() if updated.next_review_due else None,
                        }
                    ),
                )
                updated_item_ids.append(updated.id)
                reviewed_count += 1

            for item_id in session_result.learned_item_ids:
                item = await uow.vocab.get(user_id, item_id)
                if not item:
                    continue
                item.last_seen_at = now
                if not getattr(item, "success_rate", None):
                    item.success_rate = 0.6
                item.decay_score = self._scheduler.decay_score(
                    item,
                    retention_rate=retention_rate,
                    mistake_frequency=0,
                    difficulty_score=min(1.0, max(0.0, len(item.source_text or "") / 12.0)),
                    as_of=now,
                )
                await uow.vocab.update(item)
                updated_item_ids.append(item.id)
                learned_count += 1

            for skill, score in session_result.skill_scores.items():
                await uow.skill_tracking.record(user_id, skill, max(0.0, min(1.0, float(score))))
                await uow.learning_events.record(
                    user_id,
                    "skill_update",
                    json.dumps({skill: max(0.0, min(1.0, float(score)))}),
                )

            for mistake in session_result.mistakes:
                category = (mistake.get("category") or "general").strip().lower()
                pattern = (mistake.get("pattern") or "").strip()
                if not pattern:
                    continue
                await uow.mistake_patterns.record(user_id, category, pattern)

            total_vocab = await uow.vocab.list_all(user_id, limit=500, offset=0)
            current_skills = dict(learning_state.skills or {})
            for skill, score in session_result.skill_scores.items():
                current_skills[skill] = max(0.0, min(1.0, float(score)))
            weak_areas = self._canonical_weak_areas(
                session_result=session_result,
                current_skills=current_skills,
                total_vocab=total_vocab,
            )
            mastery_percent = self._mastery_percent(total_vocab)
            accuracy_rate = self._canonical_accuracy_rate(
                existing=float(getattr(learning_state, "accuracy_rate", 0.0) or 0.0),
                session_result=session_result,
            )
            response_speed_seconds = self._canonical_response_speed(
                existing=float(getattr(learning_state, "response_speed_seconds", 0.0) or 0.0),
                session_result=session_result,
            )
            await uow.learning_states.update(
                user_id,
                skills=current_skills,
                weak_areas=weak_areas,
                mastery_percent=mastery_percent,
                accuracy_rate=accuracy_rate,
                response_speed_seconds=response_speed_seconds,
            )

            total_sessions = int(engagement_state.total_sessions or 0) + 1
            sessions_last_3_days = self._sessions_last_3_days(engagement_state, now)
            current_streak, longest_streak = self._streaks_from_profile_and_state(profile, engagement_state, now)
            momentum_score = self._canonical_momentum_score(
                sessions_last_3_days=sessions_last_3_days,
                reviewed_count=reviewed_count,
                learned_count=learned_count,
            )
            await uow.engagement_states.update(
                user_id,
                current_streak=current_streak,
                longest_streak=longest_streak,
                momentum_score=momentum_score,
                total_sessions=total_sessions,
                sessions_last_3_days=sessions_last_3_days,
                last_session_at=now,
            )

            xp = int(progress_state.xp or 0) + self._xp_gain(reviewed_count, learned_count, session_result.skill_scores)
            level = max(1, (xp // XP_PER_LEVEL) + 1)
            milestones = [milestone for milestone in PROGRESS_MILESTONES if level >= milestone]
            await uow.progress_states.update(
                user_id,
                xp=xp,
                level=level,
                milestones=milestones,
            )

            await uow.commit()

        if self._event_service:
            await self._event_service.track_event(
                user_id=user_id,
                event_type="knowledge_updated",
                payload={
                    "source": "learning_engine",
                    "reviewed_count": reviewed_count,
                    "learned_count": learned_count,
                    "updated_item_ids": updated_item_ids,
                    "weak_areas": list(session_result.weak_areas),
                },
            )

        return KnowledgeUpdateSummary(
            reviewed_count=reviewed_count,
            learned_count=learned_count,
            weak_areas=list(session_result.weak_areas),
            updated_item_ids=updated_item_ids,
        )

    def _review_pressure(self, due_items, retention_rate: float, frequency_multiplier: float, patterns) -> float:
        if not due_items:
            return 0.0
        max_urgency = 0.0
        total_urgency = 0.0
        for item in due_items:
            urgency = self._item_review_priority(item, retention_rate, patterns)
            total_urgency += urgency
            max_urgency = max(max_urgency, urgency)
        average_urgency = total_urgency / max(1, len(due_items))
        due_load = min(1.0, len(due_items) / max(4, int(8 * max(frequency_multiplier, 0.6))))
        return max(max_urgency, average_urgency, due_load)

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

    def _mistake_frequency(self, source_text: str | None, patterns) -> int:
        if not source_text:
            return 0
        frequency = 0
        needle = source_text.lower()
        for pattern in patterns or []:
            if needle in str(getattr(pattern, "pattern", "")).lower():
                frequency += int(getattr(pattern, "count", 1) or 1)
        return frequency

    def _item_review_priority(self, item, retention_rate: float, patterns) -> float:
        difficulty_score = min(1.0, max(0.0, (len(getattr(item, "source_text", "") or "") / 12.0)))
        mistake_frequency = self._mistake_frequency(getattr(item, "source_text", None), patterns)
        stored_decay = float(getattr(item, "decay_score", 0.0) or 0.0)
        dynamic_decay = self._scheduler.decay_score(
            item,
            retention_rate=retention_rate,
            mistake_frequency=mistake_frequency,
            difficulty_score=difficulty_score,
        )
        success_penalty = max(0.0, 0.7 - float(getattr(item, "success_rate", 0.0) or 0.0))
        return max(stored_decay, dynamic_decay) + (success_penalty * 0.4)

    def _prioritize_due_items(self, due_items, retention_rate: float, patterns):
        return sorted(
            due_items,
            key=lambda item: (
                -self._item_review_priority(item, retention_rate, patterns),
                getattr(item, "next_review_due", utc_now()),
            ),
        )

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
            prioritized_due = self._prioritize_due_items(due_items, getattr(profile, "retention_rate", 0.8), [])
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

    def _rolling_success_rate(self, previous_success: float, previous_reviews: int, response_accuracy: float) -> float:
        total = (max(0.0, previous_success) * max(0, previous_reviews)) + response_accuracy
        return round(total / max(1, previous_reviews + 1), 4)

    def _review_multiplier(self, profile) -> float:
        preference = (getattr(profile, "difficulty_preference", "medium") or "medium").lower()
        if preference == "easy":
            return 0.9
        if preference == "hard":
            return 1.1
        return 1.0

    def _canonical_weak_areas(self, *, session_result: SessionResult, current_skills: dict[str, float], total_vocab) -> list[str]:
        weak_areas: list[str] = []
        for area in session_result.weak_areas:
            normalized = str(area).strip().lower()
            if normalized and normalized not in weak_areas:
                weak_areas.append(normalized)
        for mistake in session_result.mistakes:
            category = str(mistake.get("category") or "").strip().lower()
            if category and category not in weak_areas:
                weak_areas.append(category)
        for skill, score in current_skills.items():
            if float(score) < 0.6 and skill not in weak_areas:
                weak_areas.append(skill)
        if self._mastery_percent(total_vocab) < 40.0 and "vocabulary" not in weak_areas:
            weak_areas.append("vocabulary")
        return weak_areas[:5]

    def _mastery_percent(self, total_vocab) -> float:
        total = len(total_vocab or [])
        if total <= 0:
            return 0.0
        mastered = sum(
            1 for item in total_vocab
            if float(getattr(item, "success_rate", 0.0) or 0.0) >= 0.85
            and int(getattr(item, "review_count", 0) or 0) >= 3
            and float(getattr(item, "decay_score", 1.0) or 1.0) <= 0.35
        )
        return round((mastered / total) * 100, 2)

    def _sessions_last_3_days(self, engagement_state, now) -> int:
        last_session_at = getattr(engagement_state, "last_session_at", None)
        previous = int(getattr(engagement_state, "sessions_last_3_days", 0) or 0)
        if last_session_at and (now - last_session_at) <= timedelta(days=3):
            return previous + 1
        return 1

    def _streaks_from_profile_and_state(self, profile, engagement_state, now) -> tuple[int, int]:
        profile_streak = int(getattr(profile, "current_streak", 0) or 0)
        profile_longest = int(getattr(profile, "longest_streak", 0) or 0)
        existing_streak = int(getattr(engagement_state, "current_streak", 0) or 0)
        existing_longest = int(getattr(engagement_state, "longest_streak", 0) or 0)
        last_session_at = getattr(engagement_state, "last_session_at", None)

        derived_streak = max(profile_streak, existing_streak)
        if last_session_at:
            days_since = (now.date() - last_session_at.date()).days
            if days_since == 1:
                derived_streak = max(derived_streak, existing_streak + 1)
            elif days_since > 1:
                derived_streak = max(profile_streak, 1)
        else:
            derived_streak = max(derived_streak, 1)
        longest = max(profile_longest, existing_longest, derived_streak)
        return derived_streak, longest

    def _canonical_momentum_score(self, *, sessions_last_3_days: int, reviewed_count: int, learned_count: int) -> float:
        points = min(3.0, float(sessions_last_3_days))
        points += min(2.0, reviewed_count * 0.5)
        points += min(1.0, learned_count * 0.5)
        return round(min(1.0, points / 6.0), 3)

    def _xp_gain(self, reviewed_count: int, learned_count: int, skill_scores: dict[str, float]) -> int:
        gain = (reviewed_count * 20) + (learned_count * 15)
        gain += min(20, len(skill_scores) * 5)
        return gain

    def _canonical_accuracy_rate(self, *, existing: float, session_result: SessionResult) -> float:
        scores = [
            max(0.0, min(1.0, review.response_accuracy if review.response_accuracy is not None else review.quality / 5.0))
            for review in session_result.reviewed_items
        ]
        if not scores:
            return round(existing, 1)
        session_accuracy = (sum(scores) / len(scores)) * 100
        if existing <= 0:
            return round(session_accuracy, 1)
        return round((existing * 0.7) + (session_accuracy * 0.3), 1)

    def _canonical_response_speed(self, *, existing: float, session_result: SessionResult) -> float:
        if "response_speed_seconds" in session_result.skill_scores:
            return round(float(session_result.skill_scores["response_speed_seconds"]), 1)
        return round(existing, 1)
