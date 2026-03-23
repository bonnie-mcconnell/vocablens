from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.onboarding_flow_service import OnboardingFlowService
from vocablens.services.report_models import OnboardingFlowState


class FakeEventsRepo:
    def __init__(self):
        self.events = []

    async def record(self, *, user_id: int, event_type: str, payload: dict, created_at=None) -> None:
        self.events.append(
            SimpleNamespace(
                user_id=user_id,
                event_type=event_type,
                payload=payload,
                created_at=created_at,
            )
        )

    async def list_by_user(self, user_id: int, limit: int = 200):
        rows = [event for event in self.events if event.user_id == user_id]
        return list(reversed(rows))[:limit]


class FakeProfilesRepo:
    def __init__(self):
        self.profiles = {}
        self.updated = []

    async def get_or_create(self, user_id: int):
        profile = self.profiles.get(user_id)
        if profile is None:
            profile = SimpleNamespace(
                preferred_channel="push",
                preferred_time_of_day=18,
                frequency_limit=2,
                difficulty_preference="medium",
                content_preference="mixed",
            )
            self.profiles[user_id] = profile
        return profile

    async def update(self, user_id: int, **kwargs):
        profile = await self.get_or_create(user_id)
        for key, value in kwargs.items():
            if value is not None:
                setattr(profile, key, value)
        self.updated.append((user_id, kwargs))


class FakeOnboardingStatesRepo:
    def __init__(self):
        self.states = {}

    async def get(self, user_id: int):
        return self.states.get(user_id)

    async def upsert(self, user_id: int, state: OnboardingFlowState):
        self.states[user_id] = state
        return state


class FakeDecisionTracesRepo:
    def __init__(self):
        self.rows = []

    async def create(self, **kwargs):
        self.rows.append(kwargs)
        return SimpleNamespace(**kwargs)


class FakeUOW:
    def __init__(
        self,
        events_repo: FakeEventsRepo,
        profiles_repo: FakeProfilesRepo,
        onboarding_states_repo: FakeOnboardingStatesRepo,
        decision_traces_repo: FakeDecisionTracesRepo,
    ):
        self.events = events_repo
        self.profiles = profiles_repo
        self.onboarding_states = onboarding_states_repo
        self.decision_traces = decision_traces_repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeWowEngine:
    def __init__(self, wow):
        self.wow = wow
        self.calls = []

    async def score_session(self, user_id: int, **kwargs):
        self.calls.append((user_id, kwargs))
        return self.wow


class FakeAddictionEngine:
    def __init__(self):
        self.plan = SimpleNamespace(
            reward={"bonus_xp": 9, "progress_increase": 2, "feedback": "Strong start"},
            pressure={"show_streak_decay_warning": False, "will_lose_progress": False},
            identity={"message": "You are becoming fluent."},
            ritual={"daily_ritual_hour": 19, "daily_ritual_message": "Make this your daily ritual around 19:00.", "streak_anchor": 2},
        )

    async def execute(self, user_id: int):
        return self.plan


class FakeLifecycleService:
    def __init__(self, stage: str = "new_user"):
        self.stage = stage

    async def evaluate(self, user_id: int):
        return SimpleNamespace(stage=self.stage)


class FakeAdaptivePaywallService:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
        self.started_trials = []

    async def evaluate(self, user_id: int, *, wow_score: float = 0.0, wow_moment: bool = False):
        self.calls.append({"user_id": user_id, "wow_score": wow_score, "wow_moment": wow_moment})
        return self.decision

    async def start_trial(self, user_id: int, duration_days: int | None = None):
        self.started_trials.append({"user_id": user_id, "duration_days": duration_days})


class FakeNotificationDecisionEngine:
    def __init__(self):
        self.calls = []
        self.decision = SimpleNamespace(
            should_send=True,
            send_at=SimpleNamespace(isoformat=lambda: "2026-03-21T19:00:00+00:00"),
            channel="push",
            reason="retention action selected",
        )

    async def decide(self, user_id: int, retention):
        self.calls.append({"user_id": user_id, "retention": retention})
        return self.decision


class FakeRetentionEngine:
    def __init__(self):
        self.assessment = SimpleNamespace(
            state="active",
            drop_off_risk=0.22,
            session_frequency=1.0,
            current_streak=1,
            longest_streak=1,
            last_active_at=None,
            is_high_engagement=False,
            suggested_actions=[],
        )

    async def assess_user(self, user_id: int):
        return self.assessment


def _wow(score: float, qualifies: bool, current_accuracy: float):
    return SimpleNamespace(
        score=score,
        tutor_interaction_score=0.3,
        accuracy_improvement_score=0.2,
        engagement_score=0.2,
        baseline_accuracy=0.5,
        current_accuracy=current_accuracy,
        qualifies=qualifies,
        triggers={"paywall": qualifies, "trial": score >= 0.8, "upsell": score >= 0.72},
    )


