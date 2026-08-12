import traceback
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings

SYSTEM_PROMPT = """\
Ты — предохранитель (guardrail) для бота салона красоты. Проанализируй \
сообщение клиента и верни JSON со следующими полями:

- is_stop_bot: true, если клиент просит позвать человека/менеджера, явно \
жалуется, агрессивен, либо пишет что-то, требующее немедленного вмешательства \
человека вместо бота.
- reason: краткая причина на русском, если is_stop_bot или is_hot_lead — \
иначе null.
- is_hot_lead: true, если клиент явно готов записаться или купить прямо \
сейчас и стоит подключить менеджера, чтобы не упустить продажу.
- is_refusal: true, если клиент явно отказывается от услуг или прощается и \
не планирует продолжать диалог.
- detected_language: 'ru' или 'ky' — определи, на каком из этих двух языков \
написано сообщение.
"""


class GuardrailResult(BaseModel):
    is_stop_bot: bool
    reason: str | None = None
    is_hot_lead: bool
    is_refusal: bool
    detected_language: Literal["ru", "ky"]


# On API failure the pipeline must not crash — fall back to "everything looks
# normal" so the rest of the chain (Main AI / Gemini reply) can still run.
_FALLBACK_RESULT = GuardrailResult(
    is_stop_bot=False,
    reason=None,
    is_hot_lead=False,
    is_refusal=False,
    detected_language="ru",
)


class GuardrailService:
    """Cheap/fast classifier that runs before any reply-generating model."""

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or None)

    async def check(self, combined_text: str) -> GuardrailResult:
        print(f"[GUARDRAIL] Calling model={settings.GUARDRAIL_MODEL}...", flush=True)
        try:
            response = await self._client.messages.parse(
                model=settings.GUARDRAIL_MODEL,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": combined_text}],
                output_format=GuardrailResult,
            )
            result = response.parsed_output
        except Exception:
            print("[GUARDRAIL] ERROR calling Anthropic API — falling back to safe defaults:", flush=True)
            traceback.print_exc()
            return _FALLBACK_RESULT

        print(
            f"[GUARDRAIL] language={result.detected_language} "
            f"is_stop_bot={result.is_stop_bot} is_hot_lead={result.is_hot_lead} "
            f"is_refusal={result.is_refusal} reason={result.reason!r}",
            flush=True,
        )
        return result


guardrail_service = GuardrailService()
