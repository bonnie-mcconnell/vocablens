import sqlite3
from pathlib import Path


def init_db(db_path: Path) -> None:

    with sqlite3.connect(db_path) as conn:

        conn.execute("PRAGMA foreign_keys = ON;")

        # ---------------------------------------------------
        # Users
        # ---------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        # ---------------------------------------------------
        # Vocabulary
        # ---------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,

                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,

                created_at TEXT NOT NULL,

                last_reviewed_at TEXT,
                review_count INTEGER NOT NULL DEFAULT 0,
                retention_score REAL NOT NULL DEFAULT 2.5,
                next_review_due TEXT,

                example_source_sentence TEXT,
                example_translated_sentence TEXT,
                grammar_note TEXT,
                semantic_cluster TEXT,

                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

                UNIQUE(user_id, source_text, source_lang, target_lang)
            );
            """
        )

        # ---------------------------------------------------
        # Translation cache
        # ---------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_cache (
                text TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                translation TEXT NOT NULL,
                PRIMARY KEY (text, target_lang)
            );
            """
        )

        # ---------------------------------------------------
        # Indexes
        # ---------------------------------------------------

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vocab_user_id ON vocabulary(user_id)"
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vocab_next_due ON vocabulary(next_review_due)"
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vocab_cluster ON vocabulary(semantic_cluster)"
        )