from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.daily_loop_service import DailyLoopService


class FakeUOW:
    def __init__(self, events=None, weak_clusters=None, mistakes=None, due_items=None, profile=None, learning_state=None, engagement_state=None, progress_state=None):
        self.vocab = SimpleNamespace(list_due=self._list_due)
        self.learning_states = SimpleNamespace(get_or_create=self._get_learning_state, update=self._update_engagement_passthrough)
        self.engagement_states = SimpleNamespace(get_or_create=self._get_engagement_state, update=self._update_engagement_state)
        self.progress_states = SimpleNamespace(get_or_create=self._get_progress_state, update=self._update_progress_state)
        self.daily_missions = SimpleNamespace(
            get_by_user_date=self._get_daily_mission_by_user_date,
            create_once=self._create_daily_mission_once,
            mark_completed_once=self._mark_daily_mission_completed_once,
        )
        self.reward_chests = SimpleNamespace(
            get_by_mission_id=self._get_reward_chest_by_mission_id,
            create_once=self._create_reward_chest_once,
            mark_unlocked_once=self._mark_reward_chest_unlocked_once,
            mark_claimed_once=self._mark_reward_chest_claimed_once,
        )
        self.decision_traces = SimpleNamespace(create=self._create_decision_trace)
        self._due_items = due_items or []
        self._profile = profile or SimpleNamespace(current_streak=4)
        self._learning_state = learning_state or SimpleNamespace(weak_areas=["vocabulary"])
        self._engagement_state = engagement_state or SimpleNamespace(
            current_streak=4,
            momentum_score=0.5,
            total_sessions=4,
            sessions_last_3_days=2,
            last_session_at=utc_now() - timedelta(hours=3),
            shields_used_this_week=0,
            daily_mission_completed_at=None,
            updated_at=utc_now(),
        )
        self._progress_state = progress_state or SimpleNamespace(xp=120, level=1, milestones=[], updated_at=utc_now())
        self._daily_mission = None
        self._reward_chest = None
        self._decision_traces = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _list_due(self, user_id: int):
        return self._due_items

    async def _get_learning_state(self, user_id: int):
        return self._learning_state

    async def _get_engagement_state(self, user_id: int):
        return self._engagement_state

    async def _get_progress_state(self, user_id: int):
        return self._progress_state

    async def _update_engagement_state(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self._engagement_state, key, value)
        return self._engagement_state

    async def _update_progress_state(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self._progress_state, key, value)
        return self._progress_state

    async def _update_engagement_passthrough(self, user_id: int, **kwargs):
        return self._learning_state

    async def _get_daily_mission_by_user_date(self, user_id: int, mission_date: str):
        if self._daily_mission and self._daily_mission.user_id == user_id and self._daily_mission.mission_date == mission_date:
            return self._daily_mission
        return None

    async def _create_daily_mission_once(self, **kwargs):
        if self._daily_mission is not None:
            return self._daily_mission, False
        self._daily_mission = SimpleNamespace(id=1, status="issued", completed_at=None, created_at=utc_now(), updated_at=utc_now(), **kwargs)
        return self._daily_mission, True

    async def _mark_daily_mission_completed_once(self, mission_id: int, *, completed_at):
        if self._daily_mission.status != "issued":
            return self._daily_mission, False
        self._daily_mission.status = "completed"
        self._daily_mission.completed_at = completed_at
        return self._daily_mission, True

    async def _get_reward_chest_by_mission_id(self, mission_id: int):
        return self._reward_chest

    async def _create_reward_chest_once(self, **kwargs):
        if self._reward_chest is not None:
            return self._reward_chest, False
        self._reward_chest = SimpleNamespace(id=1, status="locked", unlocked_at=None, created_at=utc_now(), updated_at=utc_now(), **kwargs)
        return self._reward_chest, True

    async def _mark_reward_chest_unlocked_once(self, chest_id: int, *, unlocked_at):
        if self._reward_chest.status != "locked":
            return self._reward_chest, False
        self._reward_chest.status = "unlocked"
        self._reward_chest.unlocked_at = unlocked_at
        return self._reward_chest, True

    async def _mark_reward_chest_claimed_once(self, chest_id: int, *, claimed_at):
        if self._reward_chest.status != "unlocked":
            return self._reward_chest, False
        self._reward_chest.status = "claimed"
        self._reward_chest.claimed_at = claimed_at
        return self._reward_chest, True

    async def _create_decision_trace(self, **kwargs):
        self._decision_traces.append(kwargs)
        return SimpleNamespace(**kwargs)


