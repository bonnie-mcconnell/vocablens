from vocablens.providers.llm.base import LLMProvider


class SemanticClusterService:

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    def cluster_word(
        self,
        word: str,
        source_lang: str,
    ) -> str:

        prompt = f"""
Assign this word to a semantic topic cluster.

Word: {word}
Language: {source_lang}

Return ONE word only.

Examples:
food
travel
emotion
verb
adjective
shopping
"""

        return self._llm.generate(prompt).strip().lower()