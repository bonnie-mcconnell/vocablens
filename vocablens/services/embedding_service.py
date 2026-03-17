import numpy as np
from openai import OpenAI
import json

from vocablens.infrastructure.postgres_embedding_repository import PostgresEmbeddingRepository


class EmbeddingService:

    def __init__(self, repo: PostgresEmbeddingRepository):
        self.client = OpenAI()
        self.repo = repo

    def embed(self, text: str):

        result = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )

        return np.array(result.data[0].embedding)

    def similarity(self, a, b):

        return np.dot(a, b) / (
            np.linalg.norm(a) * np.linalg.norm(b)
        )

    def store_embedding(self, word: str, vector) -> None:
        self.repo.store_sync(word, vector.tolist())
