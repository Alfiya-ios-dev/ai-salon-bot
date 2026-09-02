from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Connection to tenant_registry_db (the shared registry of businesses),
    # NOT to any tenant's own data — see app/tenant_db.py for that.
    DATABASE_URL: str = "postgresql+asyncpg://salon_user:salon_pass@localhost:5432/tenant_registry_db"
    DEBOUNCE_DELAY_SECONDS: float = 3.0

    # Provider for MainAIService (function-calling reply model) and
    # GuardrailService (fast classifier) — "openai" or "gemini". Both are
    # called through the same AsyncOpenAI client shape: OpenAI natively,
    # Gemini via its OpenAI-compatible endpoint (see app/services/ai_client.py).
    # Replaces the former OpenRouter-based client, dropped after repeated
    # Cloudflare 403s from OpenRouter's edge.
    AI_PROVIDER: str = "openai"
    AI_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str = ""

    # Cheap/fast classifier model for GuardrailService — deliberately
    # separate from AI_MODEL so it can stay on a smaller model than the main
    # reply generator regardless of which AI_PROVIDER is active.
    GUARDRAIL_MODEL: str = "gpt-4o-mini"

    # Unrelated to AI_PROVIDER above: GeminiService (app/services/gemini_service.py)
    # is a separate, Kyrgyz-language reply path that always talks to Gemini
    # directly via the native google-genai SDK, not the OpenAI-compat client.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"

    # Used only by scripts/tooling for convenience (e.g. printing the
    # setWebhook command) — actual webhook routing is DB-driven via
    # Tenant.telegram_bot_token (app/registry_models.py), not this setting,
    # since different tenants can link different bot tokens.
    TELEGRAM_BOT_TOKEN: str = ""

    # Where pilot-limit warnings (see app/services/pilot_limit_service.py)
    # get sent for dalfy's own team, in addition to the log line that always
    # fires. Uses TELEGRAM_BOT_TOKEN above. Left empty by default — no
    # dalfy-admin Telegram chat is configured yet, so only the log fires.
    DALFY_ADMIN_TELEGRAM_CHAT_ID: str = ""

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
