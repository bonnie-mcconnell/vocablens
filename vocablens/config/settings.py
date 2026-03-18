import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    SECRET_KEY: str = os.getenv("VOCABLENS_SECRET", "dev-secret-change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost/vocablens",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")

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

    ENABLE_BACKGROUND_TASKS: bool = _as_bool(os.getenv("ENABLE_BACKGROUND_TASKS"), False)
    ENABLE_REDIS_CACHE: bool = _as_bool(os.getenv("ENABLE_REDIS_CACHE"), False)


settings = Settings()
