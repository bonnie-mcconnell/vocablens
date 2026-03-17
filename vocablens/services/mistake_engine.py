from vocablens.providers.llm.base import LLMProvider
from vocablens.prompts import load_prompt
from vocablens.infrastructure.unit_of_work import UnitOfWork


class MistakeEngine:
    """
    Analyzes learner messages for mistakes using LLM and records patterns.
    """

    def __init__(self, llm: LLMProvider, uow_factory: type[UnitOfWork] | None = None):
        self.llm = llm
        self.template = load_prompt("mistake_analysis_prompt")
        self._uow_factory = uow_factory

    async def analyze(self, user_id: int, message: str, language: str):
        prompt = self.template.format(
            message=message,
            language=language,
        )

        analysis_result = self.llm.generate_json_with_usage(prompt)
        analysis = self._normalize_analysis(analysis_result.content)

        # store patterns if possible
        if self._uow_factory:
            async with self._uow_factory() as uow:
                for m in analysis["grammar_mistakes"]:
                    await uow.mistake_patterns.record(user_id, "grammar", str(m))
                for m in analysis["vocab_misuse"]:
                    await uow.mistake_patterns.record(user_id, "vocabulary", str(m))
                for m in analysis["repeated_errors"]:
                    await uow.mistake_patterns.record(user_id, "repetition", str(m))
                repeated = await uow.mistake_patterns.repeated_patterns(user_id, threshold=2, limit=5)
                analysis["repeated_errors"] = [
                    {
                        "pattern": item.pattern,
                        "count": item.count,
                        "category": item.category,
                    }
                    for item in repeated
                ]
                if not analysis["correction_feedback"]:
                    analysis["correction_feedback"] = self._default_feedback(analysis)
                await uow.commit()

        return analysis

    def _normalize_analysis(self, raw: dict | None) -> dict:
        raw = raw or {}
        grammar = self._ensure_list(raw.get("grammar_mistakes"))
        vocab = self._ensure_list(raw.get("vocab_misuse"))
        repeated = self._ensure_list(raw.get("repeated_errors"))
        suggestions = self._ensure_list(raw.get("suggestions"))
        correction_feedback = self._ensure_list(raw.get("correction_feedback"))
        if not correction_feedback:
            correction_feedback = self._feedback_from_suggestions(grammar, vocab, suggestions)
        return {
            "grammar_mistakes": grammar,
            "vocab_misuse": vocab,
            "repeated_errors": repeated,
            "suggestions": suggestions,
            "correction_feedback": correction_feedback,
        }

    def _ensure_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _feedback_from_suggestions(self, grammar, vocab, suggestions):
        feedback = []
        for item in grammar[:2]:
            feedback.append(f"Grammar correction: {item}")
        for item in vocab[:2]:
            feedback.append(f"Vocabulary correction: {item}")
        for item in suggestions[:2]:
            feedback.append(str(item))
        return feedback

    def _default_feedback(self, analysis: dict):
        feedback = self._feedback_from_suggestions(
            analysis.get("grammar_mistakes", []),
            analysis.get("vocab_misuse", []),
            analysis.get("suggestions", []),
        )
        return feedback[:3]
