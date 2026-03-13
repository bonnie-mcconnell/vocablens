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
                ease_factor REAL NOT NULL DEFAULT 2.5,
                interval INTEGER NOT NULL DEFAULT 1,
                repetitions INTEGER NOT NULL DEFAULT 0,
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
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                translation TEXT NOT NULL,
                PRIMARY KEY (text, source_lang, target_lang)
            );
            """
        )

        # ---------------------------------------------------
        # Learning intelligence tables
        # ---------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                skill TEXT NOT NULL,
                score REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translation_cache_langs ON translation_cache(source_lang, target_lang)"
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_history_user ON conversation_history(user_id, created_at)"
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_history_user ON skill_history(user_id, created_at)"
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learning_events_user ON learning_events(user_id, created_at)"
        )

        # ---------------------------------------------------
        # Backfill / migrations for existing DBs
        # ---------------------------------------------------
        for stmt in [
            "ALTER TABLE vocabulary ADD COLUMN ease_factor REAL NOT NULL DEFAULT 2.5",
            "ALTER TABLE vocabulary ADD COLUMN interval INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE vocabulary ADD COLUMN repetitions INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                # Column probably already exists
                pass
