from vocablens.providers.llm.base import LLMJsonResult, LLMUsage
from vocablens.services.explanation_service import ExplainMyThinkingService
from tests.conftest import run_async


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def generate_json_with_usage(self, prompt: str):
        self.calls += 1
        return LLMJsonResult(
            content={
                "grammar_mistake": "You used the wrong tense.",
                "natural_phrasing": "I went to school yesterday.",
                "native_level_explanation": "Native speakers pick the tense that matches the time marker automatically.",
            },
            usage=LLMUsage(total_tokens=15),
        )


def test_explain_my_thinking_returns_human_tutor_style_explanation():
    llm = FakeLLM()
    service = ExplainMyThinkingService(llm)

    result = run_async(
        service.explain(
            "I go to school yesterday",
            {
                "grammar_mistakes": ["present tense used with a past-time expression"],
                "vocab_misuse": [],
                "correction_feedback": ["Say 'I went to school yesterday.'"],
                "suggestions": [],
            },
        )
    )

    assert result["grammar_mistake"] == "You used the wrong tense."
    assert result["natural_phrasing"] == "I went to school yesterday."
    assert "Native speakers" in result["native_level_explanation"]
    assert llm.calls == 1


def test_explain_my_thinking_basic_quality_uses_fallback_without_llm():
    llm = FakeLLM()
    service = ExplainMyThinkingService(llm)

    result = run_async(
        service.explain(
            "I go to school yesterday",
            {
                "grammar_mistakes": ["present tense used with a past-time expression"],
                "vocab_misuse": [],
                "correction_feedback": ["Say 'I went to school yesterday.'"],
                "suggestions": [],
            },
            quality="basic",
        )
    )

    assert result["grammar_mistake"] == "present tense used with a past-time expression"
    assert result["natural_phrasing"] == "Say 'I went to school yesterday.'"
    assert llm.calls == 0
