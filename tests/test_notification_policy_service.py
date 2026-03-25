from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.notification_policy_service import NotificationPolicyService


class FakeNotificationPolicyRegistryRepo:
    async def get(self, policy_key: str):
        return SimpleNamespace(
            policy_key=policy_key,
            status="active",
            is_killed=False,
            policy={
                "cooldown_hours": 6,
                "default_frequency_limit": 1,
                "default_preferred_time_of_day": 20,
                "stage_policies": {
                    "new_user": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "activating": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "engaged": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "at_risk": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 4},
                    "churned": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 8},
                },
                "suppression_overrides": [
                    {
                        "source_context": "lifecycle_service.notification",
                        "stage": "engaged",
                        "lifecycle_notifications_enabled": False,
                        "suppression_reason": "quiet engaged users",
                        "recovery_window_hours": 24,
                    }
                ],
            },
        )


class FakeUOW:
    def __init__(self):
        self.notification_policy_registries = FakeNotificationPolicyRegistryRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_notification_policy_service_resolves_source_override():
    service = NotificationPolicyService(lambda: FakeUOW())

    policy = run_async(service.current_policy())
    stage_policy = run_async(service.lifecycle_stage_policy("engaged", source_context="lifecycle_service.notification"))

    assert policy.cooldown_hours == 6
    assert policy.default_frequency_limit == 1
    assert policy.governance.min_sample_size == 25
    assert stage_policy.lifecycle_notifications_enabled is False
    assert stage_policy.suppression_reason == "quiet engaged users"
    assert stage_policy.recovery_window_hours == 24
