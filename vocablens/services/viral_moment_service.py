from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.analytics_service import AnalyticsService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.progress_service import ProgressService


@dataclass(frozen=True)
class ViralMoment:
    type: str
    title: str
    hook: str
    caption: str
    share_text: str
    visual_payload: dict[str, object]
    source_signals: dict[str, object]
    priority: float


class ViralMomentService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        progress_service: ProgressService,
        gamification_service: GamificationService,
        analytics_service: AnalyticsService | None = None,
    ):
        self._uow_factory = uow_factory
        self._progress = progress_service
        self._gamification = gamification_service
        self._analytics = analytics_service

    async def generate_share_moments(self, user_id: int, *, limit: int = 4) -> list[ViralMoment]:
        progress = await self._progress.build_dashboard(user_id)
        gamification = await self._gamification.summary(user_id)
        async with self._uow_factory() as uow:
            users = await uow.users.list_all()
            learning_events = await uow.learning_events.list_since(user_id, since=utc_now() - timedelta(days=30))
            await uow.commit()

        metrics = progress.get("metrics", {})
        moments: list[ViralMoment] = []

        before_after = self._before_after_moment(metrics, learning_events)
        if before_after is not None:
            moments.append(before_after)

        percentile = await self._percentile_moment(user_id, metrics, users)
        if percentile is not None:
            moments.append(percentile)

        streak = self._streak_flex_moment(gamification)
        if streak is not None:
            moments.append(streak)

        hard_sentence = self._hard_sentence_moment(learning_events)
        if hard_sentence is not None:
            moments.append(hard_sentence)

        moments.sort(key=lambda item: (-item.priority, item.type))
        return moments[: max(1, limit)]

    async def best_share_moment(self, user_id: int, moment_type: str | None = None) -> ViralMoment | None:
        moments = await self.generate_share_moments(user_id, limit=10)
        if moment_type is None:
            return moments[0] if moments else None
        for moment in moments:
            if moment.type == moment_type:
                return moment
        return None

    def _before_after_moment(self, metrics: dict, learning_events) -> ViralMoment | None:
        current_accuracy = round(float(metrics.get("accuracy_rate", 0.0) or 0.0), 1)
        baseline_accuracy = self._baseline_accuracy(learning_events)
        if current_accuracy <= 0:
            return None
        improvement = max(0.0, round(current_accuracy - baseline_accuracy, 1))
        return ViralMoment(
            type="before_after",
            title="Before vs After",
            hook=f"My first session was rough. Now I'm at {current_accuracy}% accuracy.",
            caption=f"Started at {baseline_accuracy}% accuracy. Now I'm {improvement} points better.",
            share_text=f"Before: {baseline_accuracy}% accuracy. After: {current_accuracy}%.",
            visual_payload={
                "before_accuracy": baseline_accuracy,
                "after_accuracy": current_accuracy,
                "delta": improvement,
            },
            source_signals={
                "baseline_accuracy": baseline_accuracy,
                "current_accuracy": current_accuracy,
            },
            priority=0.96 if improvement >= 15 else 0.82,
        )

    async def _percentile_moment(self, user_id: int, metrics: dict, users) -> ViralMoment | None:
        if not users:
            return None
        current_mastery = round(float(metrics.get("vocabulary_mastery_percent", 0.0) or 0.0), 1)
        peer_masteries = []
        for user in users:
            peer_progress = await self._progress.build_dashboard(user.id)
            peer_masteries.append(float(peer_progress.get("metrics", {}).get("vocabulary_mastery_percent", 0.0) or 0.0))
        percentile = self._percentile(current_mastery, peer_masteries)
        return ViralMoment(
            type="percentile",
            title="Percentile",
            hook=f"You're better than {percentile}% of learners on mastery.",
            caption=f"Current vocabulary mastery puts you ahead of {percentile}% of active learners.",
            share_text=f"Better than {percentile}% of learners on vocabulary mastery.",
            visual_payload={
                "percentile": percentile,
                "metric": "vocabulary_mastery_percent",
                "value": current_mastery,
            },
            source_signals={
                "mastery_percent": current_mastery,
                "percentile": percentile,
            },
            priority=0.9 if percentile >= 75 else 0.74,
        )

    def _streak_flex_moment(self, gamification) -> ViralMoment | None:
        streak = int(getattr(gamification, "current_streak", 0) or 0)
        if streak <= 0:
            return None
        badge = "streak_master" if streak >= 7 else "streak_keeper" if streak >= 3 else "daily_player"
        return ViralMoment(
            type="streak_flex",
            title=f"{streak}-Day Streak",
            hook=f"I've kept this streak alive for {streak} days.",
            caption=f"Level {gamification.level}, {gamification.xp} XP, and the streak is still climbing.",
            share_text=f"{streak}-day streak. Level {gamification.level}. {gamification.xp} XP.",
            visual_payload={
                "badge": badge,
                "streak_days": streak,
                "level": gamification.level,
                "xp": gamification.xp,
            },
            source_signals={
                "current_streak": streak,
                "level": gamification.level,
                "xp": gamification.xp,
            },
            priority=0.88 if streak >= 7 else 0.72,
        )

    def _hard_sentence_moment(self, learning_events) -> ViralMoment | None:
        for event in sorted(
            list(learning_events),
            key=lambda item: getattr(item, "created_at", utc_now()),
            reverse=True,
        ):
            if getattr(event, "event_type", None) != "conversation_turn":
                continue
            payload = self._payload(event)
            message = str(payload.get("message", "") or "").strip()
            mistakes = payload.get("mistakes", {}) or {}
            grammar_mistakes = mistakes.get("grammar_mistakes", []) if isinstance(mistakes, dict) else []
            if len(message) >= 24 and len(grammar_mistakes) <= 1:
                return ViralMoment(
                    type="hard_sentence_mastered",
                    title="Hard Sentence Mastered",
                    hook="I can say this now without freezing.",
                    caption=f"One of my strongest recent lines: {message}",
                    share_text=f"Hard sentence mastered: {message}",
                    visual_payload={
                        "sentence": message,
                        "mistake_count": len(grammar_mistakes),
                    },
                    source_signals={
                        "sentence_length": len(message),
                        "mistake_count": len(grammar_mistakes),
                    },
                    priority=0.92,
                )
        return None

    def _baseline_accuracy(self, learning_events) -> float:
        scored = []
        for event in sorted(learning_events, key=lambda item: getattr(item, "created_at", utc_now())):
            if getattr(event, "event_type", None) != "word_reviewed":
                continue
            payload = self._payload(event)
            if payload.get("response_accuracy") is not None:
                scored.append(float(payload["response_accuracy"]) * 100)
            if len(scored) >= 3:
                break
        if not scored:
            return 50.0
        return round(sum(scored) / len(scored), 1)

    def _payload(self, event) -> dict:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            return payload
        payload_json = getattr(event, "payload_json", None)
        if not payload_json:
            return {}
        try:
            return json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _percentile(self, current_value: float, values: list[float]) -> int:
        if not values:
            return 50
        lower = sum(1 for value in values if value < current_value)
        percentile = round((lower / max(1, len(values))) * 100)
        return max(1, min(99, int(percentile)))
