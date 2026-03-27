import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_tuple(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items if items else default


@dataclass(frozen=True)
class Settings:
    APP_ENV: str = os.getenv("VOCABLENS_ENV", "development")
    SECRET_KEY: str = os.getenv("VOCABLENS_SECRET", "dev-secret-change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost/vocablens",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")

    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "15"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_BACKOFF_BASE: float = float(os.getenv("LLM_BACKOFF_BASE", "0.5"))
    TRANSLATE_TIMEOUT: float = float(os.getenv("TRANSLATE_TIMEOUT", "10"))
    TRANSLATE_MAX_RETRIES: int = int(os.getenv("TRANSLATE_MAX_RETRIES", "3"))
    TRANSLATE_CACHE_TTL: int = int(os.getenv("TRANSLATE_CACHE_TTL", "3600"))
    SPEECH_TIMEOUT: float = float(os.getenv("SPEECH_TIMEOUT", "30"))
    SPEECH_MAX_RETRIES: int = int(os.getenv("SPEECH_MAX_RETRIES", "2"))
    TTS_TIMEOUT: float = float(os.getenv("TTS_TIMEOUT", "30"))
    TTS_MAX_RETRIES: int = int(os.getenv("TTS_MAX_RETRIES", "2"))
    EMBEDDING_TIMEOUT: float = float(os.getenv("EMBEDDING_TIMEOUT", "20"))
    EMBEDDING_MAX_RETRIES: int = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))
    CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "3"))
    CIRCUIT_BREAKER_RESET_SECONDS: float = float(os.getenv("CIRCUIT_BREAKER_RESET_SECONDS", "30"))
    KNOWLEDGE_GRAPH_CACHE_TTL: int = int(os.getenv("KNOWLEDGE_GRAPH_CACHE_TTL", "600"))
    JOB_DEAD_LETTER_QUEUE: str = os.getenv("JOB_DEAD_LETTER_QUEUE", "dead_letter")
    ENABLE_OUTBOUND_NOTIFICATIONS: bool = _as_bool(os.getenv("ENABLE_OUTBOUND_NOTIFICATIONS"), False)
    NOTIFICATION_WEBHOOK_URL: str = os.getenv("NOTIFICATION_WEBHOOK_URL", "")
    NOTIFICATION_TIMEOUT: float = float(os.getenv("NOTIFICATION_TIMEOUT", "5"))
    NOTIFICATION_MAX_RETRIES: int = int(os.getenv("NOTIFICATION_MAX_RETRIES", "2"))

    ENABLE_BACKGROUND_TASKS: bool = _as_bool(os.getenv("ENABLE_BACKGROUND_TASKS"), False)
    ENABLE_REDIS_CACHE: bool = _as_bool(os.getenv("ENABLE_REDIS_CACHE"), False)
    EVENT_INGEST_MODE: str = os.getenv("EVENT_INGEST_MODE", "best_effort").strip().lower()
    CORS_ALLOW_ORIGINS: tuple[str, ...] = _as_tuple(
        os.getenv("CORS_ALLOW_ORIGINS"),
        ("http://localhost:3000", "http://127.0.0.1:3000"),
    )
    CORS_ALLOW_CREDENTIALS: bool = _as_bool(os.getenv("CORS_ALLOW_CREDENTIALS"), True)
    CORS_ALLOW_METHODS: tuple[str, ...] = _as_tuple(os.getenv("CORS_ALLOW_METHODS"), ("*",))
    CORS_ALLOW_HEADERS: tuple[str, ...] = _as_tuple(os.getenv("CORS_ALLOW_HEADERS"), ("*",))

    @property
    def requires_strict_secrets(self) -> bool:
        return self.APP_ENV.strip().lower() in {"prod", "production", "staging"}

    @property
    def using_default_secret(self) -> bool:
        return self.SECRET_KEY == "dev-secret-change-me"


settings = Settings()
