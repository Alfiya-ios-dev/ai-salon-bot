from typing import Literal

import openai
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services.ai_client import build_ai_client

# Explicit, compact category list for is_stop_bot — passed into the prompt
# as a short bullet list instead of a longer free-text explanation, and
# kept as a reusable constant rather than inline prose.
STOP_BOT_CATEGORIES = [
    "просьба позвать человека/менеджера",
    "явная жалоба или агрессия",
    "иное, требующее немедленного вмешательства человека вместо бота",
]

_STOP_BOT_CATEGORIES_TEXT = "\n".join(f"  * {category}" for category in STOP_BOT_CATEGORIES)

# Plain string with a placeholder (not an f-string/`.format()` template) —
# the JSON example below contains literal `{`/`}`, which would collide with
# either of those.
_SYSTEM_PROMPT_TEMPLATE = """\
Ты — предохранитель (guardrail) для бота салона красоты. Проанализируй \
сообщение клиента и верни ТОЛЬКО валидный JSON-объект (без markdown, без \
пояснений, без текста до или после) со следующими полями:

- is_stop_bot: true, если сообщение попадает в одну из категорий:
__STOP_BOT_CATEGORIES__
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

SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.replace("__STOP_BOT_CATEGORIES__", _STOP_BOT_CATEGORIES_TEXT)


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
    # Some models wrap JSON in a ```json ... ``` fence even when instructed
    # not to and with response_format=json_object set — kept as a defensive
    # strip regardless of which AI_PROVIDER/model is active.
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


class GuardrailService:
    """Cheap/fast classifier that runs before any reply-generating model."""

    def __init__(self) -> None:
        self._client = build_ai_client()

    async def check(
        self, combined_text: str, current_language: str = "ru", dialog_summary: str = ""
    ) -> GuardrailResult:
        """Classifies only the messages accumulated since the last debounce
        flush (combined_text) plus, if one exists, the dialog's running
        summary — never the full message history, RAG knowledge base, or
        tool descriptions, none of which this classifier needs.
        """
        print(f"[GUARDRAIL] Calling model={settings.GUARDRAIL_MODEL}...", flush=True)
        system_prompt = f"{SYSTEM_PROMPT}\n\nТекущий язык этого диалога: '{current_language}'."

        user_content = combined_text
        if dialog_summary:
            user_content = f"Краткая сводка диалога: {dialog_summary}\n\nТекущее сообщение клиента:\n{combined_text}"

        try:
            response = await self._client.chat.completions.create(
                model=settings.GUARDRAIL_MODEL,
                max_tokens=512,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
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
