from datetime import datetime
from pathlib import Path
import sqlite3
from typing import List

from vocablens.domain.models import VocabularyItem
from vocablens.domain.errors import PersistenceError


class SQLiteVocabularyRepository:

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    # ----------------------------------------------------
    # CREATE
    # ----------------------------------------------------

    def add(self, user_id: int, item: VocabularyItem) -> VocabularyItem:

        try:

            with self._connect() as conn:

                cursor = conn.execute(
                    """
                    INSERT INTO vocabulary (
                        user_id,
                        source_text,
                        translated_text,
                        source_lang,
                        target_lang,
                        created_at,
                        last_reviewed_at,
                        review_count,
                        ease_factor,
                        interval,
                        repetitions,
                        next_review_due
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        item.source_text,
                        item.translated_text,
                        item.source_lang,
                        item.target_lang,
                        item.created_at.isoformat(),
                        item.last_reviewed_at.isoformat()
                        if item.last_reviewed_at else None,
                        item.review_count,
                        item.ease_factor,
                        item.interval,
                        item.repetitions,
                        item.next_review_due.isoformat()
                        if item.next_review_due else None,
                    ),
                )

                item.id = cursor.lastrowid
                return item

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    # ----------------------------------------------------
    # READ
    # ----------------------------------------------------

    def list_all(
        self,
        user_id: int,
        limit: int,
        offset: int,
    ) -> List[VocabularyItem]:

        try:

            with self._connect() as conn:

                rows = conn.execute(
                    """
                    SELECT *
                    FROM vocabulary
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset),
                ).fetchall()

                return [self._row_to_domain(r) for r in rows]

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def list_due(self, user_id: int) -> List[VocabularyItem]:

        try:

            with self._connect() as conn:

                now = datetime.utcnow().isoformat()

                rows = conn.execute(
                    """
                    SELECT *
                    FROM vocabulary
                    WHERE user_id = ?
                    AND next_review_due IS NOT NULL
                    AND next_review_due <= ?
                    ORDER BY next_review_due ASC
                    """,
                    (user_id, now),
                ).fetchall()

                return [self._row_to_domain(r) for r in rows]

        except sqlite3.Error as exc:
            raise PersistenceError(str(exc)) from exc

    def get(
        self,
        user_id: int,
        item_id: int,
    ) -> VocabularyItem | None:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM vocabulary
                WHERE id = ? AND user_id = ?
                """,
                (item_id, user_id),
            ).fetchone()

            if not row:
                return None

            return self._row_to_domain(row)
        

    def get_by_id(self, item_id: int) -> VocabularyItem | None:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM vocabulary
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()

            if not row:
                return None

            return self._row_to_domain(row)
        
    
    def exists(
        self,
        user_id: int,
        source_text: str,
        source_lang: str,
        target_lang: str,
    ) -> bool:

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT 1
                FROM vocabulary
                WHERE user_id = ?
                AND source_text = ?
                AND source_lang = ?
                AND target_lang = ?
                LIMIT 1
                """,
                (
                    user_id,
                    source_text,
                    source_lang,
                    target_lang,
                ),
            ).fetchone()

            return row is not None

    # ----------------------------------------------------
    # UPDATE
    # ----------------------------------------------------

    def update(self, item: VocabularyItem) -> VocabularyItem:

        with self._connect() as conn:

            conn.execute(
                """
                UPDATE vocabulary
                SET
                    last_reviewed_at = ?,
                    review_count = ?,
                    ease_factor = ?,
                    interval = ?,
                    repetitions = ?,
                    next_review_due = ?
                WHERE id = ?
                """,
                (
                    item.last_reviewed_at.isoformat()
                    if item.last_reviewed_at else None,
                    item.review_count,
                    item.ease_factor,
                    item.interval,
                    item.repetitions,
                    item.next_review_due.isoformat()
                    if item.next_review_due else None,
                    item.id,
                ),
            )

        return item
    

    def update_enrichment(
        self,
        item_id: int,
        example_source: str | None,
        example_translation: str | None,
        grammar: str | None,
        cluster: str | None,
    ):

        with self._connect() as conn:

            conn.execute(
                """
                UPDATE vocabulary
                SET
                    example_source_sentence = ?,
                    example_translated_sentence = ?,
                    grammar_note = ?,
                    semantic_cluster = ?
                WHERE id = ?
                """,
                (
                    example_source,
                    example_translation,
                    grammar,
                    cluster,
                    item_id,
                ),
            )

    # ----------------------------------------------------
    # MAPPER
    # ----------------------------------------------------

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
            ease_factor=row["ease_factor"],
            interval=row["interval"],
            repetitions=row["repetitions"],
            next_review_due=(
                datetime.fromisoformat(row["next_review_due"])
                if row["next_review_due"]
                else None
            ),
        ) 
