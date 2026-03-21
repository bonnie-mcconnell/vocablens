from __future__ import annotations

from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.addiction_engine import AddictionEngine
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.onboarding_flow_presenter import OnboardingFlowPresenter
from vocablens.services.onboarding_flow_state_store import OnboardingFlowStateStore
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.wow_engine import WowEngine, WowScore

OnboardingStep = Literal[
    "identity_selection",
    "personalization",
    "instant_wow_moment",
    "progress_illusion",
    "soft_paywall",
    "habit_lock_in",
    "completed",
]


class OnboardingFlowService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        wow_engine: WowEngine,
        addiction_engine: AddictionEngine,
        lifecycle_service: LifecycleService,
        adaptive_paywall_service: AdaptivePaywallService,
        notification_decision_engine: NotificationDecisionEngine,
        retention_engine: RetentionEngine,
    ):
        self._uow_factory = uow_factory
        self._wow = wow_engine
        self._addiction = addiction_engine
        self._lifecycle = lifecycle_service
        self._paywall = adaptive_paywall_service
        self._notifications = notification_decision_engine
        self._retention = retention_engine
        self._state_store = OnboardingFlowStateStore(uow_factory)
        self._presenter = OnboardingFlowPresenter()

    async def start(self, user_id: int) -> dict:
        state = await self._state_store.load(user_id)
        if state is None:
            state = self._state_store.default_state()
            await self._state_store.save(user_id, state, event_type="onboarding_started")
        return await self._build_response(user_id, state)

    async def current_state(self, user_id: int) -> dict | None:
        return await self._state_store.load(user_id)

    async def next(self, user_id: int, payload: dict | None = None) -> dict:
        payload = dict(payload or {})
        state = await self._state_store.load(user_id) or self._state_store.default_state()

        step_handlers = {
            "identity_selection": self._handle_identity_selection,
            "personalization": self._handle_personalization,
            "instant_wow_moment": self._handle_instant_wow_moment,
            "progress_illusion": self._handle_progress_illusion,
            "soft_paywall": self._handle_soft_paywall,
            "habit_lock_in": self._handle_habit_lock_in,
        }
        handler = step_handlers.get(state["current_step"])
        if handler:
            await handler(user_id, state, payload)

        await self._state_store.save(user_id, state, event_type="onboarding_state_updated")
        if state["current_step"] == "completed":
            await self._state_store.save(user_id, state, event_type="onboarding_completed")
        return await self._build_response(user_id, state)

    async def _handle_identity_selection(self, user_id: int, state: dict, payload: dict) -> None:
        motivation = str(payload.get("motivation") or "").strip().lower()
        if not motivation:
            return
        state["identity"] = {"motivation": motivation}
        state["steps_completed"].append("identity_selection")
        state["current_step"] = "personalization"

    async def _handle_personalization(self, user_id: int, state: dict, payload: dict) -> None:
        updates = {
            "skill_level": str(payload.get("skill_level") or "").strip().lower() or None,
            "daily_goal": int(payload.get("daily_goal") or 0) or None,
            "learning_intent": str(payload.get("learning_intent") or "").strip().lower() or None,
        }
        if not all(updates.values()):
            return
        state["personalization"] = updates
        await self._persist_preferences(
            user_id=user_id,
            skill_level=updates["skill_level"],
            learning_intent=updates["learning_intent"],
        )
        state["steps_completed"].append("personalization")
        state["current_step"] = "instant_wow_moment"

    async def _handle_instant_wow_moment(self, user_id: int, state: dict, payload: dict) -> None:
        session_snapshot = dict(payload.get("session_snapshot") or {})
        wow = await self._score_wow(user_id, session_snapshot)
        understood_percent = round(wow.current_accuracy * 100, 1)
        state["wow"] = {
            "score": wow.score,
            "qualifies": wow.qualifies,
            "understood_percent": understood_percent,
            "triggers": wow.triggers,
            "session_snapshot": session_snapshot,
        }
        state["early_success_score"] = max(understood_percent, round(wow.score * 100, 1))
        if wow.qualifies or understood_percent >= 70.0:
            state["steps_completed"].append("instant_wow_moment")
            state["current_step"] = "progress_illusion"

    async def _handle_progress_illusion(self, user_id: int, state: dict, payload: dict) -> None:
        addiction = await self._addiction.execute(user_id)
        lifecycle = await self._lifecycle.evaluate(user_id)
        wow_score = float(state.get("wow", {}).get("score", 0.0) or 0.0)
        paywall = await self._paywall.evaluate(user_id, wow_score=wow_score)
        state["progress_illusion"] = {
            "xp_gain": 40 + int(addiction.reward.get("bonus_xp", 0) or 0),
            "initial_streak": max(1, addiction.ritual.get("streak_anchor", 1) - 1),
            "relative_ranking_percentile": self._ranking_percentile(
                wow_score=wow_score,
                lifecycle_stage=lifecycle.stage,
                addiction=addiction,
            ),
            "reward": addiction.reward,
            "identity": addiction.identity,
        }
        state["steps_completed"].append("progress_illusion")
        state["paywall"] = self._paywall_payload(paywall)
        should_show_paywall = (
            paywall.show_paywall
            and paywall.allow_access
            and (wow_score >= 0.65 or self._engagement_threshold_met(state))
        )
        state["current_step"] = "soft_paywall" if should_show_paywall else "habit_lock_in"

    async def _handle_soft_paywall(self, user_id: int, state: dict, payload: dict) -> None:
        accepted_trial = bool(payload.get("accept_trial"))
        skipped = bool(payload.get("skip_paywall"))
        paywall = state.get("paywall", {})
        if accepted_trial and paywall.get("trial_recommended"):
            await self._paywall.start_trial(user_id, paywall.get("trial_days"))
            paywall["trial_started"] = True
        if accepted_trial or skipped or not paywall.get("show"):
            state["steps_completed"].append("soft_paywall")
            state["current_step"] = "habit_lock_in"

    async def _handle_habit_lock_in(self, user_id: int, state: dict, payload: dict) -> None:
        preferred_time = payload.get("preferred_time_of_day")
        if preferred_time is None:
            return
        preferred_channel = str(payload.get("preferred_channel") or "push").strip().lower()
        frequency_limit = int(payload.get("frequency_limit") or 1)
        await self._persist_habit_preferences(
            user_id=user_id,
            preferred_time_of_day=int(preferred_time),
            preferred_channel=preferred_channel,
            frequency_limit=frequency_limit,
        )
        retention = await self._retention.assess_user(user_id)
        notification = await self._notifications.decide(user_id, retention)
        addiction = await self._addiction.execute(user_id)
        state["habit_lock_in"] = {
            "preferred_time_of_day": int(preferred_time),
            "preferred_channel": preferred_channel,
            "frequency_limit": frequency_limit,
            "scheduled_notification": {
                "should_send": notification.should_send,
                "send_at": notification.send_at.isoformat(),
                "channel": notification.channel,
                "reason": notification.reason,
            },
            "ritual": addiction.ritual,
            "pressure": addiction.pressure,
        }
        state["steps_completed"].append("habit_lock_in")
        state["current_step"] = "completed"

    async def _build_response(self, user_id: int, state: dict) -> dict:
        lifecycle = await self._lifecycle.evaluate(user_id)
        view = self._presenter.build(state=state, lifecycle_stage=lifecycle.stage)
        return {
            "current_step": view.current_step,
            "onboarding_state": view.onboarding_state,
            "ui_directives": view.ui_directives,
            "messaging": view.messaging,
            "next_action": view.next_action,
        }

    async def _persist_preferences(self, *, user_id: int, skill_level: str, learning_intent: str) -> None:
        difficulty = {
            "beginner": "easy",
            "intermediate": "medium",
            "advanced": "hard",
        }.get(skill_level, "medium")
        async with self._uow_factory() as uow:
            await uow.profiles.get_or_create(user_id)
            await uow.profiles.update(
                user_id=user_id,
                difficulty_preference=difficulty,
                content_preference=learning_intent,
            )
            await uow.commit()

    async def _persist_habit_preferences(
        self,
        *,
        user_id: int,
        preferred_time_of_day: int,
        preferred_channel: str,
        frequency_limit: int,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.profiles.get_or_create(user_id)
            await uow.profiles.update(
                user_id=user_id,
                preferred_time_of_day=max(0, min(23, preferred_time_of_day)),
                preferred_channel=preferred_channel if preferred_channel in {"email", "push", "in_app"} else "push",
                frequency_limit=max(1, frequency_limit),
            )
            await uow.commit()

    async def _score_wow(self, user_id: int, session_snapshot: dict) -> WowScore:
        return await self._wow.score_session(
            user_id,
            tutor_mode=bool(session_snapshot.get("tutor_mode", True)),
            correction_feedback_count=int(session_snapshot.get("correction_feedback_count", 0) or 0),
            new_words_count=int(session_snapshot.get("new_words_count", 0) or 0),
            grammar_mistake_count=int(session_snapshot.get("grammar_mistake_count", 0) or 0),
            session_turn_count=int(session_snapshot.get("session_turn_count", 0) or 0),
            reply_length=int(session_snapshot.get("reply_length", 0) or 0),
        )

    def _engagement_threshold_met(self, state: dict) -> bool:
        snapshot = state.get("wow", {}).get("session_snapshot", {}) or {}
        return (
            int(snapshot.get("session_turn_count", 0) or 0) >= 4
            or int(snapshot.get("correction_feedback_count", 0) or 0) >= 2
            or int(snapshot.get("reply_length", 0) or 0) >= 100
        )

    def _ranking_percentile(self, *, wow_score: float, lifecycle_stage: str, addiction) -> int:
        base = 52
        base += int(wow_score * 25)
        base += int(addiction.reward.get("progress_increase", 0) or 0) * 3
        if lifecycle_stage in {"new_user", "activating"}:
            base += 6
        return max(51, min(99, base))

    def _paywall_payload(self, paywall) -> dict:
        return {
            "show": bool(getattr(paywall, "show_paywall", False)),
            "type": getattr(paywall, "paywall_type", None),
            "reason": getattr(paywall, "reason", None),
            "usage_percent": getattr(paywall, "usage_percent", 0),
            "allow_access": getattr(paywall, "allow_access", True),
            "trial_recommended": getattr(paywall, "trial_recommended", False),
            "trial_days": getattr(paywall, "trial_days", None),
            "wow_score": getattr(paywall, "wow_score", 0.0),
            "strategy": getattr(paywall, "strategy", None),
        }
