from vocablens.providers.llm.base import LLMProvider


class ExampleSentenceService:

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    def generate_example(
        self,
        word: str,
        source_lang: str,
        target_lang: str,
    ) -> dict:

        prompt = f"""
Create a simple example sentence using the word "{word}".

Return JSON only.

{{
 "source_sentence": "...",
 "translated_sentence": "..."
}}

Source language: {source_lang}
Target language: {target_lang}
"""

        return self._llm.generate_json(prompt)