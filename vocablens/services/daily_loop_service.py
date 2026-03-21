from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.retention_engine import RetentionEngine


@dataclass(frozen=True)
class DailyMissionStep:
    action: str
    target: str | None
    reason: str
    difficulty: str


@dataclass(frozen=True)
class DailyLoopPlan:
    date: str
    mission: list[DailyMissionStep]
    mission_max_sessions: int
    weak_area: str
    streak: int
    streak_shield_available: bool
    loss_aversion_message: str
    momentum_score: float
    reward_chest_ready: bool
    reward_preview: dict[str, Any]
    notification_preview: dict[str, Any]


@dataclass(frozen=True)
class DailyLoopCompletion:
    completed: bool
    streak: int
    reward_chest_unlocked: bool
    reward_preview: dict[str, Any]
    momentum_score: float


@dataclass(frozen=True)
class SkipShieldResult:
    applied: bool
    streak_preserved: bool
    shields_remaining_this_week: int
    reason: str


class DailyLoopService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        learning_engine: LearningEngine,
        gamification_service: GamificationService,
        notification_engine: NotificationDecisionEngine,
        retention_engine: RetentionEngine,
        event_service: EventService | None = None,
    ):
        self._uow_factory = uow_factory
        self._learning = learning_engine
        self._gamification = gamification_service
        self._notifications = notification_engine
        self._retention = retention_engine
        self._events = event_service

    async def build_daily_loop(self, user_id: int) -> DailyLoopPlan:
        recommendation = await self._learning.get_next_lesson(user_id)
        retention = await self._retention.assess_user(user_id)
        gamification = await self._gamification.summary(user_id)

        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            due_items = await uow.vocab.list_due(user_id)
            await uow.commit()

        weak_area = self._weak_area(recommendation, learning_state)
        momentum_score = float(getattr(engagement_state, "momentum_score", 0.0) or 0.0)
        mission_max_sessions = self._mission_size(momentum_score, retention.drop_off_risk)
        mission = self._mission_steps(recommendation, weak_area, mission_max_sessions, due_items)
        shield_available = self._shield_available(engagement_state)
        reward_chest_ready = self._mission_completed_today(engagement_state)
        reward_preview = self._reward_preview(progress_state, gamification, reward_chest_ready)
        notification = await self._notifications.decide(user_id, retention)

        if self._events:
            await self._events.track_event(
                user_id,
                "daily_mission_generated",
                {
                    "weak_area": weak_area,
                    "mission_sessions": mission_max_sessions,
                    "momentum_score": momentum_score,
                },
            )

        return DailyLoopPlan(
            date=utc_now().date().isoformat(),
            mission=mission,
            mission_max_sessions=mission_max_sessions,
            weak_area=weak_area,
            streak=int(getattr(engagement_state, "current_streak", 0) or 0),
            streak_shield_available=shield_available,
            loss_aversion_message=self._loss_aversion_message(engagement_state, progress_state, due_items, weak_area),
            momentum_score=momentum_score,
            reward_chest_ready=reward_chest_ready,
            reward_preview=reward_preview,
            notification_preview={
                "should_send": notification.should_send,
                "channel": notification.channel,
                "send_at": notification.send_at.isoformat(),
                "reason": notification.reason,
            },
        )

    async def complete_daily_mission(self, user_id: int) -> DailyLoopCompletion:
        await self._retention.record_activity(user_id)
        now = utc_now()
        async with self._uow_factory() as uow:
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            momentum_score = round(min(1.0, float(engagement_state.momentum_score or 0.0) + 0.2), 3)
            engagement_state = await uow.engagement_states.update(
                user_id,
                momentum_score=momentum_score,
                daily_mission_completed_at=now,
            )
            xp = int(progress_state.xp or 0) + 25
            level = max(1, (xp // 250) + 1)
            milestones = [milestone for milestone in (2, 3, 5, 10) if level >= milestone]
            progress_state = await uow.progress_states.update(
                user_id,
                xp=xp,
                level=level,
                milestones=milestones,
            )
            await uow.commit()
        gamification = await self._gamification.summary(user_id)
        reward_preview = self._reward_preview(progress_state, gamification, True)

        if self._events:
            await self._events.track_event(
                user_id,
                "daily_mission_completed",
                {
                    "streak": engagement_state.current_streak,
                    "momentum_score": momentum_score,
                },
            )
            await self._events.track_event(
                user_id,
                "reward_chest_unlocked",
                {
                    "xp_reward": reward_preview["xp_reward"],
                    "badge_hint": reward_preview["badge_hint"],
                },
            )

        return DailyLoopCompletion(
            completed=True,
            streak=engagement_state.current_streak,
            reward_chest_unlocked=True,
            reward_preview=reward_preview,
            momentum_score=momentum_score,
        )

    async def use_skip_shield(self, user_id: int) -> SkipShieldResult:
        async with self._uow_factory() as uow:
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            await uow.commit()

        if not self._shield_available(engagement_state):
            return SkipShieldResult(
                applied=False,
                streak_preserved=False,
                shields_remaining_this_week=0,
                reason="weekly shield already used",
            )

        shields_used = self._shields_used_this_week(engagement_state) + 1
        async with self._uow_factory() as uow:
            await uow.engagement_states.update(
                user_id,
                shields_used_this_week=shields_used,
            )
            await uow.commit()

        if self._events:
            await self._events.track_event(
                user_id,
                "skip_shield_used",
                {
                    "streak_preserved": getattr(engagement_state, "current_streak", 0),
                    "used_at": utc_now().isoformat(),
                },
            )

        return SkipShieldResult(
            applied=True,
            streak_preserved=True,
            shields_remaining_this_week=0,
            reason="shield consumed and streak preserved",
        )

    def _mission_steps(self, recommendation, weak_area: str, mission_size: int, due_items) -> list[DailyMissionStep]:
        steps: list[DailyMissionStep] = []
        primary_target = getattr(recommendation, "target", None) or weak_area
        steps.append(
            DailyMissionStep(
                action=recommendation.action,
                target=primary_target,
                reason=f"Primary mission targets {weak_area}.",
                difficulty=getattr(recommendation, "lesson_difficulty", "medium"),
            )
        )
        if mission_size >= 2:
            follow_up_action = "review_word" if due_items else "practice_grammar"
            follow_up_target = getattr(due_items[0], "source_text", None) if due_items else weak_area
            steps.append(
                DailyMissionStep(
                    action=follow_up_action,
                    target=follow_up_target,
                    reason="Second mission step reinforces weak performance.",
                    difficulty=getattr(recommendation, "lesson_difficulty", "medium"),
                )
            )
        if mission_size >= 3:
            steps.append(
                DailyMissionStep(
                    action="conversation_drill",
                    target=weak_area,
                    reason="Final mission step locks in momentum with a short drill.",
                    difficulty=getattr(recommendation, "lesson_difficulty", "medium"),
                )
            )
        return steps

    def _weak_area(self, recommendation, learning_state) -> str:
        if getattr(recommendation, "skill_focus", None):
            return str(recommendation.skill_focus)
        weak_areas = list(getattr(learning_state, "weak_areas", []) or [])
        if weak_areas:
            return str(weak_areas[0])
        return "vocabulary"

    def _mission_size(self, momentum_score: float, drop_off_risk: float) -> int:
        if drop_off_risk >= 0.65:
            return 1
        if momentum_score >= 0.7:
            return 3
        return 2

    def _shield_available(self, engagement_state) -> bool:
        return self._shields_used_this_week(engagement_state) < 1

    def _shields_used_this_week(self, engagement_state) -> int:
        updated_at = getattr(engagement_state, "updated_at", None)
        if updated_at is None or updated_at < utc_now() - timedelta(days=7):
            return 0
        return int(getattr(engagement_state, "shields_used_this_week", 0) or 0)

    def _mission_completed_today(self, engagement_state) -> bool:
        completed_at = getattr(engagement_state, "daily_mission_completed_at", None)
        return bool(completed_at and completed_at.date() == utc_now().date())

    def _loss_aversion_message(self, engagement_state, progress_state, due_items, weak_area: str) -> str:
        streak = getattr(engagement_state, "current_streak", 0)
        xp = getattr(progress_state, "xp", 0)
        if streak > 0:
            return f"Skip today and you risk losing your {streak}-day streak, daily momentum, and progress on {weak_area}."
        if due_items:
            return f"Skip today and {len(due_items)} review items will keep decaying."
        return f"Skip today and your current progress pace plus {xp} XP momentum will cool off."

    def _reward_preview(self, progress_state, gamification, unlocked: bool) -> dict[str, Any]:
        level = int(getattr(progress_state, "level", 1) or 1)
        badges = list(getattr(gamification, "badges", []) or [])
        badge_hint = badges[0].label if badges else f"Level {level + 1} push"
        return {
            "xp_reward": 25,
            "badge_hint": badge_hint,
            "chest_state": "unlocked" if unlocked else "locked",
        }
