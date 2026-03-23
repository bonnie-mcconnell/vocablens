from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.addiction_engine import AddictionEngine
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
from vocablens.services.onboarding_flow_presenter import OnboardingFlowPresenter
from vocablens.services.onboarding_flow_state_store import OnboardingFlowStateStore
from vocablens.services.report_models import (
    OnboardingFlowState,
    OnboardingHabitLockInState,
    OnboardingIdentityState,
    OnboardingPaywallState,
    OnboardingPersonalizationState,
    OnboardingProgressIllusionState,
    OnboardingScheduledNotificationState,
    OnboardingWowPayload,
)
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.user_experience_contracts import OnboardingMessaging, OnboardingResponse
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
            await self._record_transition_trace(
                user_id=user_id,
                from_step=None,
                to_step=state.current_step,
                reason="Initialized a fresh onboarding flow.",
                inputs={"source": "start"},
                outputs={"steps_completed": list(state.steps_completed)},
            )
        return await self._build_response(user_id, state)

    async def current_state(self, user_id: int) -> dict | None:
        state = await self._state_store.load(user_id)
        return asdict(state) if state is not None else None

    async def next(self, user_id: int, payload: dict | None = None) -> dict:
        payload = dict(payload or {})
        state = await self._state_store.load(user_id) or self._state_store.default_state()
        previous_step = state.current_step

        step_handlers = {
            "identity_selection": self._handle_identity_selection,
            "personalization": self._handle_personalization,
            "instant_wow_moment": self._handle_instant_wow_moment,
            "progress_illusion": self._handle_progress_illusion,
            "soft_paywall": self._handle_soft_paywall,
            "habit_lock_in": self._handle_habit_lock_in,
        }
        handler = step_handlers.get(state.current_step)
        if handler:
            await handler(user_id, state, payload)

        await self._state_store.save(user_id, state, event_type="onboarding_state_updated")
        if state.current_step != previous_step:
            await self._record_transition_trace(
                user_id=user_id,
                from_step=previous_step,
                to_step=state.current_step,
                reason=self._transition_reason(previous_step, state),
                inputs=self._transition_inputs(previous_step, payload),
                outputs={"steps_completed": list(state.steps_completed)},
            )
        if state.current_step == "completed":
            await self._state_store.save(user_id, state, event_type="onboarding_completed")
        return await self._build_response(user_id, state)

    async def _handle_identity_selection(self, user_id: int, state: OnboardingFlowState, payload: dict) -> None:
        motivation = str(payload.get("motivation") or "").strip().lower()
        if not motivation:
            return
        state.identity = OnboardingIdentityState(motivation=motivation)
        state.steps_completed.append("identity_selection")
        state.current_step = "personalization"

    async def _handle_personalization(self, user_id: int, state: OnboardingFlowState, payload: dict) -> None:
        updates = {
            "skill_level": str(payload.get("skill_level") or "").strip().lower() or None,
            "daily_goal": int(payload.get("daily_goal") or 0) or None,
            "learning_intent": str(payload.get("learning_intent") or "").strip().lower() or None,
        }
        if not all(updates.values()):
            return
        state.personalization = OnboardingPersonalizationState(**updates)
        await self._persist_preferences(
            user_id=user_id,
            skill_level=updates["skill_level"],
            learning_intent=updates["learning_intent"],
        )
        state.steps_completed.append("personalization")
        state.current_step = "instant_wow_moment"

    async def _handle_instant_wow_moment(self, user_id: int, state: OnboardingFlowState, payload: dict) -> None:
        session_snapshot = dict(payload.get("session_snapshot") or {})
        wow = await self._score_wow(user_id, session_snapshot)
        understood_percent = round(wow.current_accuracy * 100, 1)
        state.wow = OnboardingWowPayload(
            score=wow.score,
            qualifies=wow.qualifies,
            triggered=False,
            understood_percent=understood_percent,
            triggers=wow.triggers,
            session_snapshot=session_snapshot,
        )
        state.early_success_score = max(understood_percent, round(wow.score * 100, 1))
        if wow.qualifies or understood_percent >= 70.0:
            state.steps_completed.append("instant_wow_moment")
            state.current_step = "progress_illusion"

    async def _handle_progress_illusion(self, user_id: int, state: OnboardingFlowState, payload: dict) -> None:
        addiction = await self._addiction.execute(user_id)
        lifecycle = await self._lifecycle.evaluate(user_id)
        wow_score = float(state.wow.score or 0.0)
        paywall = await self._paywall.evaluate(user_id, wow_score=wow_score)
        reward = self._as_payload(addiction.reward)
        ritual = self._as_payload(addiction.ritual)
        state.progress_illusion = OnboardingProgressIllusionState(
            xp_gain=40 + int(reward.get("bonus_xp", 0) or 0),
            initial_streak=max(1, int(ritual.get("streak_anchor", 1) or 1) - 1),
            relative_ranking_percentile=self._ranking_percentile(
                wow_score=wow_score,
                lifecycle_stage=lifecycle.stage,
                addiction=addiction,
            ),
            reward=reward,
            identity=self._as_payload(addiction.identity),
        )
        state.steps_completed.append("progress_illusion")
        state.paywall = self._paywall_payload(paywall)
        should_show_paywall = (
            paywall.show_paywall
            and paywall.allow_access
            and (wow_score >= 0.65 or self._engagement_threshold_met(state))
        )
        if should_show_paywall:
            await self._record_paywall_trace(
                user_id=user_id,
                state=state,
                lifecycle_stage=lifecycle.stage,
                reason="Paywall shown after progress illusion because wow or engagement threshold qualified.",
            )
        state.current_step = "soft_paywall" if should_show_paywall else "habit_lock_in"

    async def _handle_soft_paywall(self, user_id: int, state: OnboardingFlowState, payload: dict) -> None:
        accepted_trial = bool(payload.get("accept_trial"))
        skipped = bool(payload.get("skip_paywall"))
        paywall = state.paywall
        if accepted_trial and paywall.trial_recommended:
            await self._paywall.start_trial(user_id, paywall.trial_days)
            state.paywall = OnboardingPaywallState(**(asdict(paywall) | {"trial_started": True}))
        if accepted_trial or skipped or not paywall.show:
            state.steps_completed.append("soft_paywall")
            state.current_step = "habit_lock_in"

    async def _handle_habit_lock_in(self, user_id: int, state: OnboardingFlowState, payload: dict) -> None:
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
        state.habit_lock_in = OnboardingHabitLockInState(
            preferred_time_of_day=int(preferred_time),
            preferred_channel=preferred_channel,
            frequency_limit=frequency_limit,
            scheduled_notification=OnboardingScheduledNotificationState(
                should_send=notification.should_send,
                send_at=notification.send_at.isoformat(),
                channel=notification.channel,
                reason=notification.reason,
            ),
            ritual=self._as_payload(addiction.ritual),
            pressure=self._as_payload(addiction.pressure),
        )
        state.steps_completed.append("habit_lock_in")
        state.current_step = "completed"

    async def _build_response(self, user_id: int, state: OnboardingFlowState) -> dict:
        lifecycle = await self._lifecycle.evaluate(user_id)
        serialized_state = asdict(state)
        view = self._presenter.build(state=serialized_state, lifecycle_stage=lifecycle.stage)
        response = OnboardingResponse(
            current_step=view.current_step,
            onboarding_state=serialized_state,
            ui_directives=asdict(view.ui_directives) if is_dataclass(view.ui_directives) else view.ui_directives,
            messaging=OnboardingMessaging(**(asdict(view.messaging) if is_dataclass(view.messaging) else view.messaging)),
            next_action=asdict(view.next_action) if is_dataclass(view.next_action) else view.next_action,
        )
        return response.model_dump(mode="json")

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

    def _engagement_threshold_met(self, state: OnboardingFlowState) -> bool:
        snapshot = state.wow.session_snapshot or {}
        return (
            int(snapshot.get("session_turn_count", 0) or 0) >= 4
            or int(snapshot.get("correction_feedback_count", 0) or 0) >= 2
            or int(snapshot.get("reply_length", 0) or 0) >= 100
        )

    def _ranking_percentile(self, *, wow_score: float, lifecycle_stage: str, addiction) -> int:
        base = 52
        base += int(wow_score * 25)
        reward = self._as_payload(addiction.reward)
        base += int(reward.get("progress_increase", 0) or 0) * 3
        if lifecycle_stage in {"new_user", "activating"}:
            base += 6
        return max(51, min(99, base))

    def _paywall_payload(self, paywall) -> OnboardingPaywallState:
        return OnboardingPaywallState(
            show=bool(getattr(paywall, "show_paywall", False)),
            type=getattr(paywall, "paywall_type", None),
            reason=getattr(paywall, "reason", None),
            usage_percent=getattr(paywall, "usage_percent", 0),
            allow_access=getattr(paywall, "allow_access", True),
            trial_recommended=getattr(paywall, "trial_recommended", False),
            trial_days=getattr(paywall, "trial_days", None),
            wow_score=getattr(paywall, "wow_score", 0.0),
            strategy=getattr(paywall, "strategy", None),
        )

    def _as_payload(self, value) -> dict:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return dict(value)
        return {}

    async def _record_transition_trace(
        self,
        *,
        user_id: int,
        from_step: str | None,
        to_step: str,
        reason: str,
        inputs: dict,
        outputs: dict,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="onboarding_transition",
                source="onboarding_flow_service",
                reference_id=f"onboarding:{user_id}",
                policy_version="v1",
                inputs={
                    "from_step": from_step,
                    **inputs,
                },
                outputs={
                    "to_step": to_step,
                    **outputs,
                },
                reason=reason,
            )
            await uow.commit()

    async def _record_paywall_trace(
        self,
        *,
        user_id: int,
        state: OnboardingFlowState,
        lifecycle_stage: str,
        reason: str,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="onboarding_paywall_entry",
                source="onboarding_flow_service",
                reference_id=f"onboarding:{user_id}",
                policy_version="v1",
                inputs={
                    "current_step": state.current_step,
                    "wow_score": state.wow.score,
                    "understood_percent": state.wow.understood_percent,
                    "lifecycle_stage": lifecycle_stage,
                    "paywall": asdict(state.paywall),
                },
                outputs={
                    "next_step": "soft_paywall",
                    "paywall_strategy": state.paywall.strategy,
                    "trial_recommended": state.paywall.trial_recommended,
                },
                reason=reason,
            )
            await uow.commit()

    def _transition_reason(self, previous_step: str, state: OnboardingFlowState) -> str:
        if previous_step == "identity_selection":
            return "User selected an onboarding motivation."
        if previous_step == "personalization":
            return "User completed onboarding preferences."
        if previous_step == "instant_wow_moment":
            return "Wow or comprehension threshold qualified the user for progression."
        if previous_step == "progress_illusion":
            return "Progress illusion finished and next step was chosen from paywall eligibility."
        if previous_step == "soft_paywall":
            return "User cleared the paywall step by accepting, skipping, or bypassing it."
        if previous_step == "habit_lock_in":
            return "User locked in reminder preferences and completed onboarding."
        return "Onboarding step advanced."

    def _transition_inputs(self, previous_step: str, payload: dict) -> dict:
        if previous_step == "identity_selection":
            return {"motivation": payload.get("motivation")}
        if previous_step == "personalization":
            return {
                "skill_level": payload.get("skill_level"),
                "daily_goal": payload.get("daily_goal"),
                "learning_intent": payload.get("learning_intent"),
            }
        if previous_step == "instant_wow_moment":
            return {"session_snapshot": dict(payload.get("session_snapshot") or {})}
        if previous_step == "soft_paywall":
            return {
                "accept_trial": bool(payload.get("accept_trial")),
                "skip_paywall": bool(payload.get("skip_paywall")),
            }
        if previous_step == "habit_lock_in":
            return {
                "preferred_time_of_day": payload.get("preferred_time_of_day"),
                "preferred_channel": payload.get("preferred_channel"),
                "frequency_limit": payload.get("frequency_limit"),
            }
        return dict(payload)
