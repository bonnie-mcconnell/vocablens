import json
import os

from openai import OpenAI

from vocablens.providers.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):

    def __init__(self):

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        self._client = OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> str:

        response = self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        content = response.choices[0].message.content

        if not content:
            return ""

        return content.strip()

    def generate_json(self, prompt: str) -> dict:

        response = self.generate(prompt)

        try:
            return json.loads(response)
        except Exception:
            return {}