import json

from vocablens.prompts import load_prompt
from vocablens.providers.llm.base import LLMProvider


class ExplainMyThinkingService:
    """
    Explains the learner's wording like a human tutor.
    """

    def __init__(self, llm: LLMProvider):
        self._llm = llm
        self._template = load_prompt("explain_thinking_prompt")

    async def explain(self, message: str, analysis: dict, quality: str = "premium") -> dict | None:
        if not self._has_signal(analysis):
            return None
        if quality == "basic":
            return self._normalize({}, analysis)

        prompt = self._template.format(
            message=message,
            mistakes=json.dumps(
                {
                    "grammar_mistakes": analysis.get("grammar_mistakes", []),
                    "vocab_misuse": analysis.get("vocab_misuse", []),
                    "repeated_errors": analysis.get("repeated_errors", []),
                    "suggestions": analysis.get("suggestions", []),
                    "correction_feedback": analysis.get("correction_feedback", []),
                }
            ),
        )
        result = await self._llm.generate_json_with_usage(prompt)
        normalized = self._normalize(result.content, analysis)
        if quality == "standard":
            normalized["native_level_explanation"] = normalized["native_level_explanation"][:180]
        return normalized

    def _has_signal(self, analysis: dict) -> bool:
        return bool(
            analysis.get("grammar_mistakes")
            or analysis.get("vocab_misuse")
            or analysis.get("correction_feedback")
        )

    def _normalize(self, payload: dict | None, analysis: dict) -> dict:
        payload = payload or {}
        grammar = str(payload.get("grammar_mistake") or "").strip()
        natural = str(payload.get("natural_phrasing") or "").strip()
        native = str(payload.get("native_level_explanation") or "").strip()

        if not grammar:
            grammar = self._fallback_grammar(analysis)
        if not natural:
            natural = self._fallback_natural(analysis)
        if not native:
            native = self._fallback_native(grammar, natural)

        return {
            "grammar_mistake": grammar,
            "natural_phrasing": natural,
            "native_level_explanation": native,
        }

    def _fallback_grammar(self, analysis: dict) -> str:
        grammar = analysis.get("grammar_mistakes", [])
        vocab = analysis.get("vocab_misuse", [])
        if grammar:
            return str(grammar[0])
        if vocab:
            return f"Vocabulary choice issue: {vocab[0]}"
        return "The sentence is understandable, but the structure is a little unnatural."

    def _fallback_natural(self, analysis: dict) -> str:
        feedback = analysis.get("correction_feedback", [])
        suggestions = analysis.get("suggestions", [])
        if feedback:
            return str(feedback[0])
        if suggestions:
            return str(suggestions[0])
        return "Try a shorter, more natural version that native speakers would say automatically."

    def _fallback_native(self, grammar: str, natural: str) -> str:
        return (
            f"Native speakers usually choose the phrasing that sounds more automatic and less literal. "
            f"Here, the issue is: {grammar}. A more natural version is: {natural}."
        )