def _service(*, wow_score=0.82, qualifies=True, paywall=None):
    events_repo = FakeEventsRepo()
    profiles_repo = FakeProfilesRepo()
    onboarding_states_repo = FakeOnboardingStatesRepo()
    decision_traces_repo = FakeDecisionTracesRepo()
    paywall = paywall or SimpleNamespace(
        show_paywall=True,
        paywall_type="soft_paywall",
        reason="wow moment reached",
        usage_percent=24,
        allow_access=True,
        trial_recommended=True,
        trial_days=5,
        wow_score=wow_score,
        strategy="high_intent:early:premium_anchor",
    )
    service = OnboardingFlowService(
        lambda: FakeUOW(events_repo, profiles_repo, onboarding_states_repo, decision_traces_repo),
        FakeWowEngine(_wow(wow_score, qualifies, 0.81)),
        FakeAddictionEngine(),
        FakeLifecycleService(),
        FakeAdaptivePaywallService(paywall),
        FakeNotificationDecisionEngine(),
        FakeRetentionEngine(),
    )
    return service, events_repo, profiles_repo, decision_traces_repo


def test_onboarding_flow_service_transitions_through_identity_and_personalization():
    service, _, profiles, traces = _service()

    start = run_async(service.start(1))
    after_identity = run_async(service.next(1, {"motivation": "travel"}))
    after_personalization = run_async(
        service.next(
            1,
            {"skill_level": "beginner", "daily_goal": 10, "learning_intent": "conversation"},
        )
    )

    assert start["current_step"] == "identity_selection"
    assert after_identity["current_step"] == "personalization"
    assert after_personalization["current_step"] == "instant_wow_moment"
    assert profiles.profiles[1].difficulty_preference == "easy"
    assert profiles.profiles[1].content_preference == "conversation"
    assert traces.rows[0]["trace_type"] == "onboarding_transition"
    assert traces.rows[0]["outputs"]["to_step"] == "identity_selection"


def test_onboarding_flow_service_triggers_wow_and_advances_to_progress_illusion():
    service, _, _, traces = _service(wow_score=0.84, qualifies=True)
    run_async(service.start(2))
    run_async(service.next(2, {"motivation": "fluency"}))
    run_async(service.next(2, {"skill_level": "intermediate", "daily_goal": 15, "learning_intent": "conversation"}))

    response = run_async(
        service.next(
            2,
            {
                "session_snapshot": {
                    "tutor_mode": True,
                    "correction_feedback_count": 3,
                    "new_words_count": 2,
                    "grammar_mistake_count": 0,
                    "session_turn_count": 5,
                    "reply_length": 150,
                }
            },
        )
    )

    assert response["current_step"] == "progress_illusion"
    assert response["onboarding_state"]["wow"]["qualifies"] is True
    assert response["onboarding_state"]["wow"]["understood_percent"] == 81.0
    assert response["messaging"]["encouragement_message"].startswith("You picked up")
    assert any(row["trace_type"] == "onboarding_transition" and row["outputs"]["to_step"] == "progress_illusion" for row in traces.rows)


def test_onboarding_flow_service_times_soft_paywall_after_progress_illusion_only():
    service, _, _, traces = _service(wow_score=0.88, qualifies=True)
    run_async(service.start(3))
    run_async(service.next(3, {"motivation": "confidence"}))
    run_async(service.next(3, {"skill_level": "beginner", "daily_goal": 5, "learning_intent": "grammar"}))
    run_async(
        service.next(
            3,
            {
                "session_snapshot": {
                    "tutor_mode": True,
                    "correction_feedback_count": 2,
                    "new_words_count": 1,
                    "grammar_mistake_count": 0,
                    "session_turn_count": 4,
                    "reply_length": 120,
                }
            },
        )
    )

    response = run_async(service.next(3, {}))

    assert response["current_step"] == "soft_paywall"
    assert response["ui_directives"]["show_paywall"] is True
    assert response["onboarding_state"]["paywall"]["trial_recommended"] is True
    assert any(row["trace_type"] == "onboarding_paywall_entry" for row in traces.rows)


def test_onboarding_flow_service_locks_habit_and_schedules_notification():
    service, _, profiles, traces = _service(wow_score=0.86, qualifies=True)
    run_async(service.start(4))
    run_async(service.next(4, {"motivation": "travel"}))
    run_async(service.next(4, {"skill_level": "beginner", "daily_goal": 12, "learning_intent": "conversation"}))
    run_async(
        service.next(
            4,
            {
                "session_snapshot": {
                    "tutor_mode": True,
                    "correction_feedback_count": 3,
                    "new_words_count": 2,
                    "grammar_mistake_count": 0,
                    "session_turn_count": 5,
                    "reply_length": 150,
                }
            },
        )
    )
    run_async(service.next(4, {}))
    run_async(service.next(4, {"skip_paywall": True}))

    response = run_async(
        service.next(
            4,
            {
                "preferred_time_of_day": 19,
                "preferred_channel": "push",
                "frequency_limit": 1,
            },
        )
    )

    assert response["current_step"] == "completed"
    assert response["onboarding_state"]["habit_lock_in"]["preferred_time_of_day"] == 19
    assert response["onboarding_state"]["habit_lock_in"]["scheduled_notification"]["should_send"] is True
    assert profiles.profiles[4].preferred_time_of_day == 19
    assert response["ui_directives"]["show_streak_animation"] is True
    assert any(row["trace_type"] == "onboarding_transition" and row["outputs"]["to_step"] == "completed" for row in traces.rows)
