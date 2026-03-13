from vocablens.providers.llm.base import LLMProvider
from vocablens.prompts import load_prompt


class MistakeEngine:
    """
    Analyzes learner messages for mistakes using LLM.
    """

    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.template = load_prompt("mistake_analysis_prompt")

    def analyze(self, message: str, language: str):
        prompt = self.template.format(
            message=message,
            language=language,
        )

        return self.llm.generate_json(prompt)
