import sqlite3


class SQLiteTranslationCacheRepository:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, text: str, target_lang: str):

        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT translation
                FROM translation_cache
                WHERE text=? AND target_lang=?
                """,
                (text, target_lang),
            )

            row = cur.fetchone()
            return row["translation"] if row else None

    def save(self, text: str, target_lang: str, translation: str):

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO translation_cache
                (text, target_lang, translation)
                VALUES (?, ?, ?)
                """,
                (text, target_lang, translation),
            )