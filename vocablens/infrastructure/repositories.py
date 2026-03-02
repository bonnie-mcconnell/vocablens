from datetime import datetime
from pathlib import Path
import sqlite3

from vocablens.domain.models import VocabularyItem
from vocablens.domain.errors import PersistenceError


class SQLiteVocabularyRepository:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, item: VocabularyItem) -> VocabularyItem:
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO vocabulary (
                        source_text,
                        translated_text,
                        source_lang,
                        target_lang,
                        created_at,
                        last_reviewed_at,
                        review_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.source_text,
                        item.translated_text,
                        item.source_lang,
                        item.target_lang,
                        item.created_at.isoformat(),
                        item.last_reviewed_at.isoformat()
                        if item.last_reviewed_at
                        else None,
                        item.review_count,
                    ),
                )

                item.id = cursor.lastrowid
                return item

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def list_all(self) -> list[VocabularyItem]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM vocabulary ORDER BY created_at DESC"
                ).fetchall()

                return [self._row_to_domain(row) for row in rows]

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def increment_review(self, item_id: int) -> VocabularyItem:
        try:
            with self._connect() as conn:
                now = datetime.utcnow().isoformat()

                cursor = conn.execute(
                    """
                    UPDATE vocabulary
                    SET review_count = review_count + 1,
                        last_reviewed_at = ?
                    WHERE id = ?
                    """,
                    (now, item_id),
                )

                if cursor.rowcount == 0:
                    raise ValueError("Vocabulary item not found")

                row = conn.execute(
                    "SELECT * FROM vocabulary WHERE id = ?",
                    (item_id,),
                ).fetchone()

                return self._row_to_domain(row)

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def _row_to_domain(self, row: sqlite3.Row) -> VocabularyItem:
        return VocabularyItem(
            id=row["id"],
            source_text=row["source_text"],
            translated_text=row["translated_text"],
            source_lang=row["source_lang"],
            target_lang=row["target_lang"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_reviewed_at=(
                datetime.fromisoformat(row["last_reviewed_at"])
                if row["last_reviewed_at"]
                else None
            ),
            review_count=row["review_count"],
        )