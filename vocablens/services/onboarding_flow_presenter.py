from __future__ import annotations

from dataclasses import dataclass

from vocablens.services.report_models import (
    OnboardingFlowMessageSet,
    OnboardingNextAction,
    OnboardingUiDirectives,
)


@dataclass(frozen=True)
class OnboardingFlowView:
    current_step: str
    onboarding_state: dict
    ui_directives: OnboardingUiDirectives
    messaging: OnboardingFlowMessageSet
    next_action: OnboardingNextAction


class OnboardingFlowPresenter:
    def build(self, *, state: dict, lifecycle_stage: str) -> OnboardingFlowView:
        current_step = state["current_step"]
        return OnboardingFlowView(
            current_step=current_step,
            onboarding_state=state,
            ui_directives=self._ui_directives(current_step, state),
            messaging=self._messaging(current_step, state, lifecycle_stage),
            next_action=self._next_action(current_step, state, lifecycle_stage),
        )

    def _ui_directives(self, current_step: str, state: dict) -> OnboardingUiDirectives:
        return OnboardingUiDirectives(
            show_identity_picker=current_step == "identity_selection",
            show_personalization_form=current_step == "personalization",
            show_wow_meter=current_step == "instant_wow_moment",
            show_progress_boost=current_step in {"progress_illusion", "habit_lock_in", "completed"},
            show_streak_animation=current_step in {"progress_illusion", "habit_lock_in", "completed"},
            show_relative_ranking=current_step in {"progress_illusion", "completed"},
            show_paywall=current_step == "soft_paywall" and bool(state.get("paywall", {}).get("show")),
            show_trial_offer=current_step == "soft_paywall" and bool(state.get("paywall", {}).get("trial_recommended")),
            show_notification_scheduler=current_step == "habit_lock_in",
        )

    def _messaging(self, current_step: str, state: dict, lifecycle_stage: str) -> OnboardingFlowMessageSet:
        wow = state.get("wow", {})
        progress = state.get("progress_illusion", {})
        habit = state.get("habit_lock_in", {})
        encouragement_map = {
            "identity_selection": "Choose the version of yourself you want to become.",
            "personalization": "We will tune the first session so an early win is realistic.",
            "instant_wow_moment": f"You understood {wow.get('understood_percent', 0.0)}% of that round. One more clean turn should make the pattern stick.",
            "progress_illusion": f"You picked up {progress.get('xp_gain', 0)} XP and started a streak.",
            "soft_paywall": "The user has seen the core value. This is the point to show the upgrade path.",
            "habit_lock_in": "Pick the moment you want this habit to happen every day.",
            "completed": "The first routine is in place.",
        }
        urgency = ""
        if current_step in {"progress_illusion", "soft_paywall", "habit_lock_in"}:
            urgency = f"Lifecycle stage: {lifecycle_stage}. Move while the first-session context is still fresh."
        reward_message = habit.get("ritual", {}).get("daily_ritual_message")
        if not reward_message:
            reward_message = state.get("progress_illusion", {}).get("identity", {}).get("message")
        if not reward_message:
            reward_message = "This step should end with a visible gain."
        return OnboardingFlowMessageSet(
            encouragement_message=encouragement_map.get(current_step, "Continue to the next step."),
            urgency_message=urgency,
            reward_message=reward_message,
        )

    def _next_action(self, current_step: str, state: dict, lifecycle_stage: str) -> OnboardingNextAction:
        identity = state.get("identity", {})
        personalization = state.get("personalization", {})
        if current_step == "identity_selection":
            return OnboardingNextAction(
                action="select_identity",
                target=["fluency", "travel", "confidence", "career"],
                reason="Motivation shapes the rest of the onboarding flow.",
            )
        if current_step == "personalization":
            return OnboardingNextAction(
                action="set_preferences",
                target={
                    "skill_level": personalization.get("skill_level"),
                    "daily_goal": personalization.get("daily_goal"),
                    "learning_intent": personalization.get("learning_intent"),
                },
                reason=f"Tailor the first win around {identity.get('motivation', 'the chosen goal')}.",
            )
        if current_step == "instant_wow_moment":
            mode = "micro_lesson" if personalization.get("learning_intent") in {"grammar", "vocabulary"} else "tutor_interaction"
            return OnboardingNextAction(
                action=mode,
                target=personalization.get("learning_intent", "conversation"),
                reason="The fastest route to activation is one guided success.",
            )
        if current_step == "progress_illusion":
            return OnboardingNextAction(
                action="reveal_progress",
                target=state.get("progress_illusion", {}),
                reason="Make the early gains explicit before asking for anything else.",
            )
        if current_step == "soft_paywall":
            return OnboardingNextAction(
                action="offer_trial" if state.get("paywall", {}).get("trial_recommended") else "continue_free",
                target=state.get("paywall", {}),
                reason="Show the paid path only after the user has seen real value.",
            )
        if current_step == "habit_lock_in":
            return OnboardingNextAction(
                action="schedule_notification",
                target={"preferred_time_of_day": None, "preferred_channel": "push"},
                reason="The reminder works best when the user chooses the time explicitly.",
            )
        return OnboardingNextAction(
            action="go_to_dashboard",
            target=lifecycle_stage,
            reason="Onboarding is complete and the regular product flow can take over.",
        )
