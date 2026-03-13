import numpy as np
from openai import OpenAI
import sqlite3
import json


class EmbeddingService:

    def __init__(self, db_path: str = "vocablens.db"):
        self.client = OpenAI()
        self.db_path = db_path

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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vocabulary_embeddings (
                    word TEXT PRIMARY KEY,
                    embedding TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO vocabulary_embeddings (word, embedding)
                VALUES (?, ?)
                """,
                (word, json.dumps(vector.tolist())),
            )
