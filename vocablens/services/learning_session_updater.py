from __future__ import annotations

import json
from dataclasses import dataclass

from vocablens.core.time import utc_now
from vocablens.services.learning_state_projector import LearningStateProjector


@dataclass(frozen=True)
class AppliedLearningSession:
    reviewed_count: int
    learned_count: int
    updated_item_ids: list[int]
    interaction_stats: dict[str, int]


class LearningSessionUpdater:
    def __init__(self, scheduler, state_projector: LearningStateProjector | None = None):
        self._scheduler = scheduler
        self._state_projector = state_projector or LearningStateProjector()

    async def apply(self, *, uow, user_id: int, session_result, review_multiplier: float) -> AppliedLearningSession:
        now = utc_now()
        updated_item_ids: list[int] = []
        reviewed_count = 0
        learned_count = 0

        profile = await uow.profiles.get_or_create(user_id)
        learning_state = await uow.learning_states.get_or_create(user_id)
        engagement_state = await uow.engagement_states.get_or_create(user_id)
        progress_state = await uow.progress_states.get_or_create(user_id)
        retention_rate = getattr(profile, "retention_rate", 0.8)

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
            normalized = max(0.0, min(1.0, float(score)))
            await uow.skill_tracking.record(user_id, skill, normalized)
            await uow.learning_events.record(
                user_id,
                "skill_update",
                json.dumps({skill: normalized}),
            )

        for mistake in session_result.mistakes:
            category = (mistake.get("category") or "general").strip().lower()
            pattern = (mistake.get("pattern") or "").strip()
            if not pattern:
                continue
            await uow.mistake_patterns.record(user_id, category, pattern)

        total_vocab = await uow.vocab.list_all(user_id, limit=500, offset=0)
        projection = self._state_projector.project(
            learning_state=learning_state,
            engagement_state=engagement_state,
            progress_state=progress_state,
            profile=profile,
            session_result=session_result,
            total_vocab=total_vocab,
            reviewed_count=reviewed_count,
            learned_count=learned_count,
            now=now,
        )
        await uow.learning_states.update(
            user_id,
            skills=projection.skills,
            weak_areas=projection.weak_areas,
            mastery_percent=projection.mastery_percent,
            accuracy_rate=projection.accuracy_rate,
            response_speed_seconds=projection.response_speed_seconds,
        )
        interaction_stats = self._interaction_stats(
            engagement_state=engagement_state,
            reviewed_count=reviewed_count,
        )
        await uow.engagement_states.update(
            user_id,
            current_streak=projection.current_streak,
            longest_streak=projection.longest_streak,
            momentum_score=projection.momentum_score,
            total_sessions=projection.total_sessions,
            sessions_last_3_days=projection.sessions_last_3_days,
            last_session_at=now,
            interaction_stats=interaction_stats,
        )
        await uow.progress_states.update(
            user_id,
            xp=projection.xp,
            level=projection.level,
            milestones=projection.milestones,
        )

        return AppliedLearningSession(
            reviewed_count=reviewed_count,
            learned_count=learned_count,
            updated_item_ids=updated_item_ids,
            interaction_stats=interaction_stats,
        )

    def _rolling_success_rate(self, previous_success: float, previous_reviews: int, response_accuracy: float) -> float:
        total = (max(0.0, previous_success) * max(0, previous_reviews)) + response_accuracy
        return round(total / max(1, previous_reviews + 1), 4)

    def _interaction_stats(self, *, engagement_state, reviewed_count: int) -> dict[str, int]:
        stats = dict(getattr(engagement_state, "interaction_stats", {}) or {})
        stats["lessons_completed"] = int(stats.get("lessons_completed", 0) or 0) + 1
        if reviewed_count > 0:
            stats["reviews_completed"] = int(stats.get("reviews_completed", 0) or 0) + reviewed_count
        return stats
