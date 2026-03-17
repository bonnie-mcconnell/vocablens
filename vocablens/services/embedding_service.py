import numpy as np
from openai import OpenAI
import json

from vocablens.infrastructure.postgres_embedding_repository import PostgresEmbeddingRepository
from vocablens.infrastructure.observability.metrics import LLM_COST, LLM_TOKENS
from vocablens.infrastructure.observability.token_tracker import add_tokens


class EmbeddingService:

    def __init__(self, repo: PostgresEmbeddingRepository):
        self.client = OpenAI()
        self.repo = repo

    def embed(self, text: str):

        result = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        usage = getattr(result, "usage", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or prompt_tokens
            add_tokens(total_tokens)
            LLM_TOKENS.labels(provider="openai", model="text-embedding-3-small", type="prompt").inc(prompt_tokens)
            LLM_TOKENS.labels(provider="openai", model="text-embedding-3-small", type="completion").inc(0)
            LLM_TOKENS.labels(provider="openai", model="text-embedding-3-small", type="total").inc(total_tokens)
            LLM_COST.labels(provider="openai", model="text-embedding-3-small").inc(total_tokens * 0.00000002)

        return np.array(result.data[0].embedding)

    def similarity(self, a, b):

        return np.dot(a, b) / (
            np.linalg.norm(a) * np.linalg.norm(b)
        )

    def store_embedding(self, word: str, vector) -> None:
        self.repo.store_sync(word, vector.tolist())
