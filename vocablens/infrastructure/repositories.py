from datetime import datetime
from pathlib import Path
import sqlite3

from vocablens.domain.models import VocabularyItem
from vocablens.domain.errors import PersistenceError


class SQLiteVocabularyRepository:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def add(self, item: VocabularyItem) -> VocabularyItem:
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cursor.execute(
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

            conn.commit()
            item.id = cursor.lastrowid
            return item

        except Exception as exc:
            raise PersistenceError(str(exc)) from exc
        finally:
            conn.close()