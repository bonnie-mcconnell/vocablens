import numpy as np
from openai import OpenAI

from vocablens.infrastructure.postgres_embedding_repository import PostgresEmbeddingRepository
from vocablens.infrastructure.observability.metrics import LLM_COST, LLM_TOKENS
from vocablens.infrastructure.observability.token_tracker import add_tokens
from vocablens.config.settings import settings
from vocablens.infrastructure.resilience import CircuitBreaker, sync_retry


class EmbeddingService:

    def __init__(self, repo: PostgresEmbeddingRepository):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY or None,
            timeout=settings.EMBEDDING_TIMEOUT,
            max_retries=0,
        )
        self.repo = repo
        self._circuit = CircuitBreaker(
            name="openai_embedding",
            failure_threshold=settings.CIRCUIT_BREAKER_THRESHOLD,
            reset_timeout_seconds=settings.CIRCUIT_BREAKER_RESET_SECONDS,
        )

    def embed(self, text: str):
        def _call():
            self._circuit.ensure_closed()
            try:
                result = self.client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text,
                )
            except Exception:
                self._circuit.record_failure()
                raise
            self._circuit.record_success()
            return result

        result = sync_retry(
            name="openai_embedding",
            func=_call,
            attempts=settings.EMBEDDING_MAX_RETRIES,
            backoff_base=0.5,
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
