from vocablens.providers.llm.base import LLMProvider


class DrillGenerationService:

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def generate_drills(self, mistakes):

        prompt = f"""
Create exercises to fix these mistakes.

Mistakes:
{mistakes}

Return JSON exercises.
"""

        return self.llm.generate_json(prompt)