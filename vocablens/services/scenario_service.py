from vocablens.providers.llm.base import LLMProvider


class ScenarioService:
    """
    Generates real-life immersion conversations.
    """

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def start_scenario(
        self,
        scenario: str,
        language: str,
    ):

        prompt = f"""
You are role-playing a real-life conversation.

Scenario:
{scenario}

Language:
{language}

Start the conversation naturally with the learner.
"""

        return self.llm.generate_with_usage(prompt).content
