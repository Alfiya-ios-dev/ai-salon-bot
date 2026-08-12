from google import genai

from app.config import settings

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    # Lazy: genai.Client() requires a real API key at construction time, and
    # this is shared by module-level service singletons — constructing it
    # eagerly would crash app startup whenever GEMINI_API_KEY is unset.
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client
