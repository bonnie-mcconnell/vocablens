from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.addiction_engine import AddictionEngine
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.notification_decision_engine import NotificationDecisionEngine
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


@dataclass(frozen=True)
class OnboardingFlowResponse:
    current_step: OnboardingStep
    onboarding_state: dict
    ui_directives: dict
    messaging: dict
    next_action: dict


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

    async def start(self, user_id: int) -> dict:
        state = await self._load_state(user_id)
        if state is None:
            state = self._default_state()
            await self._persist_state(user_id, state, event_type="onboarding_started")
        return (await self._build_response(user_id, state)).__dict__

    async def next(self, user_id: int, payload: dict | None = None) -> dict:
        payload = dict(payload or {})
        state = await self._load_state(user_id) or self._default_state()
        current_step = state["current_step"]

        if current_step == "identity_selection":
            motivation = str(payload.get("motivation") or "").strip().lower()
            if motivation:
                state["identity"] = {"motivation": motivation}
                state["steps_completed"].append("identity_selection")
                state["current_step"] = "personalization"

        elif current_step == "personalization":
            updates = {
                "skill_level": str(payload.get("skill_level") or "").strip().lower() or None,
                "daily_goal": int(payload.get("daily_goal") or 0) or None,
                "learning_intent": str(payload.get("learning_intent") or "").strip().lower() or None,
            }
            if all(updates.values()):
                state["personalization"] = updates
                await self._persist_preferences(
                    user_id=user_id,
                    skill_level=updates["skill_level"],
                    learning_intent=updates["learning_intent"],
                )
                state["steps_completed"].append("personalization")
                state["current_step"] = "instant_wow_moment"

        elif current_step == "instant_wow_moment":
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

        elif current_step == "progress_illusion":
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
            if paywall.show_paywall and paywall.allow_access and (wow_score >= 0.65 or self._engagement_threshold_met(state)):
                state["paywall"] = self._paywall_payload(paywall)
                state["current_step"] = "soft_paywall"
            else:
                state["paywall"] = self._paywall_payload(paywall)
                state["current_step"] = "habit_lock_in"

        elif current_step == "soft_paywall":
            accepted_trial = bool(payload.get("accept_trial"))
            skipped = bool(payload.get("skip_paywall"))
            paywall = state.get("paywall", {})
            if accepted_trial and paywall.get("trial_recommended"):
                await self._paywall.start_trial(user_id, paywall.get("trial_days"))
                paywall["trial_started"] = True
            if accepted_trial or skipped or not paywall.get("show"):
                state["steps_completed"].append("soft_paywall")
                state["current_step"] = "habit_lock_in"

        elif current_step == "habit_lock_in":
            preferred_time = payload.get("preferred_time_of_day")
            preferred_channel = str(payload.get("preferred_channel") or "push").strip().lower()
            frequency_limit = int(payload.get("frequency_limit") or 1)
            if preferred_time is not None:
                await self._persist_habit_preferences(
                    user_id=user_id,
                    preferred_time_of_day=int(preferred_time),
                    preferred_channel=preferred_channel,
                    frequency_limit=frequency_limit,
                )
                lifecycle = await self._lifecycle.evaluate(user_id)
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

        await self._persist_state(user_id, state, event_type="onboarding_state_updated")
        if state["current_step"] == "completed":
            await self._persist_state(user_id, state, event_type="onboarding_completed")
        return (await self._build_response(user_id, state)).__dict__

    async def _build_response(self, user_id: int, state: dict) -> OnboardingFlowResponse:
        lifecycle = await self._lifecycle.evaluate(user_id)
        current_step = state["current_step"]
        return OnboardingFlowResponse(
            current_step=current_step,
            onboarding_state=state,
            ui_directives=self._ui_directives(current_step, state),
            messaging=self._messaging(current_step, state, lifecycle),
            next_action=self._next_action(current_step, state, lifecycle),
        )

    async def _load_state(self, user_id: int) -> dict | None:
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=200)
            await uow.commit()
        for event in events:
            if getattr(event, "event_type", None) in {"onboarding_state_updated", "onboarding_started", "onboarding_completed"}:
                payload = getattr(event, "payload", None)
                if isinstance(payload, dict) and payload.get("state"):
                    return dict(payload["state"])
        return None

    async def _persist_state(self, user_id: int, state: dict, *, event_type: str) -> None:
        snapshot = deepcopy(state)
        async with self._uow_factory() as uow:
            await uow.events.record(
                user_id=user_id,
                event_type=event_type,
                payload={
                    "state": snapshot,
                    "current_step": snapshot["current_step"],
                    "updated_at": utc_now().isoformat(),
                },
            )
            await uow.commit()

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

    def _default_state(self) -> dict:
        return {
            "current_step": "identity_selection",
            "steps_completed": [],
            "identity": {},
            "personalization": {},
            "wow": {"score": 0.0, "qualifies": False, "understood_percent": 0.0, "triggers": {}},
            "early_success_score": 0.0,
            "progress_illusion": {},
            "paywall": {"show": False},
            "habit_lock_in": {},
        }

    def _engagement_threshold_met(self, state: dict) -> bool:
        session_snapshot = state.get("wow", {}).get("session_snapshot", {}) or {}
        return (
            int(session_snapshot.get("session_turn_count", 0) or 0) >= 4
            or int(session_snapshot.get("correction_feedback_count", 0) or 0) >= 2
            or int(session_snapshot.get("reply_length", 0) or 0) >= 100
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

    def _ui_directives(self, current_step: str, state: dict) -> dict:
        return {
            "show_identity_picker": current_step == "identity_selection",
            "show_personalization_form": current_step == "personalization",
            "show_wow_meter": current_step == "instant_wow_moment",
            "show_progress_boost": current_step in {"progress_illusion", "habit_lock_in", "completed"},
            "show_streak_animation": current_step in {"progress_illusion", "habit_lock_in", "completed"},
            "show_relative_ranking": current_step in {"progress_illusion", "completed"},
            "show_paywall": current_step == "soft_paywall" and bool(state.get("paywall", {}).get("show")),
            "show_trial_offer": current_step == "soft_paywall" and bool(state.get("paywall", {}).get("trial_recommended")),
            "show_notification_scheduler": current_step == "habit_lock_in",
        }

    def _messaging(self, current_step: str, state: dict, lifecycle) -> dict:
        wow = state.get("wow", {})
        progress = state.get("progress_illusion", {})
        habit = state.get("habit_lock_in", {})
        encouragement = {
            "identity_selection": "Choose the version of yourself you want to become.",
            "personalization": "We’ll tune the first session so success feels immediate.",
            "instant_wow_moment": f"You understood {wow.get('understood_percent', 0.0)}% so far. One more strong turn should lock this in.",
            "progress_illusion": f"You just banked {progress.get('xp_gain', 0)} XP and opened a streak.",
            "soft_paywall": "You have already felt the value. Unlock more without losing momentum.",
            "habit_lock_in": "Pick the moment you want this habit to happen every day.",
            "completed": "Your first learning ritual is set.",
        }.get(current_step, "Keep going.")
        urgency = (
            f"Stage: {lifecycle.stage}. Keep the first-session momentum while it is still warm."
            if current_step in {"progress_illusion", "soft_paywall", "habit_lock_in"}
            else ""
        )
        reward = (
            habit.get("ritual", {}).get("daily_ritual_message")
            or state.get("progress_illusion", {}).get("identity", {}).get("message")
            or "A visible win is coming in this step."
        )
        return {
            "encouragement_message": encouragement,
            "urgency_message": urgency,
            "reward_message": reward,
        }

    def _next_action(self, current_step: str, state: dict, lifecycle) -> dict:
        identity = state.get("identity", {})
        personalization = state.get("personalization", {})
        if current_step == "identity_selection":
            return {
                "action": "select_identity",
                "target": ["fluency", "travel", "confidence", "career"],
                "reason": "Motivation determines how the rest of onboarding is framed.",
            }
        if current_step == "personalization":
            return {
                "action": "set_preferences",
                "target": {
                    "skill_level": personalization.get("skill_level"),
                    "daily_goal": personalization.get("daily_goal"),
                    "learning_intent": personalization.get("learning_intent"),
                },
                "reason": f"Tailor the first win around {identity.get('motivation', 'your goal')}.",
            }
        if current_step == "instant_wow_moment":
            mode = "micro_lesson" if personalization.get("learning_intent") in {"grammar", "vocabulary"} else "tutor_interaction"
            return {
                "action": mode,
                "target": personalization.get("learning_intent", "conversation"),
                "reason": "The fastest route to activation is one guided success.",
            }
        if current_step == "progress_illusion":
            return {
                "action": "reveal_progress",
                "target": state.get("progress_illusion", {}),
                "reason": "Visible progress and ranking increase the chance of a second session.",
            }
        if current_step == "soft_paywall":
            return {
                "action": "offer_trial" if state.get("paywall", {}).get("trial_recommended") else "continue_free",
                "target": state.get("paywall", {}),
                "reason": "Only show the paywall once the wow moment or early engagement threshold is real.",
            }
        if current_step == "habit_lock_in":
            return {
                "action": "schedule_notification",
                "target": {"preferred_time_of_day": None, "preferred_channel": "push"},
                "reason": "Habit lock-in works best when the reminder time is chosen explicitly.",
            }
        return {
            "action": "go_to_dashboard",
            "target": lifecycle.stage,
            "reason": "Onboarding is complete and the regular lifecycle can take over.",
        }
