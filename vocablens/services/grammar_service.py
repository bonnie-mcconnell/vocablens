from vocablens.providers.llm.base import LLMProvider


class GrammarExplanationService:

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    def explain(
        self,
        sentence: str,
        source_lang: str,
        target_lang: str,
    ) -> str:

        prompt = f"""
Explain the grammar in this sentence for a language learner.

Sentence:
{sentence}

Source language: {source_lang}
Learner language: {target_lang}

Keep explanation short and beginner friendly.
"""

        return self._llm.generate_with_usage(prompt).content
