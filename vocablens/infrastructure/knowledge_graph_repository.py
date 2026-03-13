import sqlite3
from typing import List, Dict


class KnowledgeGraphRepository:
    def __init__(self, db_path: str = "vocablens.db"):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_edge(self, source_node: str, target_node: str, relation_type: str, weight: float = 1.0):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_graph_edges (source_node, target_node, relation_type, weight)
                VALUES (?, ?, ?, ?)
                """,
                (source_node, target_node, relation_type, weight),
            )

    def list_edges(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_graph_edges"
            ).fetchall()
            return [dict(r) for r in rows]
