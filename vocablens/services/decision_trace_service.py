from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy import select

from vocablens.domain.errors import NotFoundError
from vocablens.infrastructure.db.models import (
    ExperimentAssignmentORM,
    LifecycleTransitionORM,
    OnboardingFlowStateORM,
    SubscriptionORM,
    UserEngagementStateORM,
    UserLifecycleStateORM,
    UserLearningStateORM,
    UserMonetizationStateORM,
    UserProfileORM,
    UserProgressStateORM,
)
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.adaptive_paywall_policy import AdaptivePaywallPolicy
from vocablens.services.lifecycle_stage_policy import LifecycleSnapshot, classify_lifecycle_stage
from vocablens.services.monetization_policy import MonetizationPolicy
from vocablens.services.report_models import LifecycleAction
from vocablens.services.retention_engine import RetentionAssessment, RetentionEngine


class DecisionTraceService:
    _LIFECYCLE_EVENT_TYPES = {
        "onboarding_started",
        "onboarding_state_updated",
        "onboarding_completed",
        "session_started",
        "session_ended",
        "paywall_viewed",
        "upgrade_clicked",
        "upgrade_completed",
        "subscription_upgraded",
    }
    _MONETIZATION_EVENT_TYPES = {
        "onboarding_state_updated",
        "onboarding_completed",
        "paywall_viewed",
        "upgrade_clicked",
        "upgrade_completed",
        "subscription_upgraded",
    }

    def __init__(self, uow_factory: type[UnitOfWork], business_metrics_service=None):
        self._uow_factory = uow_factory
        self._business_metrics = business_metrics_service
        self._retention_policy = RetentionEngine()
        self._adaptive_paywall_policy = AdaptivePaywallPolicy()
        self._monetization_policy = MonetizationPolicy()

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        trace_type: str | None = None,
        reference_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        normalized_limit = max(1, min(limit, 200))
        async with self._uow_factory() as uow:
            traces = await uow.decision_traces.list_recent(
                user_id=user_id,
                trace_type=trace_type,
                reference_id=reference_id,
                limit=normalized_limit,
            )
            await uow.commit()

        return {"traces": [self._trace_payload(trace) for trace in traces]}

    async def session_detail(self, reference_id: str) -> dict:
        async with self._uow_factory() as uow:
            session = await uow.learning_sessions.get_by_session_id(reference_id)
            if session is None:
                raise NotFoundError("Session not found")
            attempts = await uow.learning_sessions.list_attempts(session_id=reference_id)
            traces = await uow.decision_traces.list_recent(
                user_id=session.user_id,
                reference_id=reference_id,
                limit=200,
            )
            events = await uow.events.list_by_user(session.user_id, limit=1000)
            await uow.commit()

        related_events = []
        for event in events:
            payload = dict(getattr(event, "payload", {}) or {})
            if payload.get("session_id") != reference_id:
                continue
            related_events.append(self._event_payload(event))
        related_events.sort(key=lambda item: (item["created_at"], item["id"]))
        evaluation = self._session_evaluation_payload(
            self._latest_trace(traces, trace_type="session_evaluation")
        )

        return {
            "session": self._session_payload(session),
            "evaluation": evaluation,
            "attempts": [self._attempt_payload(attempt) for attempt in attempts],
            "events": related_events,
            "traces": [self._trace_payload(trace) for trace in traces],
        }

    async def onboarding_detail(self, user_id: int) -> dict:
        reference_id = f"onboarding:{user_id}"
        async with self._uow_factory() as uow:
            state = await uow.onboarding_states.get(user_id)
            if state is None:
                raise NotFoundError("Onboarding state not found")
            traces = await uow.decision_traces.list_recent(
                user_id=user_id,
                reference_id=reference_id,
                limit=200,
            )
            events = await uow.events.list_by_user(user_id, limit=1000)
            await uow.commit()

        related_events = []
        for event in events:
            event_type = str(getattr(event, "event_type", "") or "")
            if not event_type.startswith("onboarding_"):
                continue
            related_events.append(self._event_payload(event))
        related_events.sort(key=lambda item: (item["created_at"], item["id"]))

        onboarding_traces = [
            self._trace_payload(trace)
            for trace in traces
            if str(trace.trace_type).startswith("onboarding_")
        ]
        latest_transition = self._onboarding_transition_payload(
            self._latest_trace(traces, trace_type="onboarding_transition")
        )
        paywall_entry = self._onboarding_paywall_payload(
            self._latest_trace(traces, trace_type="onboarding_paywall_entry")
        )

        return {
            "state": self._onboarding_state_payload(state),
            "latest_transition": latest_transition,
            "paywall_entry": paywall_entry,
            "events": related_events,
            "traces": onboarding_traces,
        }

    async def lifecycle_detail(self, user_id: int) -> dict:
        snapshot = await self._user_snapshot(user_id)
        retention = self._retention_payload(snapshot)
        paywall = await self._adaptive_paywall_payload(snapshot)
        lifecycle_trace = self._latest_trace(snapshot["traces"], trace_type="lifecycle_decision")
        lifecycle = self._lifecycle_payload(
            snapshot,
            retention,
            paywall=paywall,
            decision_trace=lifecycle_trace,
        )
        relevant_events = self._filtered_events(
            snapshot["events"],
            allowed_types=self._LIFECYCLE_EVENT_TYPES,
        )
        relevant_traces = self._filtered_traces(
            snapshot["traces"],
            predicate=lambda trace: str(trace.trace_type).startswith("onboarding_")
            or str(trace.trace_type).startswith("lifecycle_")
            or (
                str(getattr(trace, "trace_type", "") or "") == "notification_selection"
                and str(getattr(trace, "reference_id", "") or "") == f"lifecycle:{user_id}"
            ),
        )
        return {
            "onboarding_state": self._onboarding_state_orm_payload(snapshot["onboarding_state"]),
            "learning_state": self._learning_state_payload(snapshot["learning_state"]),
            "engagement_state": self._engagement_state_payload(snapshot["engagement_state"]),
            "lifecycle_state": self._lifecycle_state_payload(snapshot["lifecycle_state"]),
            "lifecycle_transitions": [
                self._lifecycle_transition_payload(item) for item in snapshot["lifecycle_transitions"]
            ],
            "profile": self._profile_payload(snapshot["profile"]),
            "retention": retention,
            "lifecycle": lifecycle,
            "adaptive_paywall": paywall,
            "events": relevant_events,
            "traces": relevant_traces,
        }

    async def lifecycle_report(self, user_id: int) -> dict:
        detail = await self.lifecycle_detail(user_id)
        traces = list(detail.get("traces", []))
        events = list(detail.get("events", []))
        transitions = list(detail.get("lifecycle_transitions", []))
        return {
            "detail": detail,
            "latest_decisions": {
                "lifecycle_decision": self._latest_trace_payload_from_dicts(traces, trace_type="lifecycle_decision"),
                "lifecycle_action_plan": self._latest_trace_payload_from_dicts(traces, trace_type="lifecycle_action_plan"),
                "notification_selection": self._latest_trace_payload_from_dicts(traces, trace_type="notification_selection"),
                "latest_transition": transitions[0] if transitions else None,
            },
            "event_summary": self._event_summary_payload(events),
            "trace_summary": self._trace_summary_payload(traces),
        }

    async def monetization_detail(self, user_id: int, *, geography: str | None = None) -> dict:
        snapshot = await self._user_snapshot(user_id)
        retention = self._retention_payload(snapshot)
        paywall = await self._adaptive_paywall_payload(snapshot)
        lifecycle_trace = self._latest_trace(snapshot["traces"], trace_type="lifecycle_decision")
        lifecycle = self._lifecycle_payload(
            snapshot,
            retention,
            paywall=paywall,
            decision_trace=lifecycle_trace,
        )
        monetization_trace = self._latest_trace(snapshot["traces"], trace_type="monetization_decision")
        monetization = await self._monetization_payload(
            snapshot,
            lifecycle=lifecycle,
            paywall=paywall,
            geography=geography,
            decision_trace=monetization_trace,
        )
        relevant_events = self._filtered_events(
            snapshot["events"],
            allowed_types=self._MONETIZATION_EVENT_TYPES,
        )
        relevant_traces = self._filtered_traces(
            snapshot["traces"],
            predicate=lambda trace: str(trace.trace_type).startswith("onboarding_")
            or str(trace.trace_type).startswith("monetization_")
            or str(trace.trace_type).startswith("lifecycle_"),
        )
        return {
            "onboarding_state": self._onboarding_state_orm_payload(snapshot["onboarding_state"]),
            "learning_state": self._learning_state_payload(snapshot["learning_state"]),
            "engagement_state": self._engagement_state_payload(snapshot["engagement_state"]),
            "progress_state": self._progress_state_payload(snapshot["progress_state"]),
            "profile": self._profile_payload(snapshot["profile"]),
            "subscription": self._subscription_payload(snapshot["subscription"]),
            "monetization_state": self._monetization_state_payload(snapshot["monetization_state"]),
            "experiments": snapshot["experiments"],
            "retention": retention,
            "lifecycle": lifecycle,
            "adaptive_paywall": paywall,
            "monetization": monetization,
            "monetization_events": [self._monetization_event_payload(item) for item in snapshot["monetization_events"]],
            "events": relevant_events,
            "traces": relevant_traces,
        }

    async def monetization_report(self, user_id: int, *, geography: str | None = None) -> dict:
        detail = await self.monetization_detail(user_id, geography=geography)
        traces = list(detail.get("traces", []))
        events = list(detail.get("events", []))
        monetization_events = list(detail.get("monetization_events", []))
        return {
            "detail": detail,
            "latest_decisions": {
                "monetization_decision": self._latest_trace_payload_from_dicts(traces, trace_type="monetization_decision"),
                "lifecycle_decision": self._latest_trace_payload_from_dicts(traces, trace_type="lifecycle_decision"),
                "notification_selection": self._latest_trace_payload_from_dicts(traces, trace_type="notification_selection"),
                "latest_monetization_event": monetization_events[0] if monetization_events else None,
            },
            "event_summary": self._event_summary_payload(events),
            "trace_summary": self._trace_summary_payload(traces),
            "monetization_event_summary": self._event_summary_payload(monetization_events),
        }

    def _trace_payload(self, trace) -> dict[str, Any]:
        return {
            "id": trace.id,
            "user_id": trace.user_id,
            "trace_type": trace.trace_type,
            "source": trace.source,
            "reference_id": trace.reference_id,
            "policy_version": trace.policy_version,
            "inputs": trace.inputs,
            "outputs": trace.outputs,
            "reason": trace.reason,
            "created_at": trace.created_at.isoformat(),
        }

    def _session_payload(self, session) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "status": session.status,
            "contract_version": session.contract_version,
            "duration_seconds": session.duration_seconds,
            "mode": session.mode,
            "weak_area": session.weak_area,
            "lesson_target": session.lesson_target,
            "goal_label": session.goal_label,
            "success_criteria": session.success_criteria,
            "review_window_minutes": session.review_window_minutes,
            "max_response_words": session.max_response_words,
            "session_payload": session.session_payload,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "last_evaluated_at": session.last_evaluated_at.isoformat() if session.last_evaluated_at else None,
            "evaluation_count": session.evaluation_count,
        }

    def _attempt_payload(self, attempt) -> dict[str, Any]:
        return {
            "id": attempt.id,
            "session_id": attempt.session_id,
            "user_id": attempt.user_id,
            "submission_id": attempt.submission_id,
            "learner_response": attempt.learner_response,
            "response_word_count": attempt.response_word_count,
            "response_char_count": attempt.response_char_count,
            "is_correct": attempt.is_correct,
            "improvement_score": attempt.improvement_score,
            "validation_payload": attempt.validation_payload,
            "feedback_payload": attempt.feedback_payload,
            "created_at": attempt.created_at.isoformat(),
        }

    def _event_payload(self, event) -> dict[str, Any]:
        return {
            "id": int(event.id),
            "event_type": str(event.event_type),
            "payload": dict(getattr(event, "payload", {}) or {}),
            "created_at": event.created_at.isoformat(),
        }

    def _session_evaluation_payload(self, trace) -> dict[str, Any] | None:
        if trace is None:
            return None
        outputs = dict(getattr(trace, "outputs", {}) or {})
        return {
            "trace_type": str(trace.trace_type),
            "source": str(trace.source),
            "is_correct": bool(outputs.get("is_correct", False)),
            "improvement_score": float(outputs.get("improvement_score", 0.0)),
            "highlighted_mistakes": list(outputs.get("highlighted_mistakes", [])),
            "recommended_next_step": outputs.get("recommended_next_step"),
            "reason": trace.reason,
            "created_at": trace.created_at.isoformat(),
        }

    def _onboarding_transition_payload(self, trace) -> dict[str, Any] | None:
        if trace is None:
            return None
        inputs = dict(getattr(trace, "inputs", {}) or {})
        outputs = dict(getattr(trace, "outputs", {}) or {})
        return {
            "trace_type": str(trace.trace_type),
            "source": str(trace.source),
            "from_step": inputs.get("from_step"),
            "to_step": outputs.get("to_step"),
            "reason": trace.reason,
            "created_at": trace.created_at.isoformat(),
        }

    def _onboarding_paywall_payload(self, trace) -> dict[str, Any] | None:
        if trace is None:
            return None
        outputs = dict(getattr(trace, "outputs", {}) or {})
        return {
            "trace_type": str(trace.trace_type),
            "source": str(trace.source),
            "next_step": outputs.get("next_step"),
            "paywall_strategy": outputs.get("paywall_strategy"),
            "trial_recommended": bool(outputs.get("trial_recommended", False)),
            "reason": trace.reason,
            "created_at": trace.created_at.isoformat(),
        }

    def _onboarding_state_payload(self, state) -> dict[str, Any]:
        return {
            "current_step": state.current_step,
            "steps_completed": list(state.steps_completed),
            "identity": self._as_dict(state.identity),
            "personalization": self._as_dict(state.personalization),
            "wow": self._as_dict(state.wow),
            "early_success_score": state.early_success_score,
            "progress_illusion": self._as_dict(state.progress_illusion),
            "paywall": self._as_dict(state.paywall),
            "habit_lock_in": self._as_dict(state.habit_lock_in),
        }

    async def _user_snapshot(self, user_id: int) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("User not found")
            events = await uow.events.list_by_user(user_id, limit=1000)
            traces = await uow.decision_traces.list_recent(user_id=user_id, limit=200)
            due_items = await uow.vocab.list_due(user_id)
            weak_items = await uow.vocab.list_all(user_id, limit=100, offset=0)
            learning_state = await self._one_or_none(
                uow,
                select(UserLearningStateORM).where(UserLearningStateORM.user_id == user_id),
            )
            engagement_state = await self._one_or_none(
                uow,
                select(UserEngagementStateORM).where(UserEngagementStateORM.user_id == user_id),
            )
            progress_state = await self._one_or_none(
                uow,
                select(UserProgressStateORM).where(UserProgressStateORM.user_id == user_id),
            )
            profile = await self._one_or_none(
                uow,
                select(UserProfileORM).where(UserProfileORM.user_id == user_id),
            )
            subscription = await self._one_or_none(
                uow,
                select(SubscriptionORM).where(SubscriptionORM.user_id == user_id),
            )
            monetization_state = await self._one_or_none(
                uow,
                select(UserMonetizationStateORM).where(UserMonetizationStateORM.user_id == user_id),
            )
            onboarding_state = await self._one_or_none(
                uow,
                select(OnboardingFlowStateORM).where(OnboardingFlowStateORM.user_id == user_id),
            )
            lifecycle_state = await self._one_or_none(
                uow,
                select(UserLifecycleStateORM).where(UserLifecycleStateORM.user_id == user_id),
            )
            lifecycle_transitions = await self._all(
                uow,
                select(LifecycleTransitionORM)
                .where(LifecycleTransitionORM.user_id == user_id)
                .order_by(LifecycleTransitionORM.created_at.desc(), LifecycleTransitionORM.id.desc())
                .limit(50),
            )
            assignments = await self._all(
                uow,
                select(ExperimentAssignmentORM).where(ExperimentAssignmentORM.user_id == user_id),
            )
            monetization_events = await uow.monetization_offer_events.list_by_user(user_id, limit=100)
            used_requests, used_tokens = await uow.usage_logs.totals_for_user_day(user_id)
            await uow.commit()

        experiments = {
            assignment.experiment_key: assignment.variant
            for assignment in assignments
        }
        return {
            "user": user,
            "events": events,
            "traces": traces,
            "due_items": due_items,
            "weak_items": weak_items,
            "learning_state": learning_state,
            "engagement_state": engagement_state,
            "progress_state": progress_state,
            "profile": profile,
            "subscription": subscription,
            "monetization_state": monetization_state,
            "onboarding_state": onboarding_state,
            "lifecycle_state": lifecycle_state,
            "lifecycle_transitions": lifecycle_transitions,
            "experiments": experiments,
            "monetization_events": monetization_events,
            "used_requests": used_requests,
            "used_tokens": used_tokens,
        }

    async def _one_or_none(self, uow: UnitOfWork, statement):
        result = await uow.session.execute(statement)
        return result.scalar_one_or_none()

    async def _all(self, uow: UnitOfWork, statement):
        result = await uow.session.execute(statement)
        return result.scalars().all()

    def _retention_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        profile = snapshot["profile"]
        due_items = snapshot["due_items"]
        weak_items = snapshot["weak_items"]
        if profile is None:
            assessment = RetentionAssessment(
                state="at-risk",
                drop_off_risk=1.0,
                session_frequency=0.0,
                current_streak=0,
                longest_streak=0,
                last_active_at=None,
                is_high_engagement=False,
                suggested_actions=[],
            )
        else:
            risk = self._retention_policy._drop_off_risk(
                last_active_at=profile.last_active_at,
                session_frequency=profile.session_frequency,
                current_streak=profile.current_streak,
                retention_rate=profile.retention_rate,
            )
            state = self._retention_policy._classify_state(risk, profile.last_active_at)
            high_engagement = self._retention_policy._is_high_engagement(profile, risk)
            actions = self._retention_policy._build_actions(
                profile,
                due_items,
                weak_items,
                state,
                risk,
            )
            assessment = RetentionAssessment(
                state=state,
                drop_off_risk=risk,
                session_frequency=float(profile.session_frequency or 0.0),
                current_streak=int(profile.current_streak or 0),
                longest_streak=int(profile.longest_streak or 0),
                last_active_at=profile.last_active_at,
                is_high_engagement=high_engagement,
                suggested_actions=actions,
            )
        return {
            "state": assessment.state,
            "drop_off_risk": round(float(assessment.drop_off_risk or 0.0), 3),
            "session_frequency": round(float(assessment.session_frequency or 0.0), 3),
            "current_streak": int(assessment.current_streak or 0),
            "longest_streak": int(assessment.longest_streak or 0),
            "last_active_at": self._timestamp(assessment.last_active_at),
            "is_high_engagement": bool(assessment.is_high_engagement),
            "suggested_actions": [
                {
                    "kind": action.kind,
                    "reason": action.reason,
                    "target": action.target,
                }
                for action in assessment.suggested_actions
            ],
        }

    def _lifecycle_payload(
        self,
        snapshot: dict[str, Any],
        retention: dict[str, Any],
        *,
        paywall: dict[str, Any],
        decision_trace=None,
    ) -> dict[str, Any]:
        if decision_trace is not None:
            outputs = dict(decision_trace.outputs or {})
            return {
                "stage": str(outputs.get("stage") or "activating"),
                "reasons": [str(reason) for reason in outputs.get("reasons", [])],
                "actions": [
                    self._lifecycle_action_payload_from_trace(action)
                    for action in outputs.get("actions", [])
                ],
                "paywall": self._lifecycle_paywall_payload_from_trace(outputs.get("paywall")),
            }
        learning_state = self._learning_state_domain(snapshot["learning_state"], snapshot["user"].id)
        engagement_state = self._engagement_state_domain(snapshot["engagement_state"], snapshot["user"].id)
        retention_view = type(
            "RetentionView",
            (),
            {
                "state": "at-risk" if retention["state"] == "at-risk" else retention["state"],
                "is_high_engagement": retention["is_high_engagement"],
            },
        )()
        stage, reasons = classify_lifecycle_stage(
            snapshot=LifecycleSnapshot(
                learning_state=learning_state,
                engagement_state=engagement_state,
                retention=retention_view,
            )
        )
        actions = self._lifecycle_actions(
            stage=stage,
            retention=retention,
            learning_state=learning_state,
            paywall=paywall,
        )
        return {
            "stage": stage,
            "reasons": reasons,
            "actions": [self._lifecycle_action_payload(action) for action in actions],
            "paywall": {
                "show": bool(paywall.get("show_paywall", False)),
                "type": paywall.get("paywall_type"),
                "reason": paywall.get("reason"),
                "usage_percent": int(paywall.get("usage_percent", 0) or 0),
                "allow_access": bool(paywall.get("allow_access", True)),
            },
        }

    async def _adaptive_paywall_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        subscription = snapshot["subscription"]
        profile = snapshot["profile"]
        events = snapshot["events"]
        experiments = snapshot["experiments"]
        used_requests = int(snapshot["used_requests"] or 0)
        used_tokens = int(snapshot["used_tokens"] or 0)

        tier = (subscription.tier if subscription else "free").lower()
        request_limit = int(getattr(subscription, "request_limit", 100) or 100)
        token_limit = int(getattr(subscription, "token_limit", 50000) or 50000)
        trial_tier = getattr(subscription, "trial_tier", None)
        trial_ends_at = getattr(subscription, "trial_ends_at", None)
        trial_active = False
        if trial_tier and trial_ends_at is not None:
            from vocablens.core.time import utc_now
            trial_active = trial_ends_at > utc_now()

        sessions_seen = sum(1 for event in events if getattr(event, "event_type", None) == "session_started")
        request_ratio = self._ratio(used_requests, request_limit)
        token_ratio = self._ratio(used_tokens, token_limit)
        usage_ratio = max(request_ratio, token_ratio)

        onboarding_state = snapshot["onboarding_state"]
        onboarding_paywall = dict(getattr(onboarding_state, "paywall", {}) or {}) if onboarding_state else {}
        wow_payload = dict(getattr(onboarding_state, "wow", {}) or {}) if onboarding_state else {}
        wow_score = round(float(onboarding_paywall.get("wow_score") or wow_payload.get("score") or 0.0), 3)
        wow_moment = wow_score >= 0.65

        trigger_variant = experiments.get("paywall_trigger_timing", "control")
        pricing_variant = experiments.get("paywall_pricing_messaging", "standard")
        trial_variant = experiments.get("paywall_trial_length", "trial_3d")
        trial_days = self._adaptive_paywall_policy.trial_days(trial_variant)
        user_segment = self._adaptive_paywall_policy.segment_user(
            events=events,
            profile=profile or type("ProfileView", (), {"drop_off_risk": 0.0, "session_frequency": 0.0})(),
            sessions_seen=sessions_seen,
            usage_ratio=usage_ratio,
            wow_moment=wow_moment,
            wow_score=wow_score,
        )
        thresholds = self._adaptive_paywall_policy.thresholds(
            user_segment=user_segment,
            trigger_variant=trigger_variant,
            base_session_trigger=3,
            base_usage_soft_threshold=0.8,
            base_usage_hard_threshold=1.0,
        )
        strategy = self._adaptive_paywall_policy.strategy_name(
            user_segment=user_segment,
            trigger_variant=trigger_variant,
            pricing_variant=pricing_variant,
        )

        if tier != "free" or trial_active:
            show_paywall = False
            paywall_type = None
            reason = None
            allow_access = True
        elif usage_ratio >= thresholds["hard_usage_threshold"]:
            show_paywall = True
            paywall_type = "hard_paywall"
            reason = "adaptive usage threshold reached"
            allow_access = False
        elif wow_moment or sessions_seen >= thresholds["session_trigger"] or usage_ratio >= thresholds["soft_usage_threshold"]:
            show_paywall = True
            paywall_type = "soft_paywall"
            reason = (
                "wow moment reached"
                if wow_moment
                else "adaptive session trigger reached"
                if sessions_seen >= thresholds["session_trigger"]
                else "adaptive usage pressure high"
            )
            allow_access = True
        else:
            show_paywall = False
            paywall_type = None
            reason = None
            allow_access = True

        usage_percent = max(
            min(100, int(request_ratio * 100)) if request_limit else 100,
            min(100, int(token_ratio * 100)) if token_limit else 100,
        )
        trial_recommended = self._adaptive_paywall_policy.trial_recommended(
            decision=type("PaywallView", (), {"trial_active": trial_active, "allow_access": allow_access})(),
            wow_score=wow_score,
        )
        upsell_recommended = self._adaptive_paywall_policy.upsell_recommended(
            decision=type("PaywallView", (), {"show_paywall": show_paywall})(),
            wow_score=wow_score,
        )
        return {
            "show_paywall": show_paywall,
            "paywall_type": paywall_type,
            "reason": reason,
            "usage_percent": usage_percent,
            "request_usage_percent": min(100, int(request_ratio * 100)) if request_limit else 100,
            "token_usage_percent": min(100, int(token_ratio * 100)) if token_limit else 100,
            "usage_requests": used_requests,
            "usage_tokens": used_tokens,
            "request_limit": request_limit,
            "token_limit": token_limit,
            "sessions_seen": sessions_seen,
            "wow_moment_triggered": wow_moment,
            "trial_active": trial_active,
            "trial_tier": trial_tier,
            "trial_ends_at": self._timestamp(trial_ends_at),
            "allow_access": allow_access,
            "user_segment": user_segment,
            "strategy": strategy,
            "trigger_variant": trigger_variant,
            "pricing_variant": pricing_variant,
            "trial_days": trial_days,
            "wow_score": wow_score,
            "trial_recommended": trial_recommended,
            "upsell_recommended": upsell_recommended,
        }

    async def _monetization_payload(
        self,
        snapshot: dict[str, Any],
        *,
        lifecycle: dict[str, Any],
        paywall: dict[str, Any],
        geography: str | None,
        decision_trace=None,
    ) -> dict[str, Any]:
        if decision_trace is not None:
            outputs = dict(decision_trace.outputs or {})
            return {
                "show_paywall": bool(outputs.get("show_paywall", False)),
                "paywall_type": outputs.get("paywall_type"),
                "offer_type": str(outputs.get("offer_type") or "none"),
                "pricing": dict(outputs.get("pricing", {}) or {}),
                "trigger": dict(outputs.get("trigger", {}) or {}),
                "value_display": dict(outputs.get("value_display", {}) or {}),
                "strategy": str(outputs.get("strategy") or ""),
                "lifecycle_stage": str(outputs.get("lifecycle_stage") or lifecycle["stage"]),
                "onboarding_step": outputs.get("onboarding_step"),
                "user_segment": str(outputs.get("user_segment") or paywall["user_segment"]),
                "trial_days": outputs.get("trial_days"),
            }
        engagement_state = self._engagement_state_domain(snapshot["engagement_state"], snapshot["user"].id)
        learning_state = self._learning_state_domain(snapshot["learning_state"], snapshot["user"].id)
        progress_state = self._progress_state_domain(snapshot["progress_state"], snapshot["user"].id)
        onboarding_state = self._onboarding_state_orm_payload(snapshot["onboarding_state"])
        business_metrics = await self._business_context_payload()
        onboarding_step = onboarding_state["current_step"] if onboarding_state else None
        geography_code = self._monetization_policy.normalize_geography(geography)
        lifecycle_view = type("LifecycleView", (), {"stage": lifecycle["stage"]})()
        paywall_view = type("PaywallView", (), paywall)()

        pricing = self._monetization_policy.build_pricing(
            paywall=paywall_view,
            lifecycle=lifecycle_view,
            onboarding_state=onboarding_state,
            engagement_state=engagement_state,
            business_metrics=business_metrics,
            geography=geography_code,
        )
        offer_type = self._monetization_policy.offer_type(
            paywall=paywall_view,
            lifecycle=lifecycle_view,
            onboarding_state=onboarding_state,
        )
        show_paywall = self._monetization_policy.should_show_paywall(
            paywall=paywall_view,
            lifecycle=lifecycle_view,
            onboarding_step=onboarding_step,
        )
        if not show_paywall and offer_type == "annual_anchor":
            offer_type = "none"

        trigger = self._monetization_policy.trigger_payload(
            paywall=paywall_view,
            lifecycle=lifecycle_view,
            onboarding_step=onboarding_step,
            show_paywall=show_paywall,
        )
        value_display = self._monetization_policy.value_display(
            paywall=paywall_view,
            lifecycle=lifecycle_view,
            onboarding_state=onboarding_state,
            learning_state=learning_state,
            progress_state=progress_state,
            offer_type=offer_type,
        )
        return {
            "show_paywall": show_paywall,
            "paywall_type": paywall["paywall_type"] if show_paywall else None,
            "offer_type": offer_type,
            "pricing": asdict(pricing),
            "trigger": asdict(trigger),
            "value_display": asdict(value_display),
            "strategy": self._monetization_policy.strategy(
                paywall=paywall_view,
                offer_type=offer_type,
                geography=geography_code,
            ),
            "lifecycle_stage": lifecycle["stage"],
            "onboarding_step": onboarding_step,
            "user_segment": paywall["user_segment"],
            "trial_days": paywall["trial_days"] if offer_type == "trial" else None,
        }

    async def _business_context_payload(self) -> dict[str, Any]:
        if self._business_metrics is None:
            return {"revenue": {}}
        dashboard = await self._business_metrics.dashboard()
        if is_dataclass(dashboard):
            return asdict(dashboard)
        return dict(dashboard)

    def _filtered_events(self, events, *, allowed_types: set[str]) -> list[dict[str, Any]]:
        filtered = [
            self._event_payload(event)
            for event in events
            if str(getattr(event, "event_type", "") or "") in allowed_types
        ]
        filtered.sort(key=lambda item: (item["created_at"], item["id"]))
        return filtered

    def _filtered_traces(self, traces, *, predicate) -> list[dict[str, Any]]:
        filtered = [self._trace_payload(trace) for trace in traces if predicate(trace)]
        filtered.sort(key=lambda item: (item["created_at"], item["id"]))
        return filtered

    def _latest_trace_payload_from_dicts(self, traces: list[dict[str, Any]], *, trace_type: str) -> dict[str, Any] | None:
        for trace in reversed(traces):
            if str(trace.get("trace_type") or "") == trace_type:
                return trace
        return None

    def _event_summary_payload(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(str(item.get("event_type") or "") for item in events)
        latest_event_at = max(
            (item.get("created_at") for item in events if item.get("created_at")),
            default=None,
        )
        return {
            "total_events": len(events),
            "counts_by_type": dict(sorted(counts.items())),
            "latest_event_at": latest_event_at,
        }

    def _trace_summary_payload(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(str(item.get("trace_type") or "") for item in traces)
        latest_trace_at = max(
            (item.get("created_at") for item in traces if item.get("created_at")),
            default=None,
        )
        return {
            "total_traces": len(traces),
            "counts_by_type": dict(sorted(counts.items())),
            "latest_trace_at": latest_trace_at,
        }

    def _latest_trace(self, traces, *, trace_type: str):
        for trace in traces:
            if str(getattr(trace, "trace_type", "") or "") == trace_type:
                return trace
        return None

    def _learning_state_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "skills": dict(row.skills or {}),
            "weak_areas": list(row.weak_areas or []),
            "mastery_percent": float(row.mastery_percent or 0.0),
            "accuracy_rate": float(row.accuracy_rate or 0.0),
            "response_speed_seconds": float(row.response_speed_seconds or 0.0),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _engagement_state_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "current_streak": int(row.current_streak or 0),
            "longest_streak": int(row.longest_streak or 0),
            "momentum_score": float(row.momentum_score or 0.0),
            "total_sessions": int(row.total_sessions or 0),
            "sessions_last_3_days": int(row.sessions_last_3_days or 0),
            "last_session_at": self._timestamp(row.last_session_at),
            "shields_used_this_week": int(row.shields_used_this_week or 0),
            "daily_mission_completed_at": self._timestamp(row.daily_mission_completed_at),
            "interaction_stats": dict(row.interaction_stats or {}),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _progress_state_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "xp": int(row.xp or 0),
            "level": int(row.level or 1),
            "milestones": list(row.milestones or []),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _profile_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "learning_speed": float(row.learning_speed or 0.0),
            "retention_rate": float(row.retention_rate or 0.0),
            "difficulty_preference": row.difficulty_preference,
            "content_preference": row.content_preference,
            "last_active_at": self._timestamp(row.last_active_at),
            "session_frequency": float(row.session_frequency or 0.0),
            "current_streak": int(row.current_streak or 0),
            "longest_streak": int(row.longest_streak or 0),
            "drop_off_risk": float(row.drop_off_risk or 0.0),
            "preferred_channel": row.preferred_channel,
            "preferred_time_of_day": int(row.preferred_time_of_day or 0),
            "frequency_limit": int(row.frequency_limit or 0),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _subscription_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "tier": row.tier,
            "request_limit": int(row.request_limit or 0),
            "token_limit": int(row.token_limit or 0),
            "renewed_at": self._timestamp(row.renewed_at),
            "trial_started_at": self._timestamp(row.trial_started_at),
            "trial_ends_at": self._timestamp(row.trial_ends_at),
            "trial_tier": row.trial_tier,
            "created_at": self._timestamp(row.created_at),
        }

    def _monetization_state_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "current_offer_type": row.current_offer_type,
            "last_paywall_type": row.last_paywall_type,
            "last_paywall_reason": row.last_paywall_reason,
            "current_strategy": row.current_strategy,
            "current_geography": row.current_geography,
            "lifecycle_stage": row.lifecycle_stage,
            "paywall_impressions": int(row.paywall_impressions or 0),
            "paywall_dismissals": int(row.paywall_dismissals or 0),
            "paywall_acceptances": int(row.paywall_acceptances or 0),
            "paywall_skips": int(row.paywall_skips or 0),
            "fatigue_score": int(row.fatigue_score or 0),
            "cooldown_until": self._timestamp(row.cooldown_until),
            "trial_eligible": bool(row.trial_eligible),
            "trial_started_at": self._timestamp(row.trial_started_at),
            "trial_ends_at": self._timestamp(row.trial_ends_at),
            "trial_offer_days": row.trial_offer_days,
            "conversion_propensity": float(row.conversion_propensity or 0.0),
            "last_offer_at": self._timestamp(row.last_offer_at),
            "last_impression_at": self._timestamp(row.last_impression_at),
            "last_dismissed_at": self._timestamp(row.last_dismissed_at),
            "last_accepted_at": self._timestamp(row.last_accepted_at),
            "last_skipped_at": self._timestamp(row.last_skipped_at),
            "last_pricing": dict(row.last_pricing or {}),
            "last_trigger": dict(row.last_trigger or {}),
            "last_value_display": dict(row.last_value_display or {}),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _lifecycle_state_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "current_stage": row.current_stage,
            "previous_stage": row.previous_stage,
            "current_reasons": list(row.current_reasons or []),
            "entered_at": self._timestamp(row.entered_at),
            "last_transition_at": self._timestamp(row.last_transition_at),
            "last_transition_source": row.last_transition_source,
            "last_transition_reference_id": row.last_transition_reference_id,
            "transition_count": int(row.transition_count or 0),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _lifecycle_transition_payload(self, row) -> dict[str, Any]:
        return {
            "id": int(row.id),
            "user_id": row.user_id,
            "from_stage": row.from_stage,
            "to_stage": row.to_stage,
            "reasons": list(row.reasons or []),
            "source": row.source,
            "reference_id": row.reference_id,
            "payload": dict(row.payload or {}),
            "created_at": self._timestamp(row.created_at),
        }

    def _monetization_event_payload(self, row) -> dict[str, Any]:
        return {
            "id": int(row.id),
            "event_type": str(row.event_type),
            "offer_type": row.offer_type,
            "paywall_type": row.paywall_type,
            "strategy": row.strategy,
            "geography": row.geography,
            "payload": dict(row.payload or {}),
            "created_at": self._timestamp(row.created_at),
        }

    def _onboarding_state_orm_payload(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "current_step": row.current_step,
            "steps_completed": list(row.steps_completed or []),
            "identity": dict(row.identity or {}),
            "personalization": dict(row.personalization or {}),
            "wow": dict(row.wow or {}),
            "early_success_score": float(row.early_success_score or 0.0),
            "progress_illusion": dict(row.progress_illusion or {}),
            "paywall": dict(row.paywall or {}),
            "habit_lock_in": dict(row.habit_lock_in or {}),
            "created_at": self._timestamp(row.created_at),
            "updated_at": self._timestamp(row.updated_at),
        }

    def _learning_state_domain(self, row, user_id: int):
        payload = self._learning_state_payload(row) or {}
        return type(
            "LearningStateView",
            (),
            {
                "user_id": user_id,
                "skills": payload.get("skills", {}),
                "weak_areas": payload.get("weak_areas", []),
                "mastery_percent": payload.get("mastery_percent", 0.0),
                "accuracy_rate": payload.get("accuracy_rate", 0.0),
                "response_speed_seconds": payload.get("response_speed_seconds", 0.0),
            },
        )()

    def _engagement_state_domain(self, row, user_id: int):
        payload = self._engagement_state_payload(row) or {}
        return type(
            "EngagementStateView",
            (),
            {
                "user_id": user_id,
                "current_streak": payload.get("current_streak", 0),
                "longest_streak": payload.get("longest_streak", 0),
                "momentum_score": payload.get("momentum_score", 0.0),
                "total_sessions": payload.get("total_sessions", 0),
                "sessions_last_3_days": payload.get("sessions_last_3_days", 0),
                "last_session_at": row.last_session_at if row is not None else None,
                "shields_used_this_week": payload.get("shields_used_this_week", 0),
                "daily_mission_completed_at": row.daily_mission_completed_at if row is not None else None,
                "interaction_stats": payload.get("interaction_stats", {}),
            },
        )()

    def _progress_state_domain(self, row, user_id: int):
        payload = self._progress_state_payload(row) or {}
        return type(
            "ProgressStateView",
            (),
            {
                "user_id": user_id,
                "xp": payload.get("xp", 0),
                "level": payload.get("level", 1),
                "milestones": payload.get("milestones", []),
            },
        )()

    def _lifecycle_actions(
        self,
        *,
        stage: str,
        retention: dict[str, Any],
        learning_state,
        paywall,
    ) -> list[LifecycleAction]:
        weak_area = next(iter(getattr(learning_state, "weak_areas", []) or []), "core skills")
        mastery = float(getattr(learning_state, "mastery_percent", 0.0) or 0.0)
        actions: list[LifecycleAction] = []
        if stage == "new_user":
            actions.append(LifecycleAction(type="onboarding_nudge", message="Guide the user to complete the first meaningful session."))
            actions.append(LifecycleAction(type="quick_start_path", message="Surface the easiest next lesson and tutor mode entry point."))
        elif stage == "activating":
            actions.append(LifecycleAction(type="wow_moment_push", message=f"Guide the user toward a clean success around {weak_area}."))
            actions.append(LifecycleAction(type="progress_visibility", message=f"Highlight current mastery at {mastery}%."))
        elif stage == "engaged":
            actions.append(LifecycleAction(type="monetization_prompt", message="Show the paid value clearly without interrupting a productive stretch."))
            if paywall and paywall.get("show_paywall"):
                actions.append(
                    LifecycleAction(
                        type="paywall_follow_up",
                        message=f"Paywall available: {paywall.get('paywall_type')} for {paywall.get('reason')}.",
                    )
                )
        elif stage == "at_risk":
            actions.append(LifecycleAction(type="reengagement_flow", message="Run a low-friction comeback flow."))
            for action in retention.get("suggested_actions", [])[:2]:
                actions.append(
                    LifecycleAction(
                        type=action["kind"],
                        message=action["reason"],
                        target=action.get("target"),
                    )
                )
        elif stage == "churned":
            actions.append(
                LifecycleAction(
                    type="win_back_flow",
                    message="Offer a straightforward restart path with a reminder of what is worth returning for.",
                )
            )
        return actions

    def _lifecycle_action_payload(self, action: LifecycleAction) -> dict[str, Any]:
        return {
            "type": action.type,
            "message": action.message,
            "target": action.target,
        }

    def _lifecycle_action_payload_from_trace(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": str(payload.get("type") or ""),
            "message": str(payload.get("message") or ""),
            "target": payload.get("target"),
        }

    def _lifecycle_paywall_payload_from_trace(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(payload or {})
        return {
            "show": bool(payload.get("show", False)),
            "type": payload.get("type"),
            "reason": payload.get("reason"),
            "usage_percent": int(payload.get("usage_percent", 0) or 0),
            "allow_access": bool(payload.get("allow_access", True)),
        }

    def _ratio(self, used: int, limit: int) -> float:
        if limit <= 0:
            return 1.0
        return used / limit

    def _timestamp(self, value) -> str | None:
        return value.isoformat() if getattr(value, "isoformat", None) else None

    def _as_dict(self, value) -> dict[str, Any]:
        if hasattr(value, "__dict__"):
            return {
                key: self._as_dict(item) if hasattr(item, "__dict__") else item
                for key, item in value.__dict__.items()
                if not key.startswith("_")
            }
        if isinstance(value, dict):
            return dict(value)
        return {}
