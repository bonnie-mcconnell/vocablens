from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.learning_roadmap_service import LearningRoadmapService
from vocablens.services.onboarding_service import OnboardingService
from vocablens.services.paywall_service import PaywallService
from vocablens.services.progress_service import ProgressService
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.subscription_service import SubscriptionService
from vocablens.services.user_experience_contracts import (
    CoreLoopSnapshot,
    DashboardProgress,
    EmotionHooksSnapshot,
    FrontendDashboardResponse,
    FrontendRecommendationsResponse,
    FrontendWeakAreasResponse,
    NextActionSnapshot,
    PaywallSnapshot,
    ProgressMetrics,
    ProgressPeriod,
    ProgressTrends,
    RetentionActionSnapshot,
    RetentionSnapshot,
    SessionConfigSnapshot,
    SkillBreakdown,
    SubscriptionSnapshot,
    UiDirectivesSnapshot,
    WeakAreaMistake,
    WeakAreasSnapshot,
    WeakSkillSnapshot,
)


class FrontendService:
    """
    Aggregates frontend-facing data to reduce client round trips.
    """

    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        learning_engine: LearningEngine,
        roadmap_service: LearningRoadmapService,
        retention_engine: RetentionEngine,
        subscription_service: SubscriptionService,
        paywall_service: PaywallService | None = None,
        progress_service: ProgressService | None = None,
        global_decision_engine: GlobalDecisionEngine | None = None,
        onboarding_service: OnboardingService | None = None,
    ):
        self._uow_factory = uow_factory
        self._learning_engine = learning_engine
        self._roadmap = roadmap_service
        self._retention = retention_engine
        self._subscriptions = subscription_service
        self._paywall = paywall_service
        self._progress = progress_service
        self._global_decision = global_decision_engine
        self._onboarding = onboarding_service

    async def dashboard(self, user_id: int) -> dict:
        async with self._uow_factory() as uow:
            vocab = await uow.vocab.list_all(user_id, limit=1000, offset=0)
            due = await uow.vocab.list_due(user_id)
            skills = await uow.skill_tracking.latest_scores(user_id)
            weak_clusters = await uow.knowledge_graph.get_weak_clusters(user_id)
            mistakes = await uow.mistake_patterns.top_patterns(user_id, limit=5)
            await uow.commit()

        features = await self._subscriptions.get_features(user_id)
        recommendation = await self._learning_engine.recommend(user_id)
        roadmap = await self._roadmap.generate_today_plan(user_id)
        retention = await self._retention.assess_user(user_id)
        paywall = await self._paywall.evaluate(user_id) if self._paywall else None
        decision = await self._global_decision.decide(user_id) if self._global_decision else None
        onboarding = await self._onboarding.plan(user_id) if self._onboarding else None
        progress = await self._progress.build_dashboard(user_id) if self._progress else self._fallback_progress(vocab, due)

        response = FrontendDashboardResponse(
            progress=DashboardProgress(
                vocabulary_total=progress["vocabulary_total"],
                due_reviews=progress["due_reviews"],
                streak=retention.current_streak,
                session_frequency=retention.session_frequency,
                retention_state=retention.state,
                metrics=ProgressMetrics(**progress["metrics"]),
                daily=ProgressPeriod(**progress["daily"]),
                weekly=ProgressPeriod(**progress["weekly"]),
                trends=ProgressTrends(**progress["trends"]),
                skill_breakdown=SkillBreakdown(**progress["skill_breakdown"]),
            ),
            core_loop=self._core_loop_snapshot(progress, recommendation),
            subscription=SubscriptionSnapshot(
                tier=features.tier,
                tutor_depth=features.tutor_depth,
                explanation_quality=features.explanation_quality,
                personalization_level=features.personalization_level,
                trial_active=features.trial_active,
                trial_ends_at=features.trial_ends_at.isoformat() if getattr(features.trial_ends_at, "isoformat", None) else None,
                usage_percent=features.usage_percent,
            ),
            paywall=self._paywall_snapshot(paywall, features),
            skills=skills,
            next_action=self._next_action_snapshot(recommendation),
            retention=RetentionSnapshot(
                state=retention.state,
                drop_off_risk=retention.drop_off_risk,
                actions=[
                    RetentionActionSnapshot(kind=action.kind, reason=action.reason, target=action.target)
                    for action in retention.suggested_actions
                ],
            ),
            weak_areas=WeakAreasSnapshot(
                clusters=weak_clusters,
                mistakes=[
                    WeakAreaMistake(
                        category=getattr(pattern, "category", None),
                        pattern=getattr(pattern, "pattern", None),
                        count=getattr(pattern, "count", None),
                    )
                    for pattern in mistakes
                ],
            ),
            ui=UiDirectivesSnapshot(**self._ui_directives(retention, paywall, progress, onboarding)),
            session_config=SessionConfigSnapshot(**self._session_config(decision, recommendation)),
            emotion_hooks=EmotionHooksSnapshot(**self._emotion_hooks(retention, paywall, progress, onboarding)),
            roadmap=roadmap,
        )
        return response.model_dump(mode="json")

    async def recommendations(self, user_id: int) -> dict:
        recommendation = await self._learning_engine.recommend(user_id)
        retention = await self._retention.assess_user(user_id)
        paywall = await self._paywall.evaluate(user_id) if self._paywall else None
        decision = await self._global_decision.decide(user_id) if self._global_decision else None
        onboarding = await self._onboarding.plan(user_id) if self._onboarding else None

        response = FrontendRecommendationsResponse(
            next_action=self._next_action_snapshot(recommendation),
            core_loop=self._core_loop_snapshot({}, recommendation),
            retention_actions=[
                RetentionActionSnapshot(kind=action.kind, reason=action.reason, target=action.target)
                for action in retention.suggested_actions
            ],
            paywall=self._paywall_snapshot(paywall),
            ui=UiDirectivesSnapshot(**self._ui_directives(retention, paywall, {}, onboarding)),
            session_config=SessionConfigSnapshot(**self._session_config(decision, recommendation)),
            emotion_hooks=EmotionHooksSnapshot(**self._emotion_hooks(retention, paywall, {}, onboarding)),
        )
        return response.model_dump(mode="json")

    async def paywall(self, user_id: int) -> dict:
        paywall = await self._paywall.evaluate(user_id) if self._paywall else None
        return self._paywall_snapshot(paywall).model_dump(mode="json")

    async def weak_areas(self, user_id: int) -> dict:
        async with self._uow_factory() as uow:
            weak_clusters = await uow.knowledge_graph.get_weak_clusters(user_id)
            skills = await uow.skill_tracking.latest_scores(user_id)
            mistakes = await uow.mistake_patterns.top_patterns(user_id, limit=5)
            await uow.commit()

        sorted_skills = sorted(skills.items(), key=lambda item: item[1])
        response = FrontendWeakAreasResponse(
            weak_skills=[WeakSkillSnapshot(skill=name, score=score) for name, score in sorted_skills[:3]],
            weak_clusters=weak_clusters,
            mistake_patterns=[
                WeakAreaMistake(
                    category=getattr(pattern, "category", None),
                    pattern=getattr(pattern, "pattern", None),
                    count=getattr(pattern, "count", None),
                )
                for pattern in mistakes
            ],
        )
        return response.model_dump(mode="json")

    def meta(self, *, source: str, difficulty: str | None = None, next_action: str | None = None) -> dict:
        meta = {
            "source": source,
            "generated_at": utc_now().isoformat(),
        }
        if difficulty:
            meta["difficulty"] = difficulty
        if next_action:
            meta["next_action"] = next_action
        return meta

    def _fallback_progress(self, vocab, due) -> dict:
        return {
            "vocabulary_total": len(vocab),
            "due_reviews": len(due),
            "metrics": {},
            "daily": {},
            "weekly": {},
            "trends": {},
            "skill_breakdown": {},
            "core_loop": {
                "focus_skill": "vocabulary",
                "review_cadence": "light_review_then_new",
                "recommended_session_count": 1,
                "review_window_minutes": 30,
                "recent_improvement_score": None,
            },
        }

    def _next_action_snapshot(self, recommendation) -> NextActionSnapshot:
        return NextActionSnapshot(
            action=recommendation.action,
            target=recommendation.target,
            reason=recommendation.reason,
            difficulty=recommendation.lesson_difficulty,
            content_type=recommendation.content_type,
        )

    def _paywall_snapshot(self, paywall, features=None) -> PaywallSnapshot:
        if not paywall:
            return PaywallSnapshot(
                show=False,
                type=None,
                reason=None,
                usage_percent=getattr(features, "usage_percent", 0) if features else 0,
                allow_access=True,
                trial_active=getattr(features, "trial_active", False) if features else False,
                trial_ends_at=features.trial_ends_at.isoformat() if features and getattr(features.trial_ends_at, "isoformat", None) else None,
            )
        return PaywallSnapshot(
            show=paywall.show_paywall,
            type=paywall.paywall_type,
            reason=paywall.reason,
            usage_percent=paywall.usage_percent,
            allow_access=paywall.allow_access,
            trial_active=paywall.trial_active,
            trial_ends_at=paywall.trial_ends_at.isoformat() if getattr(paywall.trial_ends_at, "isoformat", None) else None,
            request_usage_percent=getattr(paywall, "request_usage_percent", None),
            token_usage_percent=getattr(paywall, "token_usage_percent", None),
            trial_tier=getattr(paywall, "trial_tier", None),
        )

    def _core_loop_snapshot(self, progress: dict, recommendation) -> CoreLoopSnapshot:
        core_loop = progress.get("core_loop", {}) if progress else {}
        return CoreLoopSnapshot(
            focus_skill=str(getattr(recommendation, "skill_focus", None) or core_loop.get("focus_skill") or "vocabulary"),
            focus_target=getattr(recommendation, "target", None),
            goal_label=str(getattr(recommendation, "goal_label", None) or "Finish one focused round cleanly"),
            review_cadence=str(core_loop.get("review_cadence") or "light_review_then_new"),
            recommended_session_count=int(core_loop.get("recommended_session_count") or 1),
            review_window_minutes=int(getattr(recommendation, "review_window_minutes", None) or core_loop.get("review_window_minutes") or 30),
            recent_improvement_score=core_loop.get("recent_improvement_score"),
        )

    def _ui_directives(self, retention, paywall, progress: dict, onboarding) -> dict:
        daily = progress.get("daily", {}) if progress else {}
        progress_jump = int(daily.get("words_learned", 0) or 0) + int(daily.get("reviews_completed", 0) or 0)
        onboarding_stage = getattr(onboarding, "stage", None)
        return {
            "show_streak_animation": retention.current_streak > 0 or bool(getattr(onboarding, "habit_hook", {}).get("show_streak_starting", False)),
            "show_progress_boost": progress_jump > 0 or bool(getattr(onboarding, "habit_hook", {}).get("show_progress_jump", False)),
            "show_paywall": bool(paywall.show_paywall) if paywall else False,
            "show_celebration": onboarding_stage in {"first_success", "wow_moment", "habit_hook"},
        }

    def _session_config(self, decision, recommendation) -> dict:
        primary = getattr(decision, "primary_action", None)
        mode = (
            "chat" if primary == "conversation"
            else "review" if primary == "review"
            else "drill" if primary in {"learn", "upsell", "nudge"} and getattr(recommendation, "action", "") != "conversation_drill"
            else "chat"
        )
        session_type = getattr(decision, "session_type", "quick")
        session_length = 3 if session_type == "quick" else 8 if session_type == "deep" else 1
        resolved_mode = (
            "review" if getattr(recommendation, "action", None) == "review_word"
            else "chat" if getattr(recommendation, "action", None) == "conversation_drill"
            else mode
        )
        return {
            "session_length": session_length,
            "difficulty": getattr(decision, "difficulty_level", getattr(recommendation, "lesson_difficulty", "medium")),
            "mode": resolved_mode,
        }

    def _emotion_hooks(self, retention, paywall, progress: dict, onboarding) -> dict:
        daily = progress.get("daily", {}) if progress else {}
        progress_gain = int(daily.get("words_learned", 0) or 0) + int(daily.get("reviews_completed", 0) or 0)
        onboarding_stage = getattr(onboarding, "stage", None)
        encouragement = (
            "You are one step away from your first win."
            if onboarding_stage in {"onboarding_start", "guided_learning"}
            else "Your first win is in, keep the momentum going."
            if onboarding_stage in {"first_success", "wow_moment", "habit_hook"}
            else f"Your {retention.current_streak}-day streak is building momentum."
            if retention.current_streak > 0
            else "You are making steady progress."
        )
        urgency = (
            "Finish this quick session before your streak cools off."
            if retention.state in {"at-risk", "churned"}
            else f"{getattr(paywall, 'usage_percent', 0)}% of today's usage is already used."
            if paywall and getattr(paywall, "show_paywall", False)
            else ""
        )
        reward = (
            "Nice start, your streak just began."
            if onboarding_stage == "habit_hook"
            else "That was a strong first success."
            if onboarding_stage in {"first_success", "wow_moment"}
            else f"Complete this session to add {progress_gain or 1} visible progress step(s)."
        )
        return {
            "encouragement_message": encouragement,
            "urgency_message": urgency,
            "reward_message": reward,
        }
