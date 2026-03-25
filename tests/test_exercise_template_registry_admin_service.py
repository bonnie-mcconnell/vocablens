from types import SimpleNamespace
from datetime import timedelta

import pytest

from tests.conftest import run_async
from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.core.time import utc_now
from vocablens.services.exercise_template_registry_admin_service import (
    ExerciseTemplateRegistryAdminService,
    ExerciseTemplateRegistryUpsert,
)


class FakeExerciseTemplateRepo:
    def __init__(self):
        now = utc_now()
        self.rows = {
            "recall_fill_blank_v1": SimpleNamespace(
                template_key="recall_fill_blank_v1",
                exercise_type="fill_blank",
                objective="recall",
                difficulty="medium",
                status="active",
                prompt_template="Fill the blank with {target}.",
                answer_source="target",
                choice_count=None,
                template_metadata={"description": "Recall template."},
                created_at=now - timedelta(days=14),
                updated_at=now - timedelta(days=1),
            ),
            "discrimination_choice_v1": SimpleNamespace(
                template_key="discrimination_choice_v1",
                exercise_type="multiple_choice",
                objective="discrimination",
                difficulty="medium",
                status="draft",
                prompt_template="Choose the option that best matches {target}.",
                answer_source="target",
                choice_count=4,
                template_metadata={"description": "Draft discrimination template."},
                created_at=now - timedelta(days=10),
                updated_at=now - timedelta(days=2),
            ),
            "correction_fill_blank_v1": SimpleNamespace(
                template_key="correction_fill_blank_v1",
                exercise_type="fill_blank",
                objective="correction",
                difficulty="hard",
                status="archived",
                prompt_template="Fix the phrase using {target}.",
                answer_source="target",
                choice_count=None,
                template_metadata={"description": "Retired correction template."},
                created_at=now - timedelta(days=20),
                updated_at=now - timedelta(days=8),
            )
        }

    async def get_by_key(self, template_key: str):
        return self.rows.get(template_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(self, **kwargs):
        existing = self.rows.get(kwargs["template_key"])
        row = SimpleNamespace(
            template_key=kwargs["template_key"],
            exercise_type=kwargs["exercise_type"],
            objective=kwargs["objective"],
            difficulty=kwargs["difficulty"],
            status=kwargs["status"],
            prompt_template=kwargs["prompt_template"],
            answer_source=kwargs["answer_source"],
            choice_count=kwargs["choice_count"],
            template_metadata=dict(kwargs["template_metadata"]),
            created_at=getattr(existing, "created_at", None),
            updated_at=None,
        )
        self.rows[kwargs["template_key"]] = row
        return row


class FakeExerciseTemplateAuditRepo:
    def __init__(self):
        now = utc_now()
        self.rows = [
            SimpleNamespace(
                id=1,
                template_key="recall_fill_blank_v1",
                action="status_changed",
                changed_by="ops@vocablens",
                change_note="Promoted recall template after fixture review.",
                previous_config={"status": "draft"},
                new_config={"status": "active"},
                fixture_report={
                    "fixture_count": 2,
                    "fixtures": [
                        {"status": "passed"},
                        {"status": "passed"},
                    ],
                },
                created_at=now - timedelta(days=2),
            ),
            SimpleNamespace(
                id=2,
                template_key="discrimination_choice_v1",
                action="updated",
                changed_by="ops@vocablens",
                change_note="Left in draft after fixture failure.",
                previous_config={"status": "draft"},
                new_config={"status": "draft"},
                fixture_report={
                    "fixture_count": 2,
                    "fixtures": [
                        {"status": "passed"},
                        {"status": "rejected"},
                    ],
                },
                created_at=now - timedelta(days=1),
            ),
        ]

    async def create(self, **kwargs):
        row = SimpleNamespace(id=len(self.rows) + 1, created_at=None, **kwargs)
        self.rows.append(row)
        return row

    async def list_by_template(self, template_key: str, limit: int = 50):
        rows = [row for row in self.rows if row.template_key == template_key]
        return list(reversed(rows))[:limit]

    async def latest_for_template(self, template_key: str):
        for row in reversed(self.rows):
            if row.template_key == template_key:
                return row
        return None


class FakeUOW:
    def __init__(self):
        self.exercise_templates = FakeExerciseTemplateRepo()
        self.exercise_template_audits = FakeExerciseTemplateAuditRepo()
        self.content_quality_checks = FakeContentQualityChecksRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeContentQualityGate:
    def lint_template_fixture(self, **kwargs):
        template_key = kwargs["template_key"]
        if template_key == "bad_template_v1":
            return {
                "fixture": {"target": "travel"},
                "exercise": {},
                "violations": [{"code": "answer_contract_invalid", "severity": "critical"}],
                "status": "rejected",
            }
        return {
            "fixture": {"target": "travel"},
            "exercise": {},
            "violations": [],
            "status": "passed",
        }


class FakeContentQualityChecksRepo:
    def __init__(self):
        now = utc_now()
        self.rows = [
            SimpleNamespace(
                artifact_type="generated_lesson",
                status="passed",
                checked_at=now - timedelta(days=1),
                artifact_summary={"template_keys": ["recall_fill_blank_v1"]},
            ),
            SimpleNamespace(
                artifact_type="generated_lesson",
                status="rejected",
                checked_at=now - timedelta(hours=6),
                artifact_summary={"template_keys": ["recall_fill_blank_v1", "discrimination_choice_v1"]},
            ),
            SimpleNamespace(
                artifact_type="structured_session",
                status="passed",
                checked_at=now - timedelta(hours=5),
                artifact_summary={},
            ),
        ]

    async def list_since(self, since, limit: int = 1000):
        rows = [row for row in self.rows if getattr(row, "checked_at", None) is None or row.checked_at >= since]
        return rows[:limit]


def test_exercise_template_registry_admin_service_lists_templates():
    service = ExerciseTemplateRegistryAdminService(lambda: FakeUOW(), FakeContentQualityGate())

    payload = run_async(service.list_templates())

    assert payload["templates"][0]["template_key"] == "recall_fill_blank_v1"
    assert payload["templates"][0]["status"] == "active"


def test_exercise_template_registry_admin_service_writes_audit_and_fixture_report():
    uow = FakeUOW()
    service = ExerciseTemplateRegistryAdminService(lambda: uow, FakeContentQualityGate())

    payload = run_async(
        service.upsert_template(
            template_key="discrimination_choice_v2",
            command=ExerciseTemplateRegistryUpsert(
                status="active",
                exercise_type="multiple_choice",
                objective="discrimination",
                difficulty="medium",
                prompt_template="Choose the option that best matches {target}.",
                answer_source="target",
                choice_count=4,
                description="Discrimination template.",
                metadata={"surface": "lesson"},
                change_note="Promote validated discrimination template.",
            ),
            changed_by="ops@vocablens",
        )
    )

    assert payload["template"]["template_key"] == "discrimination_choice_v2"
    assert payload["template"]["audit_entries"][0]["changed_by"] == "ops@vocablens"
    assert payload["template"]["audit_entries"][0]["fixture_report"]["fixture_count"] >= 1


def test_exercise_template_registry_admin_service_rejects_failed_promotion_fixture():
    service = ExerciseTemplateRegistryAdminService(lambda: FakeUOW(), FakeContentQualityGate())

    with pytest.raises(ValidationError):
        run_async(
            service.upsert_template(
                template_key="bad_template_v1",
                command=ExerciseTemplateRegistryUpsert(
                    status="active",
                    exercise_type="fill_blank",
                    objective="recall",
                    difficulty="medium",
                    prompt_template="Fill the blank with {target}.",
                    answer_source="target",
                    choice_count=None,
                    description="Bad template.",
                    metadata={},
                    change_note="Promote bad template for testing.",
                ),
                changed_by="ops@vocablens",
            )
        )


def test_exercise_template_registry_admin_service_raises_on_unknown_template():
    service = ExerciseTemplateRegistryAdminService(lambda: FakeUOW(), FakeContentQualityGate())

    with pytest.raises(NotFoundError):
        run_async(service.get_template("unknown_template"))


def test_exercise_template_registry_admin_service_builds_health_dashboard():
    service = ExerciseTemplateRegistryAdminService(lambda: FakeUOW(), FakeContentQualityGate())

    payload = run_async(service.get_health_dashboard(limit=10))

    assert payload["summary"]["total_templates"] == 3
    assert payload["summary"]["counts_by_status"] == {"active": 1, "archived": 1, "draft": 1}
    assert payload["summary"]["templates_with_failed_fixtures"] == 1
    assert payload["summary"]["templates_with_runtime_rejections"] == 2
    assert payload["summary"]["recent_audit_count_7d"] == 2
    assert payload["attention"][0]["template_key"] == "discrimination_choice_v1"
    assert payload["attention"][0]["latest_failed_fixture_count"] == 1
    recall_row = next(item for item in payload["templates"] if item["template_key"] == "recall_fill_blank_v1")
    assert recall_row["runtime_usage_count_7d"] == 2
    assert recall_row["runtime_rejection_count_7d"] == 1
    assert recall_row["latest_fixture_status"] == "passed"
