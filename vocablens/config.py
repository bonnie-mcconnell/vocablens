import os


class Settings:
    SECRET_KEY: str = os.getenv("VOCABLENS_SECRET", "dev-secret-change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    )


settings = Settings()