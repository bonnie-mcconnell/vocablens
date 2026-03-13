from vocablens.providers.llm.base import LLMProvider
from vocablens.prompts import load_prompt


class DrillGenerationService:

    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.template = load_prompt("drill_generation_prompt")

    def generate_drills(self, mistakes):

        prompt = self.template.format(mistakes=mistakes)

        return self.llm.generate_json(prompt)
