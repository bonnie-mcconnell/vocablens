import json
import os

from openai import AsyncOpenAI

from vocablens.providers.llm.base import LLMJsonResult, LLMProvider, LLMTextResult
from vocablens.providers.llm.llm_guardrails import LLMGuardrails


class OpenAIProvider(LLMProvider):

    def __init__(self):

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        self._client = AsyncOpenAI(api_key=api_key)
        self._guardrails = LLMGuardrails(self._client)

    def generate(self, prompt: str) -> str:
        return self.generate_with_usage(prompt).content

    def generate_with_usage(self, prompt: str) -> LLMTextResult:
        return self._guardrails.generate_text_result(
            prompt=prompt,
            version="v1",
        )

    def generate_json(self, prompt: str) -> dict:
        return self.generate_json_with_usage(prompt).content

    def generate_json_with_usage(self, prompt: str) -> LLMJsonResult:
        return self._guardrails.generate_json_result(
            prompt=prompt,
            version="v1",
            schema=None,
        )
