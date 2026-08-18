from typing import Literal

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

SYSTEM_PROMPT = """\
Ты — предохранитель (guardrail) для бота салона красоты. Проанализируй \
сообщение клиента и верни ТОЛЬКО валидный JSON-объект (без markdown, без \
пояснений, без текста до или после) со следующими полями:

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
  ВАЖНО: определяй язык по СТРУКТУРЕ предложения и служебным/обычным \
  словам (предлоги, окончания, грамматика), а НЕ по именам собственным. \
  Кыргызские имена (Гульнара, Айгуль, Нурлан и т.п.) сами по себе не делают \
  предложение кыргызским — они естественно встречаются и в русской речи. \
  Если предложение построено по русской грамматике и состоит из русских \
  слов (даже если в нём упомянуто кыргызское имя мастера или клиента) — \
  язык СТРОГО 'ru'. Выбирай 'ky', только если само предложение целиком или \
  большей частью написано кыргызскими словами.
  ОСОБЫЙ СЛУЧАЙ — короткие сообщения без языковой структуры: если \
  сообщение состоит всего из одного слова/имени (например, просто "Алия" \
  или "Кундуз"), номера телефона, числа или другого обрывка без предлогов/\
  окончаний/грамматики, по которым вообще можно было бы судить о языке — \
  НЕ угадывай язык по звучанию имени. В этом случае верни detected_language \
  равным ТЕКУЩЕМУ ЯЗЫКУ ДИАЛОГА, который указан ниже, а не переключай язык \
  диалога только из-за одного имени или числа.

Пример формата JSON-ответа:
{"is_stop_bot": false, "reason": null, "is_hot_lead": false, "is_refusal": false, "detected_language": "ru"}
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


def _strip_markdown_fence(text: str) -> str:
    # Claude via OpenRouter often wraps JSON in a ```json ... ``` fence even
    # when instructed not to and with response_format=json_object set.
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


class GuardrailService:
    """Cheap/fast classifier that runs before any reply-generating model."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY or None,
            base_url="https://openrouter.ai/api/v1",
        )

    async def check(self, combined_text: str, current_language: str = "ru") -> GuardrailResult:
        print(f"[GUARDRAIL] Calling model={settings.GUARDRAIL_MODEL}...", flush=True)
        system_prompt = f"{SYSTEM_PROMPT}\n\nТекущий язык этого диалога: '{current_language}'."
        try:
            response = await self._client.chat.completions.create(
                model=settings.GUARDRAIL_MODEL,
                max_tokens=512,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": combined_text},
                ],
            )
            raw_content = _strip_markdown_fence(response.choices[0].message.content)
            result = GuardrailResult.model_validate_json(raw_content)
        except openai.APIError as exc:
            print(f"[GUARDRAIL] API Error: {exc}", flush=True)
            return _FALLBACK_RESULT
        except (ValidationError, ValueError) as exc:
            print(f"[GUARDRAIL] Malformed model output: {exc}", flush=True)
            return _FALLBACK_RESULT
        except Exception as exc:
            print(f"[GUARDRAIL] Unexpected error: {exc}", flush=True)
            return _FALLBACK_RESULT

        print(
            f"[GUARDRAIL] language={result.detected_language} "
            f"is_stop_bot={result.is_stop_bot} is_hot_lead={result.is_hot_lead} "
            f"is_refusal={result.is_refusal} reason={result.reason!r}",
            flush=True,
        )
        return result


guardrail_service = GuardrailService()