class FakeLearningEngine:
    def __init__(self, recommendation):
        self.recommendation = recommendation

    async def get_next_lesson(self, user_id: int):
        return self.recommendation


class FakeGamificationService:
    def __init__(self, streak=4, xp=120, badges=None):
        self.streak = streak
        self.xp = xp
        self.badges = badges or [SimpleNamespace(label="Accuracy Ace")]

    async def summary(self, user_id: int):
        return SimpleNamespace(
            current_streak=self.streak,
            xp=self.xp,
            badges=self.badges,
        )


class FakeNotificationEngine:
    async def decide(self, user_id: int, assessment):
        return SimpleNamespace(
            should_send=True,
            channel="push",
            send_at=utc_now().replace(hour=18, minute=0, second=0, microsecond=0),
            reason="retention action selected",
        )


class FakeRetentionEngine:
    def __init__(self, *, streak=4, drop_off_risk=0.3):
        self.streak = streak
        self.drop_off_risk = drop_off_risk
        self.recorded = []

    async def assess_user(self, user_id: int):
        return SimpleNamespace(
            current_streak=self.streak,
            drop_off_risk=self.drop_off_risk,
            state="active",
            suggested_actions=[],
        )

    async def record_activity(self, user_id: int, occurred_at=None):
        self.recorded.append((user_id, occurred_at))


class FakeEventService:
    def __init__(self):
        self.calls = []

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None):
        self.calls.append((user_id, event_type, payload or {}))


class FakeDailyLoopHealthSignalService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str = "global"):
        self.calls.append(scope_key)
        return {"scope_key": scope_key}


def _factory_for(uow):
    return lambda: uow


def _event(event_type: str, days_ago: int = 0):
    return SimpleNamespace(
        event_type=event_type,
        created_at=utc_now() - timedelta(days=days_ago),
    )


def test_daily_loop_service_always_generates_a_mission():
    recommendation = SimpleNamespace(
        action="learn_new_word",
        target="travel",
        reason="Weak cluster",
        lesson_difficulty="medium",
        skill_focus="vocabulary",
    )
    health_signals = FakeDailyLoopHealthSignalService()
    service = DailyLoopService(
        _factory_for(
            FakeUOW(
                due_items=[SimpleNamespace(source_text="hola")],
                learning_state=SimpleNamespace(weak_areas=["travel"]),
            )
        ),
        FakeLearningEngine(recommendation),
        FakeGamificationService(),
        FakeNotificationEngine(),
        FakeRetentionEngine(drop_off_risk=0.2),
        FakeEventService(),
        health_signals,
    )

    plan = run_async(service.build_daily_loop(1))

    assert len(plan.mission) >= 1
    assert len(plan.mission) <= 3
    assert plan.weak_area == "vocabulary"
    assert plan.mission[0].target == "travel"
    assert plan.notification_preview["should_send"] is True
    assert plan.reward_preview["badge_hint"] == "Accuracy Ace"
    assert service._uow_factory()._daily_mission is not None
    assert service._uow_factory()._reward_chest is not None
    assert service._uow_factory()._decision_traces[0]["trace_type"] == "daily_mission_generation"
    assert health_signals.calls == ["global"]


def test_daily_loop_service_skip_shield_updates_correctly():
    recommendation = SimpleNamespace(
        action="review_word",
        target="hola",
        reason="Due review",
        lesson_difficulty="easy",
        skill_focus="vocabulary",
    )
    event_service = FakeEventService()
    health_signals = FakeDailyLoopHealthSignalService()
    service = DailyLoopService(
        _factory_for(FakeUOW()),
        FakeLearningEngine(recommendation),
        FakeGamificationService(streak=5),
        FakeNotificationEngine(),
        FakeRetentionEngine(streak=5),
        event_service,
        health_signals,
    )

    result = run_async(service.use_skip_shield(1))

    assert result.applied is True
    assert result.streak_preserved is True
    assert result.shields_remaining_this_week == 0
    assert event_service.calls[-1][1] == "skip_shield_used"
    assert health_signals.calls == ["global"]


