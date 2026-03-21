from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.services.virality_service import ViralityService


class FakeUsersRepo:
    def __init__(self, users):
        self.users = {user.id: user for user in users}

    async def get_by_id(self, user_id: int):
        return self.users.get(user_id)


class FakeEventsRepo:
    def __init__(self, events=None):
        self.events = list(events or [])

    async def list_by_user(self, user_id: int, limit: int = 500):
        return [event for event in self.events if event.user_id == user_id][:limit]


class FakeUOW:
    def __init__(self, users, events=None):
        self.users = FakeUsersRepo(users)
        self.events = FakeEventsRepo(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeProgressService:
    async def build_dashboard(self, user_id: int):
        return {
            "streak": 4 if user_id == 1 else 1,
            "metrics": {
                "vocabulary_mastery_percent": 61.4,
                "accuracy_rate": 84.8,
                "fluency_score": 73.2,
            },
        }


class FakeSubscriptionService:
    def __init__(self, features):
        self.features = features
        self.started_trials = []

    async def get_features(self, user_id: int):
        return self.features[user_id]

    async def start_trial(self, user_id: int, duration_days: int | None = None):
        self.started_trials.append({"user_id": user_id, "duration_days": duration_days})
        feature = self.features[user_id]
        self.features[user_id] = SimpleNamespace(
            tier=feature.tier,
            trial_active=True,
        )
        return self.features[user_id]


class FakeEventService:
    def __init__(self):
        self.events = []

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None):
        event = SimpleNamespace(user_id=user_id, event_type=event_type, payload=payload or {})
        self.events.append(event)


class FakeViralMomentService:
    async def best_share_moment(self, user_id: int, moment_type: str | None = None):
        return SimpleNamespace(
            type=moment_type or "streak_flex",
            hook="I actually stuck with this.",
            caption="7-day streak and climbing.",
            share_text="7-day streak. Level 3. 645 XP.",
            visual_payload={"badge": "streak_master", "streak_days": 7},
            source_signals={"current_streak": 7},
            priority=0.88,
        )


def _service(*, users, events=None, features=None):
    event_service = FakeEventService()
    subscription_service = FakeSubscriptionService(
        features
        or {
            1: SimpleNamespace(tier="free", trial_active=False),
            2: SimpleNamespace(tier="free", trial_active=False),
        }
    )
    service = ViralityService(
        lambda: FakeUOW(users, events),
        FakeProgressService(),
        subscription_service,
        event_service,
        FakeViralMomentService(),
        share_base_url="https://example.test",
        referral_xp_reward=300,
        referral_premium_days=5,
    )
    return service, subscription_service, event_service


def test_virality_service_builds_deterministic_invite_and_share_message():
    users = [SimpleNamespace(id=1, email="user@example.com")]
    service, _, events = _service(users=users)

    first = run_async(service.build_invite(1))
    second = run_async(service.build_invite(1))

    assert first.code == second.code
    assert first.code.startswith("VL-1-")
    assert first.share_url.endswith(first.code)
    assert "5 free Pro day(s)" in first.share_message
    assert events.events[0].event_type == "referral_invite_created"


def test_virality_service_redeems_invite_and_grants_rewards_once():
    users = [
        SimpleNamespace(id=1, email="referrer@example.com"),
        SimpleNamespace(id=2, email="friend@example.com"),
    ]
    service, subscriptions, events = _service(users=users)
    invite = run_async(service.build_invite(1))

    result = run_async(service.redeem_invite(code=invite.code, referred_user_id=2))

    assert result.referrer_user_id == 1
    assert result.referred_user_id == 2
    assert result.awarded_xp == 300
    assert result.awarded_premium_days_referrer == 5
    assert result.awarded_premium_days_referred == 5
    assert subscriptions.started_trials == [
        {"user_id": 1, "duration_days": 5},
        {"user_id": 2, "duration_days": 5},
    ]
    assert [event.event_type for event in events.events[-3:]] == [
        "referral_redeemed",
        "referral_reward_granted",
        "referral_reward_granted",
    ]


def test_virality_service_blocks_duplicate_redemption():
    users = [
        SimpleNamespace(id=1, email="referrer@example.com"),
        SimpleNamespace(id=2, email="friend@example.com"),
    ]
    prior_events = [
        SimpleNamespace(
            user_id=2,
            event_type="referral_redeemed",
            payload={"referrer_user_id": 1},
        )
    ]
    service, subscriptions, _ = _service(users=users, events=prior_events)
    invite = run_async(service.build_invite(1))

    with pytest.raises(ValueError, match="already redeemed"):
        run_async(service.redeem_invite(code=invite.code, referred_user_id=2))

    assert subscriptions.started_trials == []


def test_virality_service_builds_progress_share_payload():
    users = [SimpleNamespace(id=1, email="user@example.com")]
    service, _, events = _service(users=users)

    share = run_async(service.share_progress(1))

    assert share.stats["streak"] == 4
    assert share.stats["mastery_percent"] == 61.4
    assert "4-day VocabLens streak" in share.share_text
    assert share.share_url.startswith("https://example.test/share/progress?")
    assert events.events[-1].event_type == "progress_shared"


def test_virality_service_builds_share_payload_from_viral_moment_service():
    users = [SimpleNamespace(id=1, email="user@example.com")]
    service, _, events = _service(users=users)

    share = run_async(service.share_moment(1))

    assert share.moment_type == "streak_flex"
    assert share.share_text == "7-day streak. Level 3. 645 XP."
    assert share.share_url.startswith("https://example.test/share/moment?")
    assert share.hook == "I actually stuck with this."
    assert events.events[-1].event_type == "progress_shared"
