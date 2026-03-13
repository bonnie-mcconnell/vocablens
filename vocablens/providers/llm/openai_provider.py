import json
import os

from openai import OpenAI

from vocablens.providers.llm.base import LLMProvider
from vocablens.providers.llm.llm_guardrails import LLMGuardrails


class OpenAIProvider(LLMProvider):

    def __init__(self):

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        self._client = OpenAI(api_key=api_key)
        self._guardrails = LLMGuardrails(self._client)

    def generate(self, prompt: str) -> str:

        return self._guardrails.generate_text(
            prompt=prompt,
            version="v1",
        )

    def generate_json(self, prompt: str) -> dict:

        return self._guardrails.generate_json(
            prompt=prompt,
            version="v1",
            schema=None,
        )