def test_daily_loop_service_rewards_trigger_after_completion():
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar weak",
        lesson_difficulty="medium",
        skill_focus="grammar",
    )
    retention = FakeRetentionEngine(streak=6)
    event_service = FakeEventService()
    health_signals = FakeDailyLoopHealthSignalService()
    service = DailyLoopService(
        _factory_for(FakeUOW()),
        FakeLearningEngine(recommendation),
        FakeGamificationService(streak=6, xp=200),
        FakeNotificationEngine(),
        retention,
        event_service,
        health_signals,
    )

    run_async(service.build_daily_loop(1))
    result = run_async(service.complete_daily_mission(1))

    assert result.completed is True
    assert result.reward_chest_unlocked is True
    assert result.reward_preview["xp_reward"] == 25
    emitted_types = [call[1] for call in event_service.calls]
    assert "daily_mission_completed" in emitted_types
    assert "reward_chest_unlocked" in emitted_types
    assert retention.recorded[0][0] == 1
    assert service._uow_factory()._decision_traces[-1]["trace_type"] == "reward_chest_resolution"
    assert health_signals.calls == ["global", "global"]


def test_daily_loop_service_reuses_existing_mission_for_same_day():
    recommendation = SimpleNamespace(
        action="learn_new_word",
        target="travel",
        reason="Weak cluster",
        lesson_difficulty="medium",
        skill_focus="vocabulary",
    )
    uow = FakeUOW(
        due_items=[SimpleNamespace(source_text="hola")],
        learning_state=SimpleNamespace(weak_areas=["travel"]),
    )
    health_signals = FakeDailyLoopHealthSignalService()
    service = DailyLoopService(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeGamificationService(),
        FakeNotificationEngine(),
        FakeRetentionEngine(drop_off_risk=0.2),
        FakeEventService(),
        health_signals,
    )

    first = run_async(service.build_daily_loop(1))
    second = run_async(service.build_daily_loop(1))

    assert first.date == second.date
    assert first.mission[0].target == second.mission[0].target
    assert uow._daily_mission.id == 1
    assert health_signals.calls == ["global"]


def test_daily_loop_completion_is_idempotent_after_first_unlock():
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar weak",
        lesson_difficulty="medium",
        skill_focus="grammar",
    )
    retention = FakeRetentionEngine(streak=6)
    uow = FakeUOW()
    health_signals = FakeDailyLoopHealthSignalService()
    service = DailyLoopService(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeGamificationService(streak=6, xp=200),
        FakeNotificationEngine(),
        retention,
        FakeEventService(),
        health_signals,
    )

    run_async(service.build_daily_loop(1))
    first = run_async(service.complete_daily_mission(1))
    second = run_async(service.complete_daily_mission(1))

    assert first.reward_chest_unlocked is True
    assert second.reward_chest_unlocked is True
    assert second.completed is True
    assert health_signals.calls == ["global", "global"]


def test_daily_loop_claim_reward_chest_is_idempotent():
    recommendation = SimpleNamespace(
        action="practice_grammar",
        target="grammar",
        reason="Grammar weak",
        lesson_difficulty="medium",
        skill_focus="grammar",
    )
    event_service = FakeEventService()
    health_signals = FakeDailyLoopHealthSignalService()
    uow = FakeUOW()
    service = DailyLoopService(
        _factory_for(uow),
        FakeLearningEngine(recommendation),
        FakeGamificationService(streak=6, xp=200),
        FakeNotificationEngine(),
        FakeRetentionEngine(streak=6),
        event_service,
        health_signals,
    )

    run_async(service.build_daily_loop(1))
    run_async(service.complete_daily_mission(1))
    first = run_async(service.claim_reward_chest(1))
    second = run_async(service.claim_reward_chest(1))

    assert first.claimed is True
    assert first.already_claimed is False
    assert first.reward_preview["chest_state"] == "claimed"
    assert second.claimed is True
    assert second.already_claimed is True
    assert second.reward_preview["chest_state"] == "claimed"
    emitted_types = [call[1] for call in event_service.calls]
    assert emitted_types.count("reward_chest_claimed") == 1
    assert uow._decision_traces[-1]["source"] == "daily_loop_service.claim_reward_chest"
    assert health_signals.calls == ["global", "global", "global"]
