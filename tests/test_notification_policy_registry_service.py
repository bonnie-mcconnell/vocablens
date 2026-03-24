from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.services.notification_policy_registry_service import (
    NotificationPolicyRegistryService,
    NotificationPolicyRegistryUpsert,
)


def _policy_payload():
    return {
        "cooldown_hours": 6,
        "default_frequency_limit": 2,
        "default_preferred_time_of_day": 19,
        "stage_policies": {
            "new_user": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
            "activating": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
            "engaged": {"lifecycle_notifications_enabled": False, "suppression_reason": "quiet engaged users", "recovery_window_hours": 24},
            "at_risk": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 6},
            "churned": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 12},
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
    }


class FakeNotificationPolicyRegistryRepo:
    def __init__(self):
        self.rows = {
            "default": SimpleNamespace(
                policy_key="default",
                status="active",
                is_killed=False,
                description="Canonical notification policy.",
                policy=_policy_payload(),
                created_at=None,
                updated_at=None,
            )
        }

    async def get(self, policy_key: str):
        return self.rows.get(policy_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(self, **kwargs):
        row = SimpleNamespace(
            policy_key=kwargs["policy_key"],
            status=kwargs["status"],
            is_killed=kwargs["is_killed"],
            description=kwargs["description"],
            policy=dict(kwargs["policy"]),
            created_at=None,
            updated_at=None,
        )
        self.rows[kwargs["policy_key"]] = row
        return row


class FakeNotificationPolicyAuditRepo:
    def __init__(self):
        self.entries = []

    async def create(self, **kwargs):
        row = SimpleNamespace(id=len(self.entries) + 1, created_at=None, **kwargs)
        self.entries.append(row)
        return row

    async def list_by_policy(self, policy_key: str, limit: int = 50):
        rows = [row for row in self.entries if row.policy_key == policy_key]
        return list(reversed(rows))[:limit]

    async def latest_for_policy(self, policy_key: str):
        for row in reversed(self.entries):
            if row.policy_key == policy_key:
                return row
        return None


class FakeUOW:
    def __init__(self):
        self.notification_policy_registries = FakeNotificationPolicyRegistryRepo()
        self.notification_policy_audits = FakeNotificationPolicyAuditRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_notification_policy_registry_service_returns_policy():
    uow = FakeUOW()
    service = NotificationPolicyRegistryService(lambda: uow)

    payload = run_async(service.get_policy("default"))

    assert payload["policy"]["policy_key"] == "default"
    assert payload["policy"]["policy"]["cooldown_hours"] == 6


def test_notification_policy_registry_service_writes_audit_on_update():
    uow = FakeUOW()
    service = NotificationPolicyRegistryService(lambda: uow)
    updated_policy = _policy_payload()
    updated_policy["cooldown_hours"] = 8

    payload = run_async(
        service.upsert_policy(
            policy_key="default",
            command=NotificationPolicyRegistryUpsert(
                status="paused",
                is_killed=False,
                description="Canonical notification policy.",
                policy=updated_policy,
                change_note="Paused notification policy for review.",
            ),
            changed_by="ops@vocablens",
        )
    )

    assert payload["policy"]["status"] == "paused"
    assert payload["policy"]["policy"]["cooldown_hours"] == 8
    assert payload["policy"]["audit_entries"][0]["action"] == "status_paused"


def test_notification_policy_registry_service_rejects_invalid_stage_shape():
    uow = FakeUOW()
    service = NotificationPolicyRegistryService(lambda: uow)
    invalid_policy = _policy_payload()
    invalid_policy["stage_policies"].pop("engaged")

    with pytest.raises(ValidationError):
        run_async(
            service.upsert_policy(
                policy_key="default",
                command=NotificationPolicyRegistryUpsert(
                    status="active",
                    is_killed=False,
                    description="Canonical notification policy.",
                    policy=invalid_policy,
                    change_note="Trying invalid stage policy shape.",
                ),
                changed_by="ops@vocablens",
            )
        )


def test_notification_policy_registry_service_raises_on_missing_policy():
    uow = FakeUOW()
    service = NotificationPolicyRegistryService(lambda: uow)

    with pytest.raises(NotFoundError):
        run_async(service.get_policy("missing"))
