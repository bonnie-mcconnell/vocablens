from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.notifications.base import NotificationMessage
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.retention_engine import RetentionAssessment


PRIORITY_RANK = {
    "streak_nudge": 3,
    "review_reminder": 2,
    "quick_session": 1,
    "resurface_weak_vocabulary": 1,
    "general": 0,
}


@dataclass(frozen=True)
class NotificationDecision:
    should_send: bool
    send_at: datetime
    channel: str
    cooldown_until: datetime | None
    message: NotificationMessage | None
    reason: str


class NotificationDecisionEngine:
    def __init__(self, uow_factory: type[UnitOfWork], cooldown_hours: int = 4):
        self._uow_factory = uow_factory
        self._cooldown = timedelta(hours=cooldown_hours)

    async def decide(
        self,
        user_id: int,
        assessment: RetentionAssessment,
        *,
        reference_id: str | None = None,
        source_context: str = "notification_decision_engine.decide",
    ) -> NotificationDecision:
        async with self._uow_factory() as uow:
            profile = await uow.profiles.get_or_create(user_id)
            recent_deliveries = await uow.notification_deliveries.list_recent(user_id, limit=50)
            session_events = await uow.learning_events.list_since(user_id, since=utc_now() - timedelta(days=14))
            weak_clusters = await uow.knowledge_graph.get_weak_clusters(user_id)
            mistakes = await uow.mistake_patterns.top_patterns(user_id, limit=3)
            await uow.commit()

        frequency_limit = int(getattr(profile, "frequency_limit", 2) or 0)
        day_cutoff = utc_now() - timedelta(days=1)
        sent_today = [row for row in recent_deliveries if row.created_at and row.created_at >= day_cutoff]
        if frequency_limit == 0:
            decision = NotificationDecision(False, utc_now(), profile.preferred_channel, None, None, "notifications disabled")
            await self._record_trace(
                user_id=user_id,
                assessment=assessment,
                profile=profile,
                recent_deliveries=recent_deliveries,
                session_events=session_events,
                weak_clusters=weak_clusters,
                mistakes=mistakes,
                action=None,
                decision=decision,
                predicted_hour=None,
                reference_id=reference_id,
                source_context=source_context,
            )
            return decision
        if len(sent_today) >= frequency_limit:
            decision = NotificationDecision(False, utc_now(), profile.preferred_channel, None, None, "daily frequency limit reached")
            await self._record_trace(
                user_id=user_id,
                assessment=assessment,
                profile=profile,
                recent_deliveries=recent_deliveries,
                session_events=session_events,
                weak_clusters=weak_clusters,
                mistakes=mistakes,
                action=None,
                decision=decision,
                predicted_hour=None,
                reference_id=reference_id,
                source_context=source_context,
            )
            return decision

        last_delivery = recent_deliveries[0] if recent_deliveries else None
        if last_delivery and last_delivery.created_at and (utc_now() - last_delivery.created_at) < self._cooldown:
            cooldown_until = last_delivery.created_at + self._cooldown
            decision = NotificationDecision(False, cooldown_until, profile.preferred_channel, cooldown_until, None, "cooldown active")
            await self._record_trace(
                user_id=user_id,
                assessment=assessment,
                profile=profile,
                recent_deliveries=recent_deliveries,
                session_events=session_events,
                weak_clusters=weak_clusters,
                mistakes=mistakes,
                action=None,
                decision=decision,
                predicted_hour=None,
                reference_id=reference_id,
                source_context=source_context,
            )
            return decision

        action = self._pick_action(assessment)
        if action is None:
            decision = NotificationDecision(False, utc_now(), profile.preferred_channel, None, None, "no retention action")
            await self._record_trace(
                user_id=user_id,
                assessment=assessment,
                profile=profile,
                recent_deliveries=recent_deliveries,
                session_events=session_events,
                weak_clusters=weak_clusters,
                mistakes=mistakes,
                action=None,
                decision=decision,
                predicted_hour=None,
                reference_id=reference_id,
                source_context=source_context,
            )
            return decision

        predicted_hour = self._predicted_hour(profile, session_events)
        send_at = self._send_time(predicted_hour)
        message = self._build_message(
            user_id=user_id,
            action=action,
            assessment=assessment,
            channel=profile.preferred_channel,
            weak_clusters=weak_clusters,
            mistakes=mistakes,
        )
        decision = NotificationDecision(
            should_send=True,
            send_at=send_at,
            channel=profile.preferred_channel,
            cooldown_until=send_at + self._cooldown,
            message=message,
            reason="retention action selected",
        )
        await self._record_trace(
            user_id=user_id,
            assessment=assessment,
            profile=profile,
            recent_deliveries=recent_deliveries,
            session_events=session_events,
            weak_clusters=weak_clusters,
            mistakes=mistakes,
            action=action,
            decision=decision,
            predicted_hour=predicted_hour,
            reference_id=reference_id,
            source_context=source_context,
        )
        return decision

    def _pick_action(self, assessment: RetentionAssessment):
        actions = sorted(
            assessment.suggested_actions,
            key=lambda action: PRIORITY_RANK.get(action.kind, PRIORITY_RANK["general"]),
            reverse=True,
        )
        return actions[0] if actions else None

    def _predicted_hour(self, profile, session_events) -> int:
        preferred = getattr(profile, "preferred_time_of_day", None)
        if preferred is not None:
            return int(preferred)
        timestamps = [getattr(event, "created_at", None) for event in session_events if getattr(event, "created_at", None)]
        if not timestamps:
            last_active = getattr(profile, "last_active_at", None)
            return int(last_active.hour) if last_active else 18
        average_hour = round(sum(ts.hour for ts in timestamps) / len(timestamps))
        return max(0, min(23, average_hour))

    def _send_time(self, predicted_hour: int) -> datetime:
        now = utc_now()
        send_at = now.replace(hour=predicted_hour, minute=0, second=0, microsecond=0)
        if send_at < now - timedelta(hours=1):
            send_at = send_at + timedelta(days=1)
        return send_at

    def _build_message(self, *, user_id: int, action, assessment: RetentionAssessment, channel: str, weak_clusters, mistakes) -> NotificationMessage:
        title = self._title_for(action.kind)
        body = self._body_for(action.kind, action.reason, assessment, weak_clusters, mistakes)
        metadata = {
            "channel": channel,
            "state": assessment.state,
            "drop_off_risk": assessment.drop_off_risk,
            "target": action.target,
            "priority": PRIORITY_RANK.get(action.kind, 0),
        }
        return NotificationMessage(
            user_id=user_id,
            category=f"retention:{action.kind}",
            title=title,
            body=body,
            metadata=metadata,
        )

    def _title_for(self, action_kind: str) -> str:
        if action_kind == "streak_nudge":
            return "Keep your streak going"
        if action_kind == "review_reminder":
            return "Review session ready"
        if action_kind == "quick_session":
            return "A short session will help"
        if action_kind == "resurface_weak_vocabulary":
            return "Revisit your weakest words"
        return "Learning update"

    def _body_for(self, action_kind: str, base_reason: str, assessment: RetentionAssessment, weak_clusters, mistakes) -> str:
        details: list[str] = [base_reason]
        if weak_clusters:
            details.append(f"Focus on {weak_clusters[0].get('cluster', 'a weak area')}.")
        elif mistakes:
            top = mistakes[0]
            details.append(f"Recent issue: {getattr(top, 'pattern', 'recurring mistakes')}.")
        if assessment.current_streak > 0:
            details.append(f"Current streak: {assessment.current_streak} day(s).")
        if assessment.drop_off_risk >= 0.45:
            details.append(f"Retention risk is {assessment.drop_off_risk:.2f}.")
        if action_kind == "review_reminder" and details[-1][-1] != ".":
            details[-1] = details[-1] + "."
        return " ".join(details)

    async def _record_trace(
        self,
        *,
        user_id: int,
        assessment: RetentionAssessment,
        profile,
        recent_deliveries,
        session_events,
        weak_clusters,
        mistakes,
        action,
        decision: NotificationDecision,
        predicted_hour: int | None,
        reference_id: str | None,
        source_context: str,
    ) -> None:
        resolved_reference = reference_id or f"notification:{user_id}"
        async with self._uow_factory() as uow:
            await uow.decision_traces.create(
                user_id=user_id,
                trace_type="notification_selection",
                source=source_context,
                reference_id=resolved_reference,
                policy_version="v1",
                inputs={
                    "retention": {
                        "state": assessment.state,
                        "drop_off_risk": round(float(assessment.drop_off_risk or 0.0), 3),
                        "current_streak": int(assessment.current_streak or 0),
                        "suggested_action_types": [item.kind for item in assessment.suggested_actions],
                    },
                    "profile": {
                        "preferred_channel": getattr(profile, "preferred_channel", None),
                        "preferred_time_of_day": getattr(profile, "preferred_time_of_day", None),
                        "frequency_limit": int(getattr(profile, "frequency_limit", 0) or 0),
                    },
                    "delivery_context": {
                        "recent_delivery_count": len(recent_deliveries),
                        "sent_today_count": len(
                            [row for row in recent_deliveries if row.created_at and row.created_at >= utc_now() - timedelta(days=1)]
                        ),
                    },
                    "session_history": {
                        "session_event_count": len(session_events),
                        "predicted_hour": predicted_hour,
                    },
                    "weak_clusters": list(weak_clusters or []),
                    "mistakes": [
                        {"category": getattr(item, "category", None), "pattern": getattr(item, "pattern", None)}
                        for item in list(mistakes or [])
                    ],
                    "selected_action": {
                        "kind": getattr(action, "kind", None),
                        "reason": getattr(action, "reason", None),
                        "target": getattr(action, "target", None),
                    },
                },
                outputs={
                    "should_send": bool(decision.should_send),
                    "channel": decision.channel,
                    "send_at": decision.send_at.isoformat(),
                    "cooldown_until": decision.cooldown_until.isoformat() if decision.cooldown_until else None,
                    "message_category": decision.message.category if decision.message else None,
                    "message_title": decision.message.title if decision.message else None,
                    "reason": decision.reason,
                },
                reason=decision.reason,
            )
            await uow.commit()
