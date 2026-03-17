from dataclasses import dataclass
from typing import Any

from vocablens.infrastructure.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class PersonalizationProfile:
    learning_speed: float
    retention_rate: float
    difficulty_preference: str
    content_preference: str


@dataclass(frozen=True)
class PersonalizationAdaptation:
    lesson_difficulty: str
    review_frequency_multiplier: float
    content_type: str


class PersonalizationService:
    """
    Maintains and interprets per-user learning profile.
    """

    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def get_profile(self, user_id: int) -> PersonalizationProfile:
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            await uow.commit()
            return self._snapshot(profile)

    async def get_adaptation(self, user_id: int) -> PersonalizationAdaptation:
        profile = await self.get_profile(user_id)
        review_multiplier = self._review_multiplier(profile.retention_rate, profile.learning_speed)
        lesson_difficulty = self._lesson_difficulty(profile.difficulty_preference, profile.learning_speed)
        return PersonalizationAdaptation(
            lesson_difficulty=lesson_difficulty,
            review_frequency_multiplier=review_multiplier,
            content_type=profile.content_preference,
        )

    async def update_from_session(
        self,
        user_id: int,
        session_duration_sec: float | None = None,
        correct_ratio: float | None = None,
        content_type: str | None = None,
    ):
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            speed = profile.learning_speed
            retention = profile.retention_rate
            difficulty = profile.difficulty_preference
            content = profile.content_preference

            if session_duration_sec is not None and session_duration_sec > 0:
                if session_duration_sec < 180:
                    speed = min(1.6, speed * 1.03)
                elif session_duration_sec > 900:
                    speed = max(0.75, speed * 0.98)

            if correct_ratio is not None:
                retention = max(0.3, min(1.0, 0.8 * retention + 0.2 * correct_ratio))
                if correct_ratio < 0.6:
                    difficulty = "easy"
                    speed = max(0.8, speed * 0.95)
                elif correct_ratio > 0.85:
                    difficulty = "hard" if speed > 1.1 else "medium"
                    speed = min(1.5, speed * 1.05)

            if content_type:
                content = content_type

            await uow.profiles.update(
                user_id=user_id,
                learning_speed=speed,
                retention_rate=retention,
                difficulty_preference=difficulty,
                content_preference=content,
            )
            await uow.commit()

    async def update_from_learning_signals(self, user_id: int):
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            events = await uow.learning_events.list_since(user_id, since=profile.updated_at)
            mistakes = await uow.mistake_patterns.top_patterns(user_id, limit=5)

            reviews = [e for e in events if e.event_type == "word_reviewed"]
            learned = [e for e in events if e.event_type == "word_learned"]
            conversations = [e for e in events if e.event_type == "conversation_turn"]

            retention = profile.retention_rate
            if reviews:
                qualities = []
                for event in reviews:
                    payload = getattr(event, "payload_json", None) or ""
                    try:
                        import json
                        qualities.append(int(json.loads(payload).get("quality", 3)))
                    except Exception:
                        qualities.append(3)
                retention = max(0.3, min(1.0, sum(qualities) / (len(qualities) * 5)))

            speed = profile.learning_speed
            if learned or conversations:
                activity = len(learned) + (0.5 * len(conversations))
                speed = max(0.75, min(1.6, 0.9 * speed + 0.1 * min(1.6, 0.8 + (activity / 10))))

            content = self._infer_content_preference(mistakes, learned, reviews, conversations, profile.content_preference)
            difficulty = self._infer_difficulty_preference(retention, speed, profile.difficulty_preference)

            await uow.profiles.update(
                user_id=user_id,
                learning_speed=speed,
                retention_rate=retention,
                difficulty_preference=difficulty,
                content_preference=content,
            )
            await uow.commit()

    async def set_preferences(
        self,
        user_id: int,
        difficulty: str | None = None,
        content: str | None = None,
    ):
        async with self._uow_factory() as uow:
            await uow.profiles.get_or_create(user_id)
            await uow.profiles.update(
                user_id=user_id,
                difficulty_preference=difficulty,
                content_preference=content,
            )
            await uow.commit()

    def _snapshot(self, profile: Any) -> PersonalizationProfile:
        return PersonalizationProfile(
            learning_speed=profile.learning_speed,
            retention_rate=profile.retention_rate,
            difficulty_preference=profile.difficulty_preference,
            content_preference=profile.content_preference,
        )

    def _review_multiplier(self, retention_rate: float, learning_speed: float) -> float:
        base = 1.0
        if retention_rate < 0.6:
            base *= 0.75
        elif retention_rate > 0.85:
            base *= 1.15
        if learning_speed < 0.95:
            base *= 0.9
        elif learning_speed > 1.2:
            base *= 1.1
        return max(0.6, min(1.4, base))

    def _lesson_difficulty(self, preference: str, learning_speed: float) -> str:
        if preference == "easy" or learning_speed < 0.9:
            return "easy"
        if preference == "hard" and learning_speed > 1.05:
            return "hard"
        return "medium"

    def _infer_content_preference(self, mistakes, learned, reviews, conversations, current: str) -> str:
        if mistakes:
            top = mistakes[0]
            if top.category == "grammar":
                return "grammar"
            if top.category == "vocabulary":
                return "vocab"
        if len(conversations) > max(len(learned), len(reviews)):
            return "conversation"
        if len(reviews) > len(learned):
            return "vocab"
        return current or "mixed"

    def _infer_difficulty_preference(self, retention: float, speed: float, current: str) -> str:
        if retention < 0.55 or speed < 0.9:
            return "easy"
        if retention > 0.85 and speed > 1.15:
            return "hard"
        return "medium" if current != "hard" else current
