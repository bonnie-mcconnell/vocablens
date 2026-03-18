from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.retention_engine import RetentionEngine


class FakeRetentionUOW:
    def __init__(self, profile, due_items=None, vocab_items=None):
        self.profiles = SimpleNamespace(
            get_or_create=self._get_or_create,
            update=self._update,
        )
        self.vocab = SimpleNamespace(
            list_due=self._list_due,
            list_all=self._list_all,
        )
        self.profile = profile
        self.due_items = due_items or []
        self.vocab_items = vocab_items or []
        self.updated = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _get_or_create(self, user_id: int):
        return self.profile

    async def _update(self, user_id: int, **kwargs):
        self.updated = kwargs
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.profile, key, value)

    async def _list_due(self, user_id: int):
        return self.due_items

    async def _list_all(self, user_id: int, limit: int, offset: int):
        return self.vocab_items


def test_retention_engine_records_activity_and_updates_streaks():
    previous_day = utc_now() - timedelta(days=1)
    profile = SimpleNamespace(
        last_active_at=previous_day,
        session_frequency=2.0,
        current_streak=2,
        longest_streak=3,
        retention_rate=0.8,
    )
    uow = FakeRetentionUOW(profile)
    engine = RetentionEngine(lambda: uow)

    run_async(engine.record_activity(1, occurred_at=utc_now()))

    assert uow.updated is not None
    assert uow.updated["current_streak"] == 3
    assert uow.updated["longest_streak"] == 3
    assert uow.updated["session_frequency"] > 2.0
    assert 0.0 <= uow.updated["drop_off_risk"] <= 1.0


def test_retention_engine_classifies_at_risk_and_suggests_actions():
    profile = SimpleNamespace(
        last_active_at=utc_now() - timedelta(days=6),
        session_frequency=0.8,
        current_streak=1,
        longest_streak=4,
        retention_rate=0.55,
        drop_off_risk=0.0,
    )
    due_items = [SimpleNamespace(source_text="hola", review_count=3, ease_factor=1.8)]
    vocab_items = [
        SimpleNamespace(source_text="hola", review_count=3, ease_factor=1.8),
        SimpleNamespace(source_text="adios", review_count=1, ease_factor=2.4),
    ]
    uow = FakeRetentionUOW(profile, due_items=due_items, vocab_items=vocab_items)
    engine = RetentionEngine(lambda: uow)

    assessment = run_async(engine.assess_user(1))

    assert assessment.state == "at-risk"
    assert assessment.drop_off_risk >= 0.45
    assert any(action.kind == "review_reminder" for action in assessment.suggested_actions)
    assert any(action.kind == "quick_session" for action in assessment.suggested_actions)
    assert any(action.kind == "resurface_weak_vocabulary" for action in assessment.suggested_actions)


def test_retention_engine_detects_high_engagement_users():
    profile = SimpleNamespace(
        last_active_at=utc_now(),
        session_frequency=5.5,
        current_streak=9,
        longest_streak=12,
        retention_rate=0.92,
        drop_off_risk=0.0,
    )
    uow = FakeRetentionUOW(profile, due_items=[], vocab_items=[])
    engine = RetentionEngine(lambda: uow)

    assessment = run_async(engine.assess_user(1))

    assert assessment.state == "active"
    assert assessment.is_high_engagement is True
