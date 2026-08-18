import openai
from openai import AsyncOpenAI

from app.config import settings

SYSTEM_PROMPT = (
    "Ты — ассистент салона красоты, отвечающий клиентам на русском языке. "
    "Отвечай дружелюбно и по делу, без лишней воды. Помогай с записью на "
    "услуги, отвечай на вопросы про мастеров, цены и расписание."
)

FALLBACK_REPLY = "К сожалению, сервис временно недоступен. Наш менеджер скоро свяжется с вами!"


class MainAIService:
    """Primary reply-generating model for Russian-language dialogs."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY or None,
            base_url="https://openrouter.ai/api/v1",
        )

    async def generate_reply(self, combined_text: str) -> str:
        print(f"[MAIN_AI] Calling model={settings.MAIN_AI_MODEL}...", flush=True)
        try:
            response = await self._client.chat.completions.create(
                model=settings.MAIN_AI_MODEL,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": combined_text},
                ],
            )
            reply_text = response.choices[0].message.content
        except openai.APIError as exc:
            print(f"[MAIN_AI] API Error: {exc}", flush=True)
            return FALLBACK_REPLY
        except Exception as exc:
            print(f"[MAIN_AI] Unexpected error: {exc}", flush=True)
            return FALLBACK_REPLY

        print(f"[MAIN_AI] Reply: {reply_text}", flush=True)
        return reply_text


main_ai_service = MainAIService()
