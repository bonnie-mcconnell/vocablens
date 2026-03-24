from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.services.experiment_registry_service import (
    ExperimentRegistryService,
    ExperimentRegistryUpsert,
    ExperimentRegistryVariantInput,
)


class FakeExperimentRegistryRepo:
    def __init__(self):
        self.rows = {
            "paywall_offer": SimpleNamespace(
                experiment_key="paywall_offer",
                status="active",
                rollout_percentage=100,
                holdout_percentage=0,
                is_killed=False,
                baseline_variant="control",
                description="Controls paywall offer composition.",
                variants=[{"name": "control", "weight": 80}, {"name": "annual_anchor", "weight": 20}],
                eligibility={},
                mutually_exclusive_with=[],
                prerequisite_experiments=[],
                created_at=None,
                updated_at=None,
            )
        }

    async def get(self, experiment_key: str):
        return self.rows.get(experiment_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(self, **kwargs):
        existing = self.rows.get(kwargs["experiment_key"])
        row = SimpleNamespace(
            experiment_key=kwargs["experiment_key"],
            status=kwargs["status"],
            rollout_percentage=kwargs["rollout_percentage"],
            holdout_percentage=kwargs["holdout_percentage"],
            is_killed=kwargs["is_killed"],
            baseline_variant=kwargs["baseline_variant"],
            description=kwargs["description"],
            variants=list(kwargs["variants"]),
            eligibility=dict(kwargs["eligibility"]),
            mutually_exclusive_with=list(kwargs["mutually_exclusive_with"]),
            prerequisite_experiments=list(kwargs["prerequisite_experiments"]),
            created_at=getattr(existing, "created_at", None),
            updated_at=None,
        )
        self.rows[kwargs["experiment_key"]] = row
        return row


class FakeAssignmentRepo:
    async def list_all(self, experiment_key: str | None = None):
        rows = [
            SimpleNamespace(experiment_key="paywall_offer", variant="control"),
            SimpleNamespace(experiment_key="paywall_offer", variant="control"),
            SimpleNamespace(experiment_key="paywall_offer", variant="annual_anchor"),
        ]
        if experiment_key is None:
            return rows
        return [row for row in rows if row.experiment_key == experiment_key]


class FakeExposureRepo:
    async def list_all(self, experiment_key: str | None = None):
        rows = [
            SimpleNamespace(experiment_key="paywall_offer", variant="control"),
            SimpleNamespace(experiment_key="paywall_offer", variant="annual_anchor"),
        ]
        if experiment_key is None:
            return rows
        return [row for row in rows if row.experiment_key == experiment_key]


class FakeOutcomeAttributionRepo:
    async def list_all(self, experiment_key: str | None = None):
        rows = [
            SimpleNamespace(
                user_id=1,
                experiment_key="paywall_offer",
                variant="control",
                assignment_reason="rollout",
                attribution_version="v1",
                exposed_at=None,
                window_end_at=None,
                retained_d1=True,
                retained_d7=False,
                converted=False,
                first_conversion_at=None,
                session_count=1,
                message_count=1,
                learning_action_count=0,
                upgrade_click_count=0,
                last_event_at=None,
            ),
            SimpleNamespace(
                user_id=2,
                experiment_key="paywall_offer",
                variant="annual_anchor",
                assignment_reason="rollout",
                attribution_version="v1",
                exposed_at=None,
                window_end_at=None,
                retained_d1=True,
                retained_d7=True,
                converted=True,
                first_conversion_at=None,
                session_count=2,
                message_count=0,
                learning_action_count=1,
                upgrade_click_count=1,
                last_event_at=None,
            ),
        ]
        if experiment_key is None:
            return rows
        return [row for row in rows if row.experiment_key == experiment_key]


class FakeAuditRepo:
    def __init__(self):
        self.entries = []

    async def create(self, **kwargs):
        row = SimpleNamespace(id=len(self.entries) + 1, created_at=None, **kwargs)
        self.entries.append(row)
        return row

    async def list_by_experiment(self, experiment_key: str, limit: int = 50):
        rows = [row for row in self.entries if row.experiment_key == experiment_key]
        return list(reversed(rows))[:limit]

    async def latest_for_experiment(self, experiment_key: str):
        for row in reversed(self.entries):
            if row.experiment_key == experiment_key:
                return row
        return None


class FakeDecisionTraceRepo:
    async def list_recent(self, *, user_id=None, trace_type: str | None = None, reference_id: str | None = None, limit: int = 100):
        rows = [
            SimpleNamespace(
                id=12,
                user_id=2,
                trace_type="experiment_assignment",
                source="experiment_service",
                reference_id="paywall_offer",
                policy_version="v1",
                inputs={"context": {"subscription_tier": "free"}},
                outputs={"variant": "annual_anchor", "assignment_reason": "rollout"},
                reason="Persisted the first canonical assignment and exposure for this experiment.",
                created_at=None,
            )
        ]
        if trace_type is not None:
            rows = [row for row in rows if row.trace_type == trace_type]
        if reference_id is not None:
            rows = [row for row in rows if row.reference_id == reference_id]
        if user_id is not None:
            rows = [row for row in rows if row.user_id == user_id]
        return rows[:limit]


class FakeUOW:
    def __init__(self):
        self.experiment_registries = FakeExperimentRegistryRepo()
        self.experiment_assignments = FakeAssignmentRepo()
        self.experiment_exposures = FakeExposureRepo()
        self.experiment_outcome_attributions = FakeOutcomeAttributionRepo()
        self.experiment_registry_audits = FakeAuditRepo()
        self.decision_traces = FakeDecisionTraceRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_experiment_registry_service_returns_health_summary():
    uow = FakeUOW()
    service = ExperimentRegistryService(lambda: uow)

    payload = run_async(service.get_registry("paywall_offer"))

    assert payload["experiment"]["health"]["assignment_count"] == 3
    assert payload["experiment"]["health"]["exposure_count"] == 2
    assert payload["experiment"]["health"]["exposure_gap"] == 1


def test_experiment_registry_service_returns_operator_report():
    uow = FakeUOW()
    service = ExperimentRegistryService(lambda: uow)

    payload = run_async(service.get_operator_report("paywall_offer", limit=10))

    assert payload["experiment"]["results"]["experiment_key"] == "paywall_offer"
    assert payload["experiment"]["attribution_summary"]["users"] == 2
    assert payload["experiment"]["attribution_summary"]["converted_users"] == 1
    assert payload["experiment"]["recent_exposures"][0]["variant"] == "annual_anchor"
    assert payload["experiment"]["latest_assignment_trace"]["trace_type"] == "experiment_assignment"


def test_experiment_registry_service_writes_audit_entry_on_update():
    uow = FakeUOW()
    service = ExperimentRegistryService(lambda: uow)

    payload = run_async(
        service.upsert_registry(
            experiment_key="paywall_offer",
            command=ExperimentRegistryUpsert(
                status="paused",
                rollout_percentage=100,
                is_killed=False,
                description="Controls paywall offer composition.",
                variants=(
                    ExperimentRegistryVariantInput(name="control", weight=70),
                    ExperimentRegistryVariantInput(name="annual_anchor", weight=30),
                ),
                change_note="Paused rollout during diagnostics.",
                holdout_percentage=10,
                baseline_variant="control",
                eligibility={"geographies": ("us", "nz")},
                mutually_exclusive_with=("paywall_pricing_messaging",),
            ),
            changed_by="ops@vocablens",
        )
    )

    assert payload["experiment"]["status"] == "paused"
    assert payload["experiment"]["holdout_percentage"] == 10
    assert payload["experiment"]["eligibility"]["geographies"] == ["us", "nz"]
    assert payload["experiment"]["audit_entries"][0]["action"] == "status_paused"
    assert payload["experiment"]["audit_entries"][0]["changed_by"] == "ops@vocablens"


def test_experiment_registry_service_rejects_missing_control_variant():
    uow = FakeUOW()
    service = ExperimentRegistryService(lambda: uow)

    with pytest.raises(ValidationError):
        run_async(
            service.upsert_registry(
                experiment_key="paywall_offer",
                command=ExperimentRegistryUpsert(
                    status="active",
                    rollout_percentage=100,
                    is_killed=False,
                    description="Controls paywall offer composition.",
                    variants=(ExperimentRegistryVariantInput(name="annual_anchor", weight=100),),
                    change_note="Testing invalid config.",
                ),
                changed_by="ops@vocablens",
            )
        )


def test_experiment_registry_service_rejects_archived_reactivation():
    uow = FakeUOW()
    uow.experiment_registries.rows["paywall_offer"].status = "archived"
    service = ExperimentRegistryService(lambda: uow)

    with pytest.raises(ValidationError):
        run_async(
            service.upsert_registry(
                experiment_key="paywall_offer",
                command=ExperimentRegistryUpsert(
                    status="active",
                    rollout_percentage=100,
                    is_killed=False,
                    description="Controls paywall offer composition.",
                    variants=(
                        ExperimentRegistryVariantInput(name="control", weight=80),
                        ExperimentRegistryVariantInput(name="annual_anchor", weight=20),
                    ),
                    change_note="Trying to reactivate an archived record.",
                ),
                changed_by="ops@vocablens",
            )
        )


def test_experiment_registry_service_raises_on_unknown_experiment():
    uow = FakeUOW()
    service = ExperimentRegistryService(lambda: uow)

    with pytest.raises(NotFoundError):
        run_async(service.get_registry("unknown_test"))


def test_experiment_registry_service_rejects_invalid_baseline_and_duplicate_policy_entries():
    uow = FakeUOW()
    service = ExperimentRegistryService(lambda: uow)

    with pytest.raises(ValidationError):
        run_async(
            service.upsert_registry(
                experiment_key="paywall_offer",
                command=ExperimentRegistryUpsert(
                    status="active",
                    rollout_percentage=100,
                    is_killed=False,
                    description="Controls paywall offer composition.",
                    variants=(
                        ExperimentRegistryVariantInput(name="control", weight=80),
                        ExperimentRegistryVariantInput(name="annual_anchor", weight=20),
                    ),
                    change_note="Trying invalid policy values.",
                    baseline_variant="missing_variant",
                    mutually_exclusive_with=("pricing_test", "pricing_test"),
                ),
                changed_by="ops@vocablens",
            )
        )
