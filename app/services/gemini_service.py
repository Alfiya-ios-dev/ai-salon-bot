from sqlalchemy.ext.asyncio import AsyncSession

from google.genai import types
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.config import settings
from app.services.gemini_client import get_gemini_client
from app.services.knowledge_service import get_knowledge_context

BASE_SYSTEM_PROMPT = (
    "Сен сулуулук салонунун жардамчысысың, кыргыз тилинде жооп бересиң. "
    "Кардарга кызматтарды тандоого жана жазылууга жардам бер. Баа жана "
    "тейлөө эрежелери жөнүндө суроолорго төмөндөгү базадагы маалымат "
    "боюнча ГАНА жооп бер (ал орус тилинде жазылганы менен, жообуңду "
    "кыргызча бер); эгер базада жооп жок болсо, ойлоп тапба, ошону тике айт. "
    "Эгер кардар коркунучтуу же сезимтал тема көтөрсө (юридикалык доо, ден "
    "соолук боюнча олуттуу маселе ж.б.), жообуңдун аягында так "
    "'[[STOP_BOT: себеп]]' деп белгиле."
)

STOP_MARKER = "[[STOP_BOT:"

FALLBACK_RESULT_TEXT = "Кечиресиз, учурда техникалык көйгөй бар. Жакында байланышабыз."


class GeminiResult(BaseModel):
    text: str
    is_stop_bot: bool = False
    stop_reason: str | None = None


class GeminiService:
    """Reply-generating model for Kyrgyz-language dialogs, with its own
    stop-topic check (a second, language-specific safety layer on top of
    the guardrail's is_stop_bot check)."""

    async def generate_reply(self, db: AsyncSession, combined_text: str) -> GeminiResult:
        print(f"[GEMINI] Calling model={settings.GEMINI_MODEL}...", flush=True)
        client = get_gemini_client()
        knowledge_context = await get_knowledge_context(db)
        system_prompt = BASE_SYSTEM_PROMPT + knowledge_context
        try:
            response = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=combined_text,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            text = response.text or ""
        except genai_errors.APIError as exc:
            print(f"[GEMINI] API Error: {exc}", flush=True)
            return GeminiResult(text=FALLBACK_RESULT_TEXT)
        except Exception as exc:
            print(f"[GEMINI] Unexpected error: {exc}", flush=True)
            return GeminiResult(text=FALLBACK_RESULT_TEXT)

        if STOP_MARKER in text:
            visible_text, _, marker_tail = text.partition(STOP_MARKER)
            reason = marker_tail.split("]]", 1)[0].strip()
            result = GeminiResult(text=visible_text.strip(), is_stop_bot=True, stop_reason=reason)
        else:
            result = GeminiResult(text=text)

        print(f"[GEMINI] Reply: {result.text!r} is_stop_bot={result.is_stop_bot}", flush=True)
        return result


gemini_service = GeminiService()
