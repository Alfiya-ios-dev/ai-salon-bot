from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Connection to tenant_registry_db (the shared registry of businesses),
    # NOT to any tenant's own data — see app/tenant_db.py for that.
    DATABASE_URL: str = "postgresql+asyncpg://salon_user:salon_pass@localhost:5432/tenant_registry_db"
    DEBOUNCE_DELAY_SECONDS: float = 3.0

    OPENROUTER_API_KEY: str = ""
    GUARDRAIL_MODEL: str = "anthropic/claude-haiku-4.5"
    MAIN_AI_MODEL: str = "anthropic/claude-sonnet-5"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"

    JWT_SECRET_KEY: str = "dev-only-insecure-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Comma-separated list of frontend origins allowed to call the API with
    # credentials (see CORSMiddleware in app/main.py). Wildcard ("*") isn't
    # used here because browsers reject credentialed requests against it —
    # set this to the real admin-panel domain(s) via .env in production.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
