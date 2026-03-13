from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    REDIS_URL: str = Field(..., env="REDIS_URL")
    OPENAI_API_KEY: str = Field(..., env="OPENAI_API_KEY")

    LLM_TIMEOUT: float = Field(15.0, env="LLM_TIMEOUT")
    LLM_MAX_RETRIES: int = Field(3, env="LLM_MAX_RETRIES")
    TRANSLATE_TIMEOUT: float = Field(10.0, env="TRANSLATE_TIMEOUT")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
