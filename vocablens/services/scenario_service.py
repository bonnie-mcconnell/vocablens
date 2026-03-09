from vocablens.providers.llm.base import LLMProvider


class ScenarioService:

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def start_scenario(
        self,
        scenario: str,
        target_lang: str,
    ):

        prompt = f"""
Create a conversation scenario.

Scenario: {scenario}

Language: {target_lang}

You are the other speaker.

Start the conversation naturally.
"""

        return self.llm.generate(prompt)