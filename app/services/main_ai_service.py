import traceback

from anthropic import AsyncAnthropic

from app.config import settings

SYSTEM_PROMPT = (
    "Ты — ассистент салона красоты, отвечающий клиентам на русском языке. "
    "Отвечай дружелюбно и по делу, без лишней воды. Помогай с записью на "
    "услуги, отвечай на вопросы про мастеров, цены и расписание."
)

FALLBACK_REPLY = (
    "Извините, у нас временные технические неполадки. "
    "Наш менеджер скоро свяжется с вами."
)


class MainAIService:
    """Primary reply-generating model for Russian-language dialogs."""

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or None)

    async def generate_reply(self, combined_text: str) -> str:
        print(f"[MAIN AI] Calling model={settings.MAIN_AI_MODEL}...", flush=True)
        try:
            response = await self._client.messages.create(
                model=settings.MAIN_AI_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": combined_text}],
            )
            reply_text = next(block.text for block in response.content if block.type == "text")
        except Exception:
            print("[MAIN AI] ERROR calling Anthropic API — returning fallback reply:", flush=True)
            traceback.print_exc()
            return FALLBACK_REPLY

        print(f"[MAIN AI] Reply: {reply_text}", flush=True)
        return reply_text


main_ai_service = MainAIService()
