from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

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
    def __init__(self, uow_factory: type[UnitOfWork], content_quality_gate: ContentQualityGateService):
        self._uow_factory = uow_factory
        self._content_quality_gate = content_quality_gate

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
