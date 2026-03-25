from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re
from typing import Any

from vocablens.core.time import utc_now
from vocablens.domain.errors import NotFoundError, ValidationError
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.content_quality_gate_service import ContentQualityGateService
from vocablens.services.exercise_template_fixtures import PROMOTION_FIXTURES


_VALID_STATUSES = {"draft", "active", "archived"}
_VALID_EXERCISE_TYPES = {"fill_blank", "multiple_choice"}
_VALID_OBJECTIVES = {"recall", "discrimination", "correction", "reinforcement", "production"}
_VALID_DIFFICULTIES = {"easy", "medium", "hard"}
_VALID_ANSWER_SOURCES = {"target", "vocab_first", "vocab_last"}
_TEMPLATE_KEY_PATTERN = re.compile(r"^[a-z0-9_]{3,80}$")


@dataclass(frozen=True)
class ExerciseTemplateRegistryUpsert:
    status: str
    exercise_type: str
    objective: str
    difficulty: str
    prompt_template: str
    answer_source: str
    choice_count: int | None
    description: str | None
    metadata: dict[str, Any]
    change_note: str


class ExerciseTemplateRegistryAdminService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        content_quality_gate: ContentQualityGateService,
        health_signal_service=None,
    ):
        self._uow_factory = uow_factory
        self._content_quality_gate = content_quality_gate
        self._health_signals = health_signal_service

    async def list_templates(self) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            templates = await uow.exercise_templates.list_all()
            latest_audits = {}
            for template in templates:
                latest_audits[template.template_key] = await uow.exercise_template_audits.latest_for_template(
                    template.template_key
                )
            await uow.commit()
        return {
            "templates": [
                self._summary_payload(template, latest_audit=latest_audits.get(template.template_key))
                for template in templates
            ]
        }

    async def get_template(self, template_key: str) -> dict[str, Any]:
        normalized_key = self._validate_template_key(template_key)
        async with self._uow_factory() as uow:
            template = await uow.exercise_templates.get_by_key(normalized_key)
            if template is None:
                raise NotFoundError(f"Exercise template '{normalized_key}' not found")
            audits = await uow.exercise_template_audits.list_by_template(normalized_key, limit=50)
            await uow.commit()
        return {"template": self._detail_payload(template, audits)}

    async def upsert_template(
        self,
        *,
        template_key: str,
        command: ExerciseTemplateRegistryUpsert,
        changed_by: str | None,
    ) -> dict[str, Any]:
        normalized_key = self._validate_template_key(template_key)
        self._validate_command(normalized_key, command)
        actor = self._normalize_actor(changed_by)
        fixture_report = self._fixture_report(normalized_key, command)
        self._validate_promotion(command, fixture_report)
        async with self._uow_factory() as uow:
            existing = await uow.exercise_templates.get_by_key(normalized_key)
            self._validate_transition(existing.status if existing else None, command.status)
            previous_config = self._template_config(existing) if existing is not None else {}
            saved = await uow.exercise_templates.upsert(
                template_key=normalized_key,
                exercise_type=command.exercise_type,
                objective=command.objective,
                difficulty=command.difficulty,
                status=command.status,
                prompt_template=command.prompt_template.strip(),
                answer_source=command.answer_source,
                choice_count=command.choice_count,
                template_metadata={
                    **dict(command.metadata or {}),
                    "description": (command.description or "").strip() or None,
                },
            )
            audit = await uow.exercise_template_audits.create(
                template_key=normalized_key,
                action=self._audit_action(existing, command),
                changed_by=actor,
                change_note=command.change_note.strip(),
                previous_config=previous_config,
                new_config=self._template_config(saved),
                fixture_report=fixture_report,
            )
            await uow.commit()
        if self._health_signals is not None:
            await self._health_signals.evaluate_scope("global")
        return {"template": self._detail_payload(saved, [audit])}

    async def list_audit_history(self, template_key: str, *, limit: int = 50) -> dict[str, Any]:
        normalized_key = self._validate_template_key(template_key)
        async with self._uow_factory() as uow:
            template = await uow.exercise_templates.get_by_key(normalized_key)
            if template is None:
                raise NotFoundError(f"Exercise template '{normalized_key}' not found")
            audits = await uow.exercise_template_audits.list_by_template(normalized_key, limit=max(1, min(limit, 200)))
            await uow.commit()
        return {"audit_entries": [self._audit_payload(item) for item in audits]}

    async def get_health_dashboard(self, *, limit: int = 50) -> dict[str, Any]:
        normalized_limit = max(1, min(limit, 200))
        window_start = utc_now() - timedelta(days=7)
        async with self._uow_factory() as uow:
            templates = await uow.exercise_templates.list_all()
            latest_audits: dict[str, Any] = {}
            recent_audits: list[Any] = []
            for template in templates:
                template_key = str(template.template_key)
                latest_audits[template_key] = await uow.exercise_template_audits.latest_for_template(template_key)
                recent_audits.extend(await uow.exercise_template_audits.list_by_template(template_key, limit=10))
            checks = await uow.content_quality_checks.list_since(window_start, limit=5000)
            await uow.commit()

        usage_by_template: dict[str, int] = {}
        rejection_by_template: dict[str, int] = {}
        for check in checks:
            if str(getattr(check, "artifact_type", "") or "") != "generated_lesson":
                continue
            summary = dict(getattr(check, "artifact_summary", {}) or {})
            template_keys = [
                str(item).strip()
                for item in list(summary.get("template_keys") or [])
                if str(item).strip()
            ]
            for template_key in template_keys:
                usage_by_template[template_key] = usage_by_template.get(template_key, 0) + 1
                if str(getattr(check, "status", "") or "") == "rejected":
                    rejection_by_template[template_key] = rejection_by_template.get(template_key, 0) + 1

        rows = []
        counts_by_status: dict[str, int] = {}
        failed_fixtures = 0
        runtime_rejections = 0
        latest_audit_at = None
        recent_audit_count = 0
        for audit in recent_audits:
            created_at = getattr(audit, "created_at", None)
            if created_at is not None and created_at >= window_start:
                recent_audit_count += 1
            latest_audit_at = self._max_timestamp(latest_audit_at, created_at)

        for template in templates:
            template_key = str(template.template_key)
            latest_audit = latest_audits.get(template_key)
            fixture_summary = self._fixture_summary(latest_audit)
            runtime_usage_count = usage_by_template.get(template_key, 0)
            runtime_rejection_count = rejection_by_template.get(template_key, 0)
            status = str(template.status)
            counts_by_status[status] = counts_by_status.get(status, 0) + 1
            if fixture_summary["failed_fixture_count"] > 0:
                failed_fixtures += 1
            if runtime_rejection_count > 0:
                runtime_rejections += 1
            rows.append(
                {
                    "template_key": template_key,
                    "exercise_type": str(template.exercise_type),
                    "objective": str(template.objective),
                    "difficulty": str(template.difficulty),
                    "status": status,
                    "runtime_usage_count_7d": runtime_usage_count,
                    "runtime_rejection_count_7d": runtime_rejection_count,
                    "latest_fixture_status": fixture_summary["status"],
                    "latest_failed_fixture_count": fixture_summary["failed_fixture_count"],
                    "latest_audit_at": self._timestamp(getattr(latest_audit, "created_at", None)),
                    "latest_change_note": str(getattr(latest_audit, "change_note", "") or "") or None,
                }
            )

        rows.sort(
            key=lambda item: (
                self._attention_rank(item),
                -int(item["runtime_rejection_count_7d"]),
                -int(item["runtime_usage_count_7d"]),
                item["template_key"],
            )
        )
        attention = [
            row
            for row in rows
            if row["latest_failed_fixture_count"] > 0 or row["runtime_rejection_count_7d"] > 0
        ]
        return {
            "summary": {
                "total_templates": len(rows),
                "counts_by_status": dict(sorted(counts_by_status.items())),
                "templates_with_failed_fixtures": failed_fixtures,
                "templates_with_runtime_rejections": runtime_rejections,
                "recent_audit_count_7d": recent_audit_count,
                "latest_audit_at": self._timestamp(latest_audit_at),
            },
            "attention": attention[:normalized_limit],
            "templates": rows[:normalized_limit],
        }

    def _validate_command(self, template_key: str, command: ExerciseTemplateRegistryUpsert) -> None:
        if command.status not in _VALID_STATUSES:
            raise ValidationError(f"Exercise template '{template_key}' has invalid status '{command.status}'")
        if command.exercise_type not in _VALID_EXERCISE_TYPES:
            raise ValidationError(f"Exercise template '{template_key}' has invalid exercise_type '{command.exercise_type}'")
        if command.objective not in _VALID_OBJECTIVES:
            raise ValidationError(f"Exercise template '{template_key}' has invalid objective '{command.objective}'")
        if command.difficulty not in _VALID_DIFFICULTIES:
            raise ValidationError(f"Exercise template '{template_key}' has invalid difficulty '{command.difficulty}'")
        if command.answer_source not in _VALID_ANSWER_SOURCES:
            raise ValidationError(f"Exercise template '{template_key}' has invalid answer_source '{command.answer_source}'")
        if len((command.change_note or "").strip()) < 8:
            raise ValidationError("Change note must be at least 8 characters")
        if "{target}" not in command.prompt_template and "{vocab_word}" not in command.prompt_template:
            raise ValidationError("Prompt template must include {target} or {vocab_word}")
        if command.exercise_type == "multiple_choice":
            if command.choice_count is None or command.choice_count < 3 or command.choice_count > 6:
                raise ValidationError("Multiple-choice templates must declare choice_count between 3 and 6")
        elif command.choice_count is not None:
            raise ValidationError("Non multiple-choice templates cannot declare choice_count")

    def _validate_template_key(self, template_key: str) -> str:
        normalized_key = (template_key or "").strip()
        if not _TEMPLATE_KEY_PATTERN.match(normalized_key):
            raise ValidationError("Exercise template key must match ^[a-z0-9_]{3,80}$")
        return normalized_key

    def _validate_transition(self, current_status: str | None, next_status: str) -> None:
        if current_status is None:
            return
        allowed = {
            "draft": {"draft", "active", "archived"},
            "active": {"active", "archived"},
            "archived": {"archived"},
        }
        if next_status not in allowed.get(current_status, {current_status}):
            raise ValidationError(f"Exercise template status cannot move from '{current_status}' to '{next_status}'")

    def _validate_promotion(self, command: ExerciseTemplateRegistryUpsert, fixture_report: dict[str, Any]) -> None:
        if command.status != "active":
            return
        if any(item["status"] == "rejected" for item in fixture_report.get("fixtures", [])):
            raise ValidationError("Active templates must pass all promotion fixtures")

    def _fixture_report(self, template_key: str, command: ExerciseTemplateRegistryUpsert) -> dict[str, Any]:
        fixtures = PROMOTION_FIXTURES.get((command.exercise_type, command.objective), [])
        results = [
            self._content_quality_gate.lint_template_fixture(
                template_key=template_key,
                exercise_type=command.exercise_type,
                objective=command.objective,
                difficulty=command.difficulty,
                prompt_template=command.prompt_template.strip(),
                answer_source=command.answer_source,
                choice_count=command.choice_count,
                fixture=fixture,
            )
            for fixture in fixtures
        ]
        return {
            "fixture_count": len(results),
            "fixtures": results,
        }

    def _template_config(self, template) -> dict[str, Any]:
        if template is None:
            return {}
        metadata = dict(getattr(template, "template_metadata", {}) or {})
        description = metadata.pop("description", None)
        return {
            "template_key": str(template.template_key),
            "exercise_type": str(template.exercise_type),
            "objective": str(template.objective),
            "difficulty": str(template.difficulty),
            "status": str(template.status),
            "prompt_template": str(template.prompt_template),
            "answer_source": str(template.answer_source),
            "choice_count": int(template.choice_count) if template.choice_count is not None else None,
            "description": description,
            "metadata": metadata,
            "created_at": self._timestamp(getattr(template, "created_at", None)),
            "updated_at": self._timestamp(getattr(template, "updated_at", None)),
        }

    def _summary_payload(self, template, *, latest_audit) -> dict[str, Any]:
        payload = self._template_config(template)
        payload["latest_change"] = self._audit_payload(latest_audit) if latest_audit else None
        return payload

    def _detail_payload(self, template, audits: list) -> dict[str, Any]:
        payload = self._template_config(template)
        payload["audit_entries"] = [self._audit_payload(item) for item in audits]
        return payload

    def _audit_payload(self, audit) -> dict[str, Any]:
        return {
            "id": int(audit.id),
            "template_key": str(audit.template_key),
            "action": str(audit.action),
            "changed_by": str(audit.changed_by),
            "change_note": str(audit.change_note),
            "previous_config": dict(audit.previous_config or {}),
            "new_config": dict(audit.new_config or {}),
            "fixture_report": dict(audit.fixture_report or {}),
            "created_at": self._timestamp(getattr(audit, "created_at", None)),
        }

    def _fixture_summary(self, audit) -> dict[str, Any]:
        if audit is None:
            return {"status": "unknown", "failed_fixture_count": 0}
        report = dict(getattr(audit, "fixture_report", {}) or {})
        fixtures = [dict(item or {}) for item in list(report.get("fixtures") or [])]
        failed_fixture_count = sum(1 for item in fixtures if str(item.get("status") or "") == "rejected")
        if not fixtures:
            status = "unknown"
        elif failed_fixture_count > 0:
            status = "rejected"
        else:
            status = "passed"
        return {"status": status, "failed_fixture_count": failed_fixture_count}

    def _attention_rank(self, row: dict[str, Any]) -> int:
        if int(row.get("latest_failed_fixture_count", 0) or 0) > 0:
            return 0
        if int(row.get("runtime_rejection_count_7d", 0) or 0) > 0:
            return 1
        return 2

    def _max_timestamp(self, current, candidate):
        if current is None:
            return candidate
        if candidate is None:
            return current
        return candidate if candidate > current else current

    def _audit_action(self, existing, command: ExerciseTemplateRegistryUpsert) -> str:
        if existing is None:
            return "created"
        if getattr(existing, "status", None) != command.status:
            return "status_changed"
        return "updated"

    def _normalize_actor(self, changed_by: str | None) -> str:
        actor = (changed_by or "").strip()
        return actor or "system_admin"

    def _timestamp(self, value) -> str | None:
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
