from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.progress_service import ProgressService
from vocablens.services.report_models import (
    OnboardingFirstWin,
    OnboardingGuidedStep,
    OnboardingHabitHook,
    OnboardingWowPayload,
)
from vocablens.services.wow_engine import WowEngine, WowScore

OnboardingStage = Literal[
    "onboarding_start",
    "guided_learning",
    "first_success",
    "wow_moment",
    "habit_hook",
]


@dataclass(frozen=True)
class OnboardingPlan:
    stage: OnboardingStage
    goals_prompt: str | None
    recommended_difficulty: str
    primary_action: str
    guided_flow: list[OnboardingGuidedStep]
    first_win: OnboardingFirstWin
    wow: OnboardingWowPayload
    habit_hook: OnboardingHabitHook


class OnboardingService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        progress_service: ProgressService,
        wow_engine: WowEngine,
        global_decision_engine: GlobalDecisionEngine,
    ):
        self._uow_factory = uow_factory
        self._progress = progress_service
        self._wow = wow_engine
        self._global = global_decision_engine

    async def plan(
        self,
        user_id: int,
        *,
        goals: list[str] | None = None,
        session_snapshot: dict | None = None,
    ) -> OnboardingPlan:
        progress = await self._progress.build_dashboard(user_id)
        decision = await self._global.decide(user_id)
        user_state = None
        if hasattr(self._global, "user_experience_state"):
            user_state = await self._global.user_experience_state(user_id)
        sessions = await self._session_count(user_id)
        wow = await self._wow_score(user_id, session_snapshot)

        stage = self._stage(
            sessions=sessions,
            goals=goals,
            progress=progress,
            wow=wow,
            lifecycle_stage=getattr(user_state, "lifecycle_stage", None),
        )
        recommended_difficulty = self._difficulty(decision.difficulty_level, stage, goals)
        guided_flow = self._guided_flow(goals, recommended_difficulty, decision.primary_action)
        first_win = self._first_win(progress, decision.primary_action)
        habit_hook = self._habit_hook(progress, decision.engagement_action, wow)

        return OnboardingPlan(
            stage=stage,
            goals_prompt=None if goals else "What do you want to do first: travel, conversation, grammar, or vocabulary?",
            recommended_difficulty=recommended_difficulty,
            primary_action=decision.primary_action,
            guided_flow=guided_flow,
            first_win=first_win,
            wow=OnboardingWowPayload(
                score=wow.score,
                qualifies=wow.qualifies,
                triggered=stage in {"wow_moment", "habit_hook"},
            ),
            habit_hook=habit_hook,
        )

    async def _session_count(self, user_id: int) -> int:
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=100)
            await uow.commit()
        return sum(1 for event in events if getattr(event, "event_type", None) == "session_started")

    async def _wow_score(self, user_id: int, session_snapshot: dict | None) -> WowScore:
        if session_snapshot is None:
            return WowScore(
                score=0.0,
                tutor_interaction_score=0.0,
                accuracy_improvement_score=0.0,
                engagement_score=0.0,
                baseline_accuracy=0.5,
                current_accuracy=0.0,
                qualifies=False,
                triggers={"paywall": False, "trial": False, "upsell": False},
            )
        return await self._wow.score_session(
            user_id,
            tutor_mode=bool(session_snapshot.get("tutor_mode", True)),
            correction_feedback_count=int(session_snapshot.get("correction_feedback_count", 0) or 0),
            new_words_count=int(session_snapshot.get("new_words_count", 0) or 0),
            grammar_mistake_count=int(session_snapshot.get("grammar_mistake_count", 0) or 0),
            session_turn_count=int(session_snapshot.get("session_turn_count", 0) or 0),
            reply_length=int(session_snapshot.get("reply_length", 0) or 0),
        )

    def _stage(
        self,
        *,
        sessions: int,
        goals: list[str] | None,
        progress: dict,
        wow: WowScore,
        lifecycle_stage: str | None = None,
    ) -> OnboardingStage:
        if wow.qualifies:
            daily = progress.get("daily", {})
            progress_jump = (
                int(daily.get("words_learned", 0) or 0) > 0
                or int(daily.get("reviews_completed", 0) or 0) > 0
            )
            return "habit_hook" if progress_jump else "wow_moment"
        if lifecycle_stage in {"new_user", "activating"}:
            if not goals:
                return "onboarding_start"
            return "guided_learning"
        if not goals and sessions <= 1:
            return "onboarding_start"
        accuracy = float(progress.get("metrics", {}).get("accuracy_rate", 0.0) or 0.0)
        if accuracy >= 70.0:
            return "first_success"
        return "guided_learning"

    def _difficulty(self, base_difficulty: str, stage: OnboardingStage, goals: list[str] | None) -> str:
        if stage in {"onboarding_start", "guided_learning", "first_success"}:
            return "easy"
        if goals and any(goal.lower() in {"travel", "conversation"} for goal in goals):
            return "medium"
        return base_difficulty

    def _guided_flow(self, goals: list[str] | None, difficulty: str, primary_action: str) -> list[OnboardingGuidedStep]:
        chosen_goal = goals[0] if goals else "conversation"
        return [
            OnboardingGuidedStep(
                type="goal_capture",
                message=f"Start with a {chosen_goal}-oriented path.",
            ),
            OnboardingGuidedStep(
                type="adaptive_difficulty",
                message=f"Set first session difficulty to {difficulty}.",
            ),
            OnboardingGuidedStep(
                type="early_success_path",
                message=f"Open with a {primary_action} step designed to land an early correct answer.",
            ),
        ]

    def _first_win(self, progress: dict, primary_action: str) -> OnboardingFirstWin:
        accuracy = float(progress.get("metrics", {}).get("accuracy_rate", 0.0) or 0.0)
        return OnboardingFirstWin(
            ensure_success=True,
            target_accuracy=max(70.0, accuracy),
            message=f"Serve a guided {primary_action} step so the user gets something right quickly.",
        )

    def _habit_hook(self, progress: dict, engagement_action: str, wow: WowScore) -> OnboardingHabitHook:
        daily = progress.get("daily", {})
        progress_jump = int(daily.get("words_learned", 0) or 0) + int(daily.get("reviews_completed", 0) or 0)
        return OnboardingHabitHook(
            show_streak_starting=wow.qualifies,
            show_progress_jump=progress_jump > 0 or wow.qualifies,
            engagement_action=engagement_action,
            message="Show the streak starting and make the first progress jump visible.",
        )
