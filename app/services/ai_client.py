"""Shared OpenAI-compatible client factory for MainAIService and
GuardrailService.

Both OpenAI and Gemini expose an OpenAI-compatible Chat Completions
endpoint (Gemini's at GEMINI_OPENAI_BASE_URL below), including support for
`tools=` (function calling) and `response_format={"type": "json_object"}` —
verified live against the Gemini endpoint before wiring this in. That means
a single AsyncOpenAI client, pointed at a different base_url/api_key, covers
both providers without any change to the tool-calling loop or JSON-mode
parsing downstream in main_ai_service.py / guardrail_service.py.

Replaces the former OpenRouter-based client (base_url="https://openrouter.ai/api/v1"),
dropped after repeated Cloudflare 403s from OpenRouter's edge.
"""

from openai import AsyncOpenAI

from app.config import settings

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def build_ai_client() -> AsyncOpenAI:
    provider = settings.AI_PROVIDER.strip().lower()
    if provider == "openai":
        return AsyncOpenAI(api_key=settings.OPENAI_API_KEY or None)
    if provider == "gemini":
        return AsyncOpenAI(api_key=settings.GEMINI_API_KEY or None, base_url=GEMINI_OPENAI_BASE_URL)
    raise ValueError(f"Unknown AI_PROVIDER: {settings.AI_PROVIDER!r} (expected 'openai' or 'gemini')")
