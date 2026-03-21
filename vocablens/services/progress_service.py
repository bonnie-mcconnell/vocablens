import json
from datetime import timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork


class ProgressService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def build_dashboard(self, user_id: int) -> dict:
        now = utc_now()
        async with self._uow_factory() as uow:
            learning_state = await uow.learning_states.get_or_create(user_id)
            engagement_state = await uow.engagement_states.get_or_create(user_id)
            progress_state = await uow.progress_states.get_or_create(user_id)
            vocab = await uow.vocab.list_all(user_id, limit=1000, offset=0)
            due = await uow.vocab.list_due(user_id)
            events = await uow.learning_events.list_since(user_id, since=now - timedelta(days=14))
            await uow.commit()

        skills = dict(getattr(learning_state, "skills", {}) or {})
        mastery_percent = round(float(getattr(learning_state, "mastery_percent", 0.0) or 0.0), 1)
        accuracy_rate = round(float(getattr(learning_state, "accuracy_rate", 0.0) or 0.0), 1)
        response_speed = round(float(getattr(learning_state, "response_speed_seconds", 0.0) or 0.0), 1)
        fluency_score = round(float(skills.get("fluency", 0.5)) * 100, 1)

        return {
            "vocabulary_total": len(vocab),
            "due_reviews": len(due),
            "xp": int(getattr(progress_state, "xp", 0) or 0),
            "level": int(getattr(progress_state, "level", 1) or 1),
            "milestones": list(getattr(progress_state, "milestones", []) or []),
            "metrics": {
                "vocabulary_mastery_percent": mastery_percent,
                "accuracy_rate": accuracy_rate,
                "response_speed_seconds": response_speed,
                "fluency_score": fluency_score,
            },
            "daily": self._aggregate_period(events, since=now - timedelta(days=1)),
            "weekly": self._aggregate_period(events, since=now - timedelta(days=7)),
            "trends": self._build_trends(events, skills, now),
            "skill_breakdown": {
                "grammar": round(float(skills.get("grammar", 0.5)) * 100, 1),
                "vocabulary": round(float(skills.get("vocabulary", 0.5)) * 100, 1),
                "fluency": fluency_score,
            },
            "engagement": {
                "current_streak": int(getattr(engagement_state, "current_streak", 0) or 0),
                "momentum_score": round(float(getattr(engagement_state, "momentum_score", 0.0) or 0.0), 3),
                "total_sessions": int(getattr(engagement_state, "total_sessions", 0) or 0),
            },
        }

    def _accuracy_rate(self, events) -> float:
        scores = []
        for event in events:
            if getattr(event, "event_type", None) != "word_reviewed":
                continue
            payload = self._payload(event)
            if payload.get("response_accuracy") is not None:
                scores.append(float(payload["response_accuracy"]) * 100)
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 1)

    def _response_speed(self, events) -> float:
        conversation_events = [
            event for event in sorted(
                [event for event in events if getattr(event, "event_type", None) == "conversation_turn"],
                key=lambda item: getattr(item, "created_at", utc_now()),
            )
            if getattr(event, "created_at", None) is not None
        ]
        if len(conversation_events) < 2:
            return 0.0
        gaps = []
        for previous, current in zip(conversation_events, conversation_events[1:]):
            gap = (current.created_at - previous.created_at).total_seconds()
            if gap >= 0:
                gaps.append(gap)
        if not gaps:
            return 0.0
        return round(sum(gaps) / len(gaps), 1)

    def _aggregate_period(self, events, *, since) -> dict:
        period_events = [
            event for event in events
            if getattr(event, "created_at", None) is not None and event.created_at >= since
        ]
        learned = sum(1 for event in period_events if getattr(event, "event_type", None) == "word_learned")
        reviewed = sum(1 for event in period_events if getattr(event, "event_type", None) == "word_reviewed")
        messages = sum(1 for event in period_events if getattr(event, "event_type", None) == "conversation_turn")
        return {
            "words_learned": learned,
            "reviews_completed": reviewed,
            "messages_sent": messages,
            "accuracy_rate": self._accuracy_rate(period_events),
        }

    def _build_trends(self, events, skills, now) -> dict:
        current_week = self._aggregate_period(events, since=now - timedelta(days=7))
        previous_start = now - timedelta(days=14)
        previous_end = now - timedelta(days=7)
        previous_week_events = [
            event for event in events
            if getattr(event, "created_at", None) is not None and previous_start <= event.created_at < previous_end
        ]
        previous_week = {
            "words_learned": sum(1 for event in previous_week_events if getattr(event, "event_type", None) == "word_learned"),
            "reviews_completed": sum(1 for event in previous_week_events if getattr(event, "event_type", None) == "word_reviewed"),
            "messages_sent": sum(1 for event in previous_week_events if getattr(event, "event_type", None) == "conversation_turn"),
            "accuracy_rate": self._accuracy_rate(previous_week_events),
        }
        return {
            "weekly_words_learned_delta": current_week["words_learned"] - previous_week["words_learned"],
            "weekly_reviews_completed_delta": current_week["reviews_completed"] - previous_week["reviews_completed"],
            "weekly_messages_sent_delta": current_week["messages_sent"] - previous_week["messages_sent"],
            "weekly_accuracy_rate_delta": round(current_week["accuracy_rate"] - previous_week["accuracy_rate"], 1),
            "fluency_score": round(float(skills.get("fluency", 0.5)) * 100, 1),
        }

    def _payload(self, event) -> dict:
        payload_json = getattr(event, "payload_json", None)
        if not payload_json:
            return {}
        try:
            return json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}
