from __future__ import annotations

from typing import Any

from vocablens.domain.errors import NotFoundError
from vocablens.infrastructure.unit_of_work import UnitOfWork


class DecisionTraceService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

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

        return {
            "session": self._session_payload(session),
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

        return {
            "state": self._onboarding_state_payload(state),
            "events": related_events,
            "traces": onboarding_traces,
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
            "duration_seconds": session.duration_seconds,
            "mode": session.mode,
            "weak_area": session.weak_area,
            "lesson_target": session.lesson_target,
            "goal_label": session.goal_label,
            "success_criteria": session.success_criteria,
            "review_window_minutes": session.review_window_minutes,
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
            "learner_response": attempt.learner_response,
            "is_correct": attempt.is_correct,
            "improvement_score": attempt.improvement_score,
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
