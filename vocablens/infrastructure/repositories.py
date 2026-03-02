from datetime import datetime, timedelta
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
                        review_count,
                        retention_score,
                        next_review_due
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
                        item.retention_score,
                        item.next_review_due.isoformat() if item.next_review_due else None,
                    ),
                )

                item.id = cursor.lastrowid
                return item

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc


    def list_all(self, limit: int, offset: int) -> list[VocabularyItem]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM vocabulary
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()

                return [self._row_to_domain(row) for row in rows]

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc
        

    def increment_review(self, item_id: int) -> VocabularyItem:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM vocabulary WHERE id = ?",
                    (item_id,),
                ).fetchone()

                if not row:
                    raise ValueError("Vocabulary item not found")

                review_count = row["review_count"] + 1
                retention_score = row["retention_score"]
                now = datetime.utcnow()

                # Basic SM-2 inspired update
                retention_score = max(1.3, retention_score + 0.1)

                if review_count == 1:
                    interval_days = 1
                elif review_count == 2:
                    interval_days = 3
                else:
                    interval_days = int(review_count * retention_score)

                next_review_due = now.replace(microsecond=0) + \
                    timedelta(days=interval_days)

                conn.execute(
                    """
                    UPDATE vocabulary
                    SET review_count = ?,
                        last_reviewed_at = ?,
                        retention_score = ?,
                        next_review_due = ?
                    WHERE id = ?
                    """,
                    (
                        review_count,
                        now.isoformat(),
                        retention_score,
                        next_review_due.isoformat(),
                        item_id,
                    ),
                )

                updated = conn.execute(
                    "SELECT * FROM vocabulary WHERE id = ?",
                    (item_id,),
                ).fetchone()

                return self._row_to_domain(updated)

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
            retention_score=row["retention_score"],
            next_review_due=(
                datetime.fromisoformat(row["next_review_due"])
                if row["next_review_due"]
                else None
            ),
        )
    
    def list_due(self) -> list[VocabularyItem]:
        try:
            with self._connect() as conn:
                now = datetime.utcnow().isoformat()

                rows = conn.execute(
                    """
                    SELECT * FROM vocabulary
                    WHERE next_review_due IS NOT NULL
                    AND next_review_due <= ?
                    ORDER BY next_review_due ASC
                    """,
                    (now,),
                ).fetchall()

                return [self._row_to_domain(r) for r in rows]

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc