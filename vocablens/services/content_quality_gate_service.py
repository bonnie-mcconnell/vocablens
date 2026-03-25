from __future__ import annotations

from typing import Any

from vocablens.domain.errors import ConflictError
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.content_quality_health_signal_service import ContentQualityHealthSignalService


class ContentQualityGateService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        health_signal_service: ContentQualityHealthSignalService | None = None,
    ):
        self._uow_factory = uow_factory
        self._health_signals = health_signal_service

    async def validate_structured_session(
        self,
        *,
        user_id: int,
        reference_id: str,
        session,
        source: str = "session_engine",
    ) -> dict[str, Any]:
        violations = self._lint_structured_session(session)
        rejected = any(str(item.get("severity") or "") == "critical" for item in violations)
        score = self._score(violations)
        artifact_summary = self._summary(session)
        async with self._uow_factory() as uow:
            await uow.content_quality_checks.create(
                user_id=user_id,
                source=source,
                artifact_type="structured_session",
                reference_id=reference_id,
                status="rejected" if rejected else "passed",
                score=score,
                violations=violations,
                artifact_summary=artifact_summary,
            )
            await uow.commit()
        if self._health_signals is not None:
            await self._health_signals.evaluate_scope("global")
        return {
            "status": "rejected" if rejected else "passed",
            "score": score,
            "violations": violations,
            "artifact_summary": artifact_summary,
        }

    async def validate_generated_lesson(
        self,
        *,
        user_id: int,
        reference_id: str,
        lesson: dict[str, Any],
        source: str = "lesson_generation_service",
    ) -> dict[str, Any]:
        normalized_lesson = dict(lesson or {})
        violations = self._lint_generated_lesson(normalized_lesson)
        rejected = any(str(item.get("severity") or "") == "critical" for item in violations)
        score = self._score(violations)
        artifact_summary = self._lesson_summary(normalized_lesson)
        async with self._uow_factory() as uow:
            await uow.content_quality_checks.create(
                user_id=user_id,
                source=source,
                artifact_type="generated_lesson",
                reference_id=reference_id,
                status="rejected" if rejected else "passed",
                score=score,
                violations=violations,
                artifact_summary=artifact_summary,
            )
            await uow.commit()
        if self._health_signals is not None:
            await self._health_signals.evaluate_scope("global")
        return {
            "status": "rejected" if rejected else "passed",
            "score": score,
            "violations": violations,
            "artifact_summary": artifact_summary,
        }

    def ensure_passed(self, report: dict[str, Any]) -> None:
        if str(report.get("status") or "") != "rejected":
            return
        raise ConflictError("Content failed quality validation")

    def _lint_structured_session(self, session) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        phases = list(getattr(session, "phases", []) or [])
        expected_order = [
            "warmup",
            "core_challenge",
            "correction_engine",
            "reinforcement",
            "win_moment",
        ]
        actual_order = [str(getattr(phase, "name", "") or "") for phase in phases]
        if actual_order != expected_order:
            violations.append(
                self._violation(
                    "phase_order_invalid",
                    "critical",
                    "Structured session phases are missing or out of order.",
                )
            )
        duration_seconds = int(getattr(session, "duration_seconds", 0) or 0)
        if duration_seconds < 120 or duration_seconds > 300:
            violations.append(
                self._violation(
                    "duration_invalid",
                    "critical",
                    "Structured session duration is outside the allowed round length.",
                )
            )
        max_response_words = int(getattr(session, "max_response_words", 0) or 0)
        if max_response_words < 1 or max_response_words > 24:
            violations.append(
                self._violation(
                    "answer_contract_invalid",
                    "critical",
                    "Structured session answer contract is outside the supported range.",
                )
            )

        for phase in phases:
            name = str(getattr(phase, "name", "") or "")
            payload = dict(getattr(phase, "payload", {}) or {})
            title = str(getattr(phase, "title", "") or "").strip()
            directive = str(getattr(phase, "directive", "") or "").strip()
            if not title or not directive:
                violations.append(
                    self._violation(
                        "phase_copy_missing",
                        "warning",
                        f"Phase '{name}' is missing operator-facing copy.",
                    )
                )
            if name in {"warmup", "core_challenge"}:
                violations.extend(self._lint_prompt_phase(name, payload))
            if name == "reinforcement":
                if not str(payload.get("corrected_answer") or "").strip():
                    violations.append(
                        self._violation(
                            "answer_contract_invalid",
                            "critical",
                            "Reinforcement phase is missing the corrected answer contract.",
                        )
                    )
            if name == "correction_engine":
                if not list(payload.get("accepted_keywords") or []):
                    violations.append(
                        self._violation(
                            "answer_contract_invalid",
                            "critical",
                            "Correction phase is missing accepted keyword guidance.",
                        )
                    )
        return violations

    def _lint_generated_lesson(self, lesson: dict[str, Any]) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        exercises = list(lesson.get("exercises") or [])
        if not exercises:
            violations.append(
                self._violation(
                    "exercise_set_empty",
                    "critical",
                    "Generated lesson is missing exercises.",
                )
            )
            return violations

        for index, exercise in enumerate(exercises):
            item = dict(exercise or {})
            template_key = str(item.get("template_key") or "").strip()
            exercise_type = str(item.get("type") or "").strip()
            objective = str(item.get("objective") or "").strip()
            difficulty = str(item.get("difficulty") or "").strip()
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            label = f"exercise_{index + 1}"
            if not template_key:
                violations.append(
                    self._violation(
                        "template_contract_invalid",
                        "critical",
                        f"{label} is missing a template key.",
                    )
                )
            if exercise_type not in {"fill_blank", "multiple_choice"}:
                violations.append(
                    self._violation(
                        "exercise_type_invalid",
                        "critical",
                        f"{label} uses an unsupported exercise type.",
                    )
                )
            if not objective or not difficulty:
                violations.append(
                    self._violation(
                        "template_contract_invalid",
                        "critical",
                        f"{label} is missing objective or difficulty metadata.",
                    )
                )
            if len(question) < 12:
                violations.append(
                    self._violation(
                        "ambiguous_prompt",
                        "warning",
                        f"{label} question is too short to be reliably interpreted.",
                    )
                )
            if not answer:
                violations.append(
                    self._violation(
                        "answer_contract_invalid",
                        "critical",
                        f"{label} is missing an answer contract.",
                    )
                )
            if answer and question.lower() == answer.lower():
                violations.append(
                    self._violation(
                        "ambiguous_prompt",
                        "warning",
                        f"{label} question mirrors the answer too closely.",
                    )
                )
            if exercise_type == "multiple_choice":
                choices = [str(choice).strip() for choice in list(item.get("choices") or []) if str(choice).strip()]
                if len(choices) < 3:
                    violations.append(
                        self._violation(
                            "answer_contract_invalid",
                            "critical",
                            f"{label} multiple-choice exercise has too few answer choices.",
                        )
                    )
                elif len({choice.lower() for choice in choices}) != len(choices):
                    violations.append(
                        self._violation(
                            "weak_distractors",
                            "warning",
                            f"{label} multiple-choice exercise contains duplicate choices.",
                        )
                    )
                if answer and answer not in choices:
                    violations.append(
                        self._violation(
                            "answer_contract_invalid",
                            "critical",
                            f"{label} multiple-choice answer is missing from the choices.",
                        )
                    )
                wrong_choices = [choice for choice in choices if answer and choice != answer]
                if wrong_choices and len(set(choice.lower() for choice in wrong_choices)) < 2:
                    violations.append(
                        self._violation(
                            "weak_distractors",
                            "warning",
                            f"{label} multiple-choice distractors are too weak.",
                        )
                    )

        next_action = dict(lesson.get("next_action") or {})
        if next_action:
            target = str(next_action.get("target") or "").strip().lower()
            if target in {"", "general", "mixed", "unknown", "vocabulary"}:
                violations.append(
                    self._violation(
                        "target_contract_invalid",
                        "critical",
                        "Generated lesson next action target is missing or too generic.",
                    )
                )
        return violations

    def _lint_prompt_phase(self, phase_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        prompt = str(payload.get("prompt") or "").strip()
        expected_answer = str(payload.get("expected_answer") or "").strip()
        target = str(payload.get("target") or "").strip()
        accepted_keywords = [
            str(item).strip()
            for item in list(payload.get("accepted_keywords") or [])
            if str(item).strip()
        ]
        mode = str(payload.get("mode") or "").strip()
        generic_targets = {"", "general", "mixed", "unknown", "vocabulary"}

        if len(prompt) < 12:
            violations.append(
                self._violation(
                    "ambiguous_prompt",
                    "warning",
                    f"{phase_name} prompt is too short to be reliably interpreted.",
                )
            )
        if not expected_answer:
            violations.append(
                self._violation(
                    "answer_contract_invalid",
                    "critical",
                    f"{phase_name} prompt is missing an expected answer.",
                )
            )
        if not accepted_keywords:
            violations.append(
                self._violation(
                    "answer_contract_invalid",
                    "critical",
                    f"{phase_name} prompt is missing accepted keywords.",
                )
            )
        elif len({item.lower() for item in accepted_keywords}) != len(accepted_keywords):
            violations.append(
                self._violation(
                    "answer_contract_invalid",
                    "warning",
                    f"{phase_name} accepted keywords contain duplicates.",
                )
            )
        if mode in {"review", "drill", "sentence", "rewrite"} and target.lower() in generic_targets:
            violations.append(
                self._violation(
                    "target_contract_invalid",
                    "critical",
                    f"{phase_name} prompt target is missing or too generic.",
                )
            )
        if prompt.lower() == expected_answer.lower():
            violations.append(
                self._violation(
                    "ambiguous_prompt",
                    "warning",
                    f"{phase_name} prompt mirrors the expected answer too closely.",
                )
            )

        choices = [str(item).strip() for item in list(payload.get("choices") or []) if str(item).strip()]
        if mode == "multiple_choice":
            if len(choices) < 3 or len({item.lower() for item in choices}) != len(choices):
                violations.append(
                    self._violation(
                        "weak_distractors",
                        "warning",
                        f"{phase_name} multiple-choice distractors are too weak or duplicated.",
                    )
                )
            if expected_answer and expected_answer not in choices:
                violations.append(
                    self._violation(
                        "answer_contract_invalid",
                        "critical",
                        f"{phase_name} expected answer is missing from the answer choices.",
                    )
                )
        return violations

    def _summary(self, session) -> dict[str, Any]:
        phases = list(getattr(session, "phases", []) or [])
        return {
            "mode": str(getattr(session, "mode", "") or ""),
            "duration_seconds": int(getattr(session, "duration_seconds", 0) or 0),
            "weak_area": str(getattr(session, "weak_area", "") or ""),
            "lesson_target": getattr(session, "lesson_target", None),
            "max_response_words": int(getattr(session, "max_response_words", 0) or 0),
            "phase_names": [str(getattr(phase, "name", "") or "") for phase in phases],
        }

    def _lesson_summary(self, lesson: dict[str, Any]) -> dict[str, Any]:
        exercises = [dict(item or {}) for item in list(lesson.get("exercises") or [])]
        return {
            "exercise_count": len(exercises),
            "exercise_types": [str(item.get("type") or "") for item in exercises],
            "has_next_action": bool(lesson.get("next_action")),
            "target": dict(lesson.get("next_action") or {}).get("target"),
        }

    def _score(self, violations: list[dict[str, Any]]) -> float:
        score = 1.0
        for violation in violations:
            severity = str(violation.get("severity") or "warning")
            score -= 0.35 if severity == "critical" else 0.1
        return round(max(0.0, score), 3)

    def _violation(self, code: str, severity: str, message: str) -> dict[str, Any]:
        return {"code": code, "severity": severity, "message": message}
