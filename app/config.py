from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://salon_user:salon_pass@localhost:5432/salon_db"
    DEBOUNCE_DELAY_SECONDS: float = 3.0

    ANTHROPIC_API_KEY: str = ""
    GUARDRAIL_MODEL: str = "claude-haiku-4-5"
    MAIN_AI_MODEL: str = "claude-opus-5"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
