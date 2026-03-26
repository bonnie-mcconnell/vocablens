from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.event_service import EventService
from vocablens.services.gamification_service import GamificationService
from vocablens.services.daily_loop_health_signal_service import DailyLoopHealthSignalService
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


@dataclass(frozen=True)
class RewardChestClaim:
    claimed: bool
    already_claimed: bool
    reward_preview: dict[str, Any]


class DailyLoopService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        learning_engine: LearningEngine,
        gamification_service: GamificationService,
        notification_engine: NotificationDecisionEngine,
        retention_engine: RetentionEngine,
        event_service: EventService | None = None,
        daily_loop_health_signal_service: DailyLoopHealthSignalService | None = None,
    ):
        self._uow_factory = uow_factory
        self._learning = learning_engine
        self._gamification = gamification_service
        self._notifications = notification_engine
        self._retention = retention_engine
        self._events = event_service
        self._health_signals = daily_loop_health_signal_service or DailyLoopHealthSignalService(uow_factory)

    async def build_daily_loop(self, user_id: int) -> DailyLoopPlan:
        mission_date = utc_now().date().isoformat()
        async with self._uow_factory() as uow:
            existing_mission = await uow.daily_missions.get_by_user_date(user_id, mission_date)
            if existing_mission is not None:
                reward_chest = await uow.reward_chests.get_by_mission_id(existing_mission.id)
                await uow.commit()
                return self._plan_from_rows(existing_mission, reward_chest)

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
        notification_preview = {
            "should_send": notification.should_send,
            "channel": notification.channel,
            "send_at": notification.send_at.isoformat(),
            "reason": notification.reason,
        }

        async with self._uow_factory() as uow:
            mission_row = await uow.daily_missions.create(
                user_id=user_id,
                mission_date=mission_date,
                weak_area=weak_area,
                mission_max_sessions=mission_max_sessions,
                steps=[asdict(step) for step in mission],
                loss_aversion_message=self._loss_aversion_message(engagement_state, progress_state, due_items, weak_area),
                streak_at_issue=int(getattr(engagement_state, "current_streak", 0) or 0),
                momentum_score=momentum_score,
                notification_preview=notification_preview,
            )
            chest_row = await uow.reward_chests.create(
                user_id=user_id,
                mission_id=mission_row.id,
                xp_reward=int(reward_preview["xp_reward"]),
                badge_hint=str(reward_preview["badge_hint"]),
                payload=dict(reward_preview),
            )
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="daily_mission_generation",
                source="daily_loop_service.build_daily_loop",
                reference_id=f"daily_mission:{user_id}:{mission_date}",
                policy_version="v1",
                inputs={
                    "recommendation": {
                        "action": recommendation.action,
                        "target": getattr(recommendation, "target", None),
                        "skill_focus": getattr(recommendation, "skill_focus", None),
                        "difficulty": getattr(recommendation, "lesson_difficulty", "medium"),
                    },
                    "retention": {
                        "state": retention.state,
                        "drop_off_risk": round(float(retention.drop_off_risk or 0.0), 3),
                        "current_streak": int(retention.current_streak or 0),
                    },
                    "engagement": {
                        "momentum_score": momentum_score,
                        "current_streak": int(getattr(engagement_state, "current_streak", 0) or 0),
                        "sessions_last_3_days": int(getattr(engagement_state, "sessions_last_3_days", 0) or 0),
                    },
                    "learning_state": {
                        "weak_areas": list(getattr(learning_state, "weak_areas", []) or []),
                        "due_items_count": len(due_items),
                    },
                },
                outputs={
                    "mission_date": mission_date,
                    "weak_area": weak_area,
                    "mission_max_sessions": mission_max_sessions,
                    "steps": [asdict(step) for step in mission],
                    "notification_preview": notification_preview,
                    "reward_preview": dict(reward_preview),
                },
                reason=f"Generated canonical daily mission for {weak_area}.",
            )
            await uow.commit()

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
        await self._health_signals.evaluate_scope("global")
        return self._plan_from_rows(mission_row, chest_row, streak_shield_available=shield_available)

    async def get_or_issue_daily_mission(self, user_id: int) -> DailyLoopPlan:
        return await self.build_daily_loop(user_id)

    async def complete_daily_mission(self, user_id: int) -> DailyLoopCompletion:
        await self._retention.record_activity(user_id)
        now = utc_now()
        async with self._uow_factory() as uow:
            mission = await uow.daily_missions.get_by_user_date(user_id, now.date().isoformat())
            if mission is None:
                await uow.commit()
                raise ValueError("Daily mission not issued")
            chest = await uow.reward_chests.get_by_mission_id(mission.id)
            if mission.status == "completed":
                await uow.commit()
                return self._completion_from_rows(mission, chest, current_streak=None, momentum_score=mission.momentum_score)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            previous_momentum_score = round(float(engagement_state.momentum_score or 0.0), 3)
            previous_xp = int(progress_state.xp or 0)
            previous_level = int(progress_state.level or 1)
            momentum_score = round(min(1.0, previous_momentum_score + 0.2), 3)
            engagement_state = await uow.engagement_states.update(
                user_id,
                momentum_score=momentum_score,
                daily_mission_completed_at=now,
            )
            xp = previous_xp + 25
            level = max(1, (xp // 250) + 1)
            milestones = [milestone for milestone in (2, 3, 5, 10) if level >= milestone]
            progress_state = await uow.progress_states.update(
                user_id,
                xp=xp,
                level=level,
                milestones=milestones,
            )
            mission = await uow.daily_missions.mark_completed(mission.id, completed_at=now)
            if chest is not None and getattr(chest, "status", "") == "locked":
                chest = await uow.reward_chests.mark_unlocked(chest.id, unlocked_at=now)
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="reward_chest_resolution",
                source="daily_loop_service.complete_daily_mission",
                reference_id=f"reward_chest:{chest.id}",
                policy_version="v1",
                inputs={
                    "mission_id": int(mission.id),
                    "mission_date": str(mission.mission_date),
                    "previous_momentum_score": previous_momentum_score,
                    "previous_xp": previous_xp,
                    "previous_level": previous_level,
                },
                outputs={
                    "mission_status": str(mission.status),
                    "reward_chest_status": str(chest.status),
                    "xp_reward": int(chest.xp_reward),
                    "badge_hint": str(chest.badge_hint),
                    "updated_momentum_score": momentum_score,
                    "updated_xp": xp,
                    "updated_level": level,
                },
                reason="Completed daily mission and unlocked canonical reward chest.",
            )
            await uow.commit()
        reward_preview = self._reward_preview_from_chest(chest)

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
        await self._health_signals.evaluate_scope("global")
        return self._completion_from_rows(
            mission,
            chest,
            current_streak=engagement_state.current_streak,
            momentum_score=momentum_score,
        )

    async def claim_reward_chest(self, user_id: int) -> RewardChestClaim:
        now = utc_now()
        async with self._uow_factory() as uow:
            mission = await uow.daily_missions.get_by_user_date(user_id, now.date().isoformat())
            if mission is None:
                await uow.commit()
                raise ValueError("Daily mission not issued")
            chest = await uow.reward_chests.get_by_mission_id(mission.id)
            if chest is None:
                await uow.commit()
                raise ValueError("Reward chest not issued")
            if str(getattr(chest, "status", "")) == "locked":
                await uow.commit()
                raise ValueError("Reward chest is locked")
            if str(getattr(chest, "status", "")) == "claimed":
                await uow.commit()
                return RewardChestClaim(
                    claimed=True,
                    already_claimed=True,
                    reward_preview=self._reward_preview_from_chest(chest),
                )
            chest = await uow.reward_chests.mark_claimed(chest.id, claimed_at=now)
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="reward_chest_resolution",
                source="daily_loop_service.claim_reward_chest",
                reference_id=f"reward_chest:{chest.id}",
                policy_version="v1",
                inputs={
                    "mission_id": int(mission.id),
                    "mission_date": str(mission.mission_date),
                    "previous_status": "unlocked",
                },
                outputs={
                    "reward_chest_id": int(chest.id),
                    "status": str(chest.status),
                    "claimed_at": now.isoformat(),
                },
                reason="Claimed canonical reward chest.",
            )
            await uow.commit()

        if self._events:
            await self._events.track_event(
                user_id,
                "reward_chest_claimed",
                {
                    "reward_chest_id": int(chest.id),
                    "xp_reward": int(getattr(chest, "xp_reward", 25) or 25),
                    "badge_hint": str(getattr(chest, "badge_hint", "Reward pending") or "Reward pending"),
                },
            )
        await self._health_signals.evaluate_scope("global")
        return RewardChestClaim(
            claimed=True,
            already_claimed=False,
            reward_preview=self._reward_preview_from_chest(chest),
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
        await self._health_signals.evaluate_scope("global")

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

    def _plan_from_rows(self, mission, reward_chest, *, streak_shield_available: bool | None = None) -> DailyLoopPlan:
        steps = [
            DailyMissionStep(
                action=str(step.get("action") or ""),
                target=step.get("target"),
                reason=str(step.get("reason") or ""),
                difficulty=str(step.get("difficulty") or "medium"),
            )
            for step in list(getattr(mission, "steps", []) or [])
        ]
        return DailyLoopPlan(
            date=str(mission.mission_date),
            mission=steps,
            mission_max_sessions=int(mission.mission_max_sessions),
            weak_area=str(mission.weak_area),
            streak=int(getattr(mission, "streak_at_issue", 0) or 0),
            streak_shield_available=True if streak_shield_available is None else streak_shield_available,
            loss_aversion_message=str(mission.loss_aversion_message),
            momentum_score=float(mission.momentum_score or 0.0),
            reward_chest_ready=bool(reward_chest and reward_chest.status in {"unlocked", "claimed"}),
            reward_preview=self._reward_preview_from_chest(reward_chest),
            notification_preview=dict(getattr(mission, "notification_preview", {}) or {}),
        )

    def _completion_from_rows(self, mission, chest, *, current_streak: int | None, momentum_score: float) -> DailyLoopCompletion:
        return DailyLoopCompletion(
            completed=str(getattr(mission, "status", "")) == "completed",
            streak=int(current_streak if current_streak is not None else getattr(mission, "streak_at_issue", 0) or 0),
            reward_chest_unlocked=bool(chest and getattr(chest, "status", "") in {"unlocked", "claimed"}),
            reward_preview=self._reward_preview_from_chest(chest),
            momentum_score=round(float(momentum_score), 3),
        )

    def _reward_preview_from_chest(self, chest) -> dict[str, Any]:
        if chest is None:
            return {"xp_reward": 25, "badge_hint": "Reward pending", "chest_state": "locked"}
        payload = dict(getattr(chest, "payload", {}) or {})
        payload.setdefault("xp_reward", int(getattr(chest, "xp_reward", 25) or 25))
        payload.setdefault("badge_hint", str(getattr(chest, "badge_hint", "Reward pending") or "Reward pending"))
        payload["chest_state"] = str(getattr(chest, "status", "") or "locked")
        return payload
