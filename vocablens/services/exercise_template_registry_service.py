from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vocablens.infrastructure.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class ExerciseTemplateBlueprint:
    template_key: str
    exercise_type: str
    objective: str
    difficulty: str
    prompt_template: str
    answer_source: str
    choice_count: int | None
    metadata: dict[str, Any]


class ExerciseTemplateRegistryService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def get_lesson_blueprint(self, recommendation, vocab: list[str]) -> list[ExerciseTemplateBlueprint]:
        objectives = self._objectives_for(recommendation)
        difficulty = str(getattr(recommendation, "lesson_difficulty", "medium") or "medium")
        async with self._uow_factory() as uow:
            candidates = await uow.exercise_templates.list_active(
                objectives=objectives,
                difficulty=difficulty,
                limit=20,
            )
            if not candidates:
                candidates = await uow.exercise_templates.list_active(
                    objectives=objectives,
                    difficulty=None,
                    limit=20,
                )
            await uow.commit()

        selected: list[ExerciseTemplateBlueprint] = []
        by_objective: dict[str, list[Any]] = {}
        for candidate in candidates:
            by_objective.setdefault(str(candidate.objective), []).append(candidate)
        for objective in objectives:
            rows = by_objective.get(objective, [])
            if not rows:
                continue
            row = rows[0]
            selected.append(
                ExerciseTemplateBlueprint(
                    template_key=str(row.template_key),
                    exercise_type=str(row.exercise_type),
                    objective=str(row.objective),
                    difficulty=str(row.difficulty),
                    prompt_template=str(row.prompt_template),
                    answer_source=str(row.answer_source),
                    choice_count=int(row.choice_count) if row.choice_count is not None else None,
                    metadata=dict(getattr(row, "template_metadata", {}) or {}),
                )
            )
        if selected:
            return selected
        return self._fallback_blueprint(recommendation, vocab)

    def render_exercises(
        self,
        *,
        blueprint: list[ExerciseTemplateBlueprint],
        recommendation,
        vocab: list[str],
    ) -> list[dict[str, Any]]:
        exercises: list[dict[str, Any]] = []
        target = str(getattr(recommendation, "target", None) or "").strip()
        vocab_words = [word for word in vocab if word]
        answer_default = target or (vocab_words[0] if vocab_words else "target")
        distractor_pool = [word for word in vocab_words if str(word).strip().lower() != answer_default.lower()]
        for item in blueprint:
            answer = self._answer_value(item, target=target, vocab=vocab_words, answer_default=answer_default)
            question = item.prompt_template.format(
                target=target or answer,
                answer=answer,
                vocab_word=answer,
            )
            exercise = {
                "template_key": item.template_key,
                "type": item.exercise_type,
                "objective": item.objective,
                "difficulty": item.difficulty,
                "question": question,
                "answer": answer,
            }
            if item.exercise_type == "multiple_choice":
                exercise["choices"] = self._choices(
                    answer=answer,
                    distractor_pool=distractor_pool,
                    choice_count=item.choice_count or 4,
                )
            exercises.append(exercise)
        return exercises

    def merge_generated_exercises(
        self,
        *,
        blueprint: list[ExerciseTemplateBlueprint],
        fallback_exercises: list[dict[str, Any]],
        generated_exercises: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        generated_by_key = {
            str(item.get("template_key") or ""): dict(item)
            for item in generated_exercises
            if str(item.get("template_key") or "")
        }
        merged: list[dict[str, Any]] = []
        for template, fallback in zip(blueprint, fallback_exercises, strict=False):
            generated = generated_by_key.get(template.template_key)
            if generated is None:
                merged.append(dict(fallback))
                continue
            merged.append(
                {
                    **dict(fallback),
                    **generated,
                    "template_key": template.template_key,
                    "type": template.exercise_type,
                    "objective": template.objective,
                    "difficulty": template.difficulty,
                }
            )
        return merged or list(fallback_exercises)

    def _objectives_for(self, recommendation) -> list[str]:
        action = str(getattr(recommendation, "action", "") or "")
        if action == "review_word":
            return ["recall", "reinforcement"]
        if action == "learn_new_word":
            return ["discrimination", "recall"]
        if action == "practice_grammar":
            return ["correction", "reinforcement"]
        if action == "conversation_drill":
            return ["production", "discrimination"]
        return ["recall", "reinforcement"]

    def _answer_value(
        self,
        template: ExerciseTemplateBlueprint,
        *,
        target: str,
        vocab: list[str],
        answer_default: str,
    ) -> str:
        if template.answer_source == "target" and target:
            return target
        if template.answer_source == "vocab_first" and vocab:
            return str(vocab[0])
        if template.answer_source == "vocab_last" and vocab:
            return str(vocab[-1])
        return answer_default

    def _choices(self, *, answer: str, distractor_pool: list[str], choice_count: int) -> list[str]:
        normalized_answer = answer.strip()
        choices = [normalized_answer]
        for candidate in distractor_pool:
            stripped = str(candidate).strip()
            if not stripped or stripped.lower() == normalized_answer.lower():
                continue
            if stripped.lower() in {item.lower() for item in choices}:
                continue
            choices.append(stripped)
            if len(choices) >= choice_count:
                break
        while len(choices) < choice_count:
            choices.append(f"{normalized_answer} option {len(choices)}")
        return choices

    def _fallback_blueprint(self, recommendation, vocab: list[str]) -> list[ExerciseTemplateBlueprint]:
        objectives = self._objectives_for(recommendation)
        difficulty = str(getattr(recommendation, "lesson_difficulty", "medium") or "medium")
        fallback_rows = [
            ExerciseTemplateBlueprint(
                template_key=f"default_{objective}",
                exercise_type="multiple_choice" if objective == "discrimination" else "fill_blank",
                objective=objective,
                difficulty=difficulty,
                prompt_template="Choose the best match for {target}." if objective == "discrimination" else "Use {target} in the blank: {target}.",
                answer_source="target" if getattr(recommendation, "target", None) else "vocab_first",
                choice_count=4 if objective == "discrimination" else None,
                metadata={},
            )
            for objective in objectives
        ]
        return fallback_rows[: max(2, min(len(fallback_rows), 3))]
