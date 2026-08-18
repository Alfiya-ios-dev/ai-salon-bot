import difflib
import json
import re
from datetime import date, datetime, timezone

import openai
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Message, SenderType, Staff
from app.services import booking_service
from app.services.knowledge_service import get_knowledge_context

BASE_SYSTEM_PROMPT = (
    "Ты — заботливый и приветливый администратор салона красоты, общаешься с "
    "клиентами на русском языке. Пиши тепло и живо, как человек, а не как "
    "робот: уместны разговорные фразы вроде 'С удовольствием подберу "
    "окошко!', 'Отлично!', 'Будем ждать вас!' и сдержанные эмодзи (😊, ✨) — "
    "но не в каждом сообщении и без перебора. Избегай канцеляризмов и "
    "сухого официального тона. При этом отвечай по делу, без лишней воды.\n\n"
    "Для работы с записью используй инструменты:\n"
    "- find_available_slots — чтобы посмотреть свободное время перед тем, как "
    "предлагать клиенту конкретный слот. Не придумывай время сам.\n"
    "- list_available_masters — если клиент явно спрашивает, КТО из мастеров "
    "свободен/доступен на конкретную дату и время (например 'кто из мастеров "
    "свободен завтра в 14:00?'). Вызови этот инструмент и назови клиенту "
    "реальные имена мастеров из результата (например 'Свободны Тумар и "
    "Бени'). НИКОГДА не отвечай на такой вопрос шаблонной фразой вроде "
    "'мастера подберём автоматически' — клиент явно спросил имена, значит "
    "нужно их назвать.\n"
    "- create_booking — только когда клиент явно подтвердил конкретные "
    "дату/время из числа свободных слотов и назвал своё имя и телефон.\n"
    "- cancel_booking — когда клиент просит отменить свою запись.\n"
    "Если инструмент вернул ошибку (например, время уже занято), сообщи об "
    "этом клиенту по-человечески и предложи альтернативу, не повторяй "
    "техническое сообщение об ошибке дословно.\n\n"
    "ВАЖНО про service_name в find_available_slots и create_booking:\n"
    "- Услугу для service_name бери СТРОГО из ПОСЛЕДНЕГО сообщения клиента, "
    "если она там явно названа. Никогда не подставляй услугу по умолчанию "
    "(например, 'Стрижка') и не переиспользуй услугу из более ранней "
    "переписки, если сейчас клиент явно назвал другую или вообще другую не "
    "называл — бери ровно то, что он написал только что.\n"
    "- Историю переписки используй, чтобы не переспрашивать мастера/дату/имя/"
    "телефон, которые клиент уже называл, и чтобы понимать контекст — но "
    "НЕ для того, чтобы додумывать за клиента услугу, если он сам её не "
    "назвал в последнем сообщении.\n"
    "- Если клиент раньше в переписке спрашивал про одну услугу (например, "
    "окрашивание), а сейчас при записи называет другую (например, стрижку) "
    "или формулирует сообщение размыто (не ясно, о какой услуге речь) — "
    "прежде чем звать create_booking, мягко уточни у него, на какую именно "
    "услугу записываем, не додумывай сам. Например: 'Супер! Подскажите, мы "
    "записываемся именно на окрашивание или ещё добавим стрижку?' или "
    "'Правильно понимаю, что планируем окрашивание, о котором говорили "
    "ранее?'.\n\n"
    "ЖЁСТКИЙ ЗАПРЕТ про client_name и client_phone в create_booking:\n"
    "Категорически запрещено вызывать create_booking, если клиент НЕ назвал "
    "своё имя и номер телефона явно и лично в этой беседе. Никогда не бери "
    "имя или телефон из примеров, из имени мастера, из общих знаний или "
    "'на всякий случай' — это чужие персональные данные, подставлять их "
    "недопустимо. Если хотя бы одного из двух (имени или телефона) в "
    "переписке не было — сначала вежливо спроси именно то, чего не "
    "хватает, и жди ответа клиента.\n"
    "Когда берёшь имя и телефон из сообщения клиента — передавай их РОВНО "
    "так, как клиент написал, меняя только регистр первой буквы имени на "
    "заглавную (например 'алия' -> 'Алия'). Запрещено 'исправлять', "
    "дополнять или переписывать имя/телефон по-своему (например 'алия' -> "
    "'Алтия' или 'Алина') — если не уверен, как правильно пишется имя, "
    "используй написание клиента как есть, не выдумывай альтернативу.\n"
    "Если и имя, и телефон прямо присутствуют в ПОСЛЕДНЕМ сообщении "
    "клиента (например 'алия 0550101855' одним сообщением) — этого "
    "достаточно, вызывай create_booking сразу, с первого раза. Не проси "
    "клиента повторить или подтвердить то, что он уже явно написал.\n"
    "Вызывай create_booking только тогда, когда оба значения дословно "
    "присутствуют в сообщениях клиента.\n\n"
    "ВАЖНО про master_name — клиент НЕ ОБЯЗАН называть мастера:\n"
    "Если клиент явно назвал конкретного мастера — передавай его имя в "
    "master_name. Если клиент НЕ назвал мастера — НЕ спрашивай, к какому "
    "мастеру он хочет попасть, это необязательно. В этом случае просто "
    "передай master_name=None (оставь параметр пустым) в find_available_slots "
    "и create_booking — бэкенд сам подберёт свободного мастера. Никогда не "
    "придумывай значения вроде 'любой мастер' или 'любой свободный мастер' "
    "и не подставляй имя мастера, которого клиент не называл. После "
    "успешного create_booking результат содержит поле master_name — "
    "назначенного мастера. В подтверждении брони естественно упомяни его, "
    "например: 'Ждём вас! Ваш мастер — Алина ✨' (бери имя именно из "
    "результата вызова, а не придумывай)."
)

FIRST_MESSAGE_INSTRUCTION = (
    "\n\nВАЖНО: это первое сообщение клиента в этом диалоге. Твой ИТОГОВЫЙ "
    "текстовый ответ клиенту (тот, что не является вызовом инструмента) "
    "обязан начинаться с короткого вежливого приветствия, и только потом "
    "переходить к сути. Это правило действует и тогда, когда перед ответом "
    "тебе нужно сначала вызвать find_available_slots или другой инструмент — "
    "не забудь поздороваться в итоговом сообщении после этого."
)

FALLBACK_REPLY = "К сожалению, сервис временно недоступен. Наш менеджер скоро свяжется с вами!"

MAX_TOOL_ROUNDS = 5

# How many past messages (client + bot) to load as conversation history.
# The salon bot's conversations are short, so a generous cap is cheap and
# just guards against unbounded context growth in a very long test session.
MAX_HISTORY_MESSAGES = 30

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_available_slots",
            "description": (
                "Найти свободные слоты для записи на услугу на конкретную дату. "
                "Используй перед тем, как предложить клиенту время."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": (
                            "Точное название услуги, как в прайс-листе. Бери СТРОГО из "
                            "последнего сообщения клиента (если там названа услуга) — "
                            "не подставляй услугу по умолчанию и не бери её из более "
                            "ранней переписки."
                        ),
                    },
                    "target_date": {
                        "type": "string",
                        "description": "Дата в формате YYYY-MM-DD",
                    },
                    "master_name": {
                        "type": "string",
                        "description": "Имя мастера, если клиент указал конкретного. Не указывай, если это не важно.",
                    },
                },
                "required": ["service_name", "target_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_available_masters",
            "description": (
                "Узнать, КАКИЕ ИМЕННО мастера свободны на конкретную услугу "
                "в конкретную дату и время. Используй, когда клиент явно "
                "спрашивает 'кто свободен', 'какие мастера доступны' и "
                "похожие вопросы — результат содержит реальные имена, их и "
                "нужно назвать клиенту."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Название услуги"},
                    "booking_datetime": {
                        "type": "string",
                        "description": "Дата и время в формате YYYY-MM-DD HH:MM",
                    },
                },
                "required": ["service_name", "booking_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": (
                "Создать запись клиента на услугу к мастеру на конкретное время. "
                "Вызывай только после подтверждения клиентом даты/времени из "
                "числа свободных слотов и получения его имени и телефона."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "master_name": {
                        "type": "string",
                        "description": (
                            "Имя мастера — указывай ТОЛЬКО если клиент сам явно назвал "
                            "конкретного мастера. Если клиенту не важно, кто именно, "
                            "оставь это поле пустым (не заполняй его) — бэкенд сам "
                            "назначит свободного мастера на эту услугу и время. Не "
                            "придумывай значения вроде 'любой' или 'любой свободный'."
                        ),
                    },
                    "service_name": {
                        "type": "string",
                        "description": (
                            "Название услуги — та, что клиент подтвердил для записи именно "
                            "сейчас. Если она отличается от той, что обсуждалась раньше в "
                            "переписке, или неясна — сначала мягко уточни у клиента, не "
                            "вызывай create_booking с угаданной услугой."
                        ),
                    },
                    "booking_datetime": {
                        "type": "string",
                        "description": "Дата и время в формате YYYY-MM-DD HH:MM",
                    },
                    "client_name": {
                        "type": "string",
                        "description": (
                            "Имя клиента — ТОЛЬКО если он сам его назвал в этой беседе. "
                            "Запрещено придумывать или подставлять чужое имя."
                        ),
                    },
                    "client_phone": {
                        "type": "string",
                        "description": (
                            "Телефон клиента — ТОЛЬКО если он сам его назвал в этой беседе. "
                            "Запрещено придумывать или подставлять чужой номер."
                        ),
                    },
                },
                "required": ["service_name", "booking_datetime", "client_name", "client_phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": (
                "Отменить запись клиента в этом диалоге. Если клиент не называл "
                "конкретный ID записи, оставь booking_id пустым — отменится его "
                "последняя активная запись."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "integer", "description": "ID записи, если клиент его назвал"},
                },
                "required": [],
            },
        },
    },
]


def _require_str(args: dict, key: str) -> str:
    """Pulls a required string argument out of LLM-supplied tool-call JSON.

    Tool schemas declare these as "type": "string", but models occasionally
    emit an unquoted number for fields that look numeric (e.g. a phone
    number) despite the schema. asyncpg raises a raw TypeError deep inside
    the INSERT ("text_encode ... expected str, got int") if that reaches a
    VARCHAR column undetected, which crashes the whole pipeline turn — so
    scalars are coerced to str here, and anything else (missing, list,
    dict, empty) is rejected with a clear error the caller can catch.
    """
    if key not in args:
        raise KeyError(key)
    value = args[key]
    if isinstance(value, str):
        value = value.strip()
    elif isinstance(value, (int, float)):
        value = str(value)
    else:
        raise ValueError(f"invalid_{key}_type")
    if not value:
        raise ValueError(f"empty_{key}")
    return value


# Below this similarity ratio a name is treated as unrelated to anything in
# the conversation (blocked); at or above it, it's treated as the model's
# own case-normalization or a minor transcription slip of a name the client
# actually typed (allowed). Calibrated against real examples: same name
# with only capitalization/word-ending differences ("иван"/"ивана",
# "алия"/"алтия" with one inserted letter) scores ~0.89; a genuinely
# different name ("алия"/"алина") scores ~0.67 — 0.8 sits cleanly between.
_NAME_FUZZY_THRESHOLD = 0.8


def _name_confirmed(history_text_lower: str, client_name: str) -> bool:
    claimed = client_name.strip().lower()
    if not claimed:
        return False
    if claimed in history_text_lower:
        return True

    # Fuzzy fallback only: catches the model normalizing case ("алия" ->
    # "Алия") or introducing a one-letter slip ("алия" -> "Алтия") when
    # transcribing a name the client actually typed — not a general
    # "sounds similar" match, which could let through a different client's
    # name and misattribute the booking.
    words = re.findall(r"[^\W\d_]+", history_text_lower, re.UNICODE)
    word_count = len(claimed.split())
    candidates = (
        words
        if word_count <= 1
        else [" ".join(words[i : i + word_count]) for i in range(len(words) - word_count + 1)]
    )
    return any(
        difflib.SequenceMatcher(None, claimed, candidate).ratio() >= _NAME_FUZZY_THRESHOLD
        for candidate in candidates
    )


def _client_info_confirmed(history: list[dict], client_name: str, client_phone: str) -> bool:
    """Deterministic guard against create_booking hallucinating client_name /
    client_phone: checks that both actually appear somewhere in this
    dialog's conversation, rather than trusting the model's own compliance
    with the "don't invent contact info" prompt instruction.

    Name matching tolerates case changes and small transcription slips (see
    _name_confirmed) since the model routinely capitalizes names the client
    typed in lowercase. Phone numbers are compared as digit-only, matched on
    the last 9 digits (the national number) — formatting differences
    (spaces, dashes, missing '+'/country code) are tolerated, but the digits
    themselves are never fuzzy-matched: a single wrong digit is a different
    phone number, not a typo to forgive.
    """
    history_text_lower = " ".join(turn.get("content") or "" for turn in history).lower()

    name_ok = _name_confirmed(history_text_lower, client_name)

    phone_digits = re.sub(r"\D", "", client_phone)
    history_digits = re.sub(r"\D", "", history_text_lower)
    phone_ok = len(phone_digits) >= 6 and phone_digits[-9:] in history_digits

    return name_ok and phone_ok


def _optional_int(args: dict, key: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"invalid_{key}_type")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ValueError(f"invalid_{key}_type")


class MainAIService:
    """Primary reply-generating model for Russian-language dialogs, with
    function-calling access to the booking service."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY or None,
            base_url="https://openrouter.ai/api/v1",
        )

    async def _load_history(self, db: AsyncSession, dialog_id: int) -> list[dict]:
        """Loads this dialog's past messages as OpenAI-style chat turns.

        Callers (webhook.py, scripts/chat_cli.py) save the client's current
        message to `messages` *before* invoking the pipeline, so the current
        turn is already the last entry here — nothing else needs to append
        combined_text again.
        """
        result = await db.execute(
            select(Message)
            .where(Message.dialog_id == dialog_id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
        rows = list(reversed(result.scalars().all()))

        history = []
        for msg in rows:
            if msg.sender_type == SenderType.client:
                role = "user"
            elif msg.sender_type in (SenderType.bot, SenderType.manager):
                role = "assistant"
            else:
                continue
            if msg.text:
                history.append({"role": role, "content": msg.text})
        return history

    async def _execute_tool(
        self, db: AsyncSession, dialog_id: int, name: str, arguments: str, history: list[dict]
    ) -> dict:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": "invalid_arguments_json"}

        print(f"[MAIN_AI] Tool call: {name}({args})", flush=True)

        try:
            if name == "find_available_slots":
                try:
                    target_date = date.fromisoformat(_require_str(args, "target_date"))
                    service_name = _require_str(args, "service_name")
                    master_name = _require_str(args, "master_name") if args.get("master_name") else None
                except (KeyError, ValueError) as exc:
                    result = {"error": str(exc) or "invalid_arguments"}
                else:
                    try:
                        slots = await booking_service.find_available_slots(
                            db, service_name=service_name, target_date=target_date, master_name=master_name
                        )
                    except ValueError as exc:
                        result = {"error": str(exc)}
                    else:
                        result = {"available_slots": [slot.strftime("%Y-%m-%d %H:%M") for slot in slots]}

            elif name == "list_available_masters":
                try:
                    booking_dt = datetime.strptime(
                        _require_str(args, "booking_datetime"), "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=timezone.utc)
                    service_name = _require_str(args, "service_name")
                except (KeyError, ValueError) as exc:
                    result = {"error": str(exc) or "invalid_arguments"}
                else:
                    try:
                        names = await booking_service.list_available_masters(db, service_name, booking_dt)
                    except ValueError as exc:
                        result = {"error": str(exc)}
                    else:
                        result = {"available_masters": names}

            elif name == "create_booking":
                try:
                    booking_dt = datetime.strptime(
                        _require_str(args, "booking_datetime"), "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=timezone.utc)
                    master_name = _require_str(args, "master_name") if args.get("master_name") else None
                    service_name = _require_str(args, "service_name")
                    client_name = _require_str(args, "client_name")
                    client_phone = _require_str(args, "client_phone")
                except (KeyError, ValueError) as exc:
                    result = {"error": str(exc) or "invalid_arguments"}
                else:
                    if not _client_info_confirmed(history, client_name, client_phone):
                        print(
                            f"[MAIN_AI] BLOCKED create_booking: client_name={client_name!r} "
                            f"client_phone={client_phone!r} not found in conversation history",
                            flush=True,
                        )
                        result = {"error": "client_info_not_confirmed_in_conversation"}
                    else:
                        booking, err = await booking_service.create_booking(
                            db,
                            dialog_id=dialog_id,
                            master_name=master_name,
                            service_name=service_name,
                            booking_datetime=booking_dt,
                            client_name=client_name,
                            client_phone=client_phone,
                        )
                        if err:
                            result = {"error": err}
                        else:
                            assigned_master = await db.get(Staff, booking.staff_id)
                            result = {
                                "status": "ok",
                                "booking_id": booking.id,
                                "booking_datetime": booking.booking_datetime.strftime("%Y-%m-%d %H:%M"),
                                "master_name": assigned_master.name,
                            }

            elif name == "cancel_booking":
                try:
                    booking_id = _optional_int(args, "booking_id")
                except ValueError as exc:
                    result = {"error": str(exc)}
                else:
                    booking, err = await booking_service.cancel_booking(
                        db, dialog_id=dialog_id, booking_id=booking_id
                    )
                    if booking is None:
                        result = {"error": err}
                    elif err == "already_cancelled":
                        result = {"status": "already_cancelled", "booking_id": booking.id}
                    else:
                        result = {"status": "cancelled", "booking_id": booking.id}

            else:
                result = {"error": f"unknown_tool: {name}"}
        except Exception as exc:
            # Last-resort safety net: a tool must never raise back into the
            # generate_reply loop — an unhandled error here would kill the
            # whole pipeline turn instead of letting the model react to it.
            print(f"[MAIN_AI] Tool '{name}' raised unexpectedly: {exc}", flush=True)
            result = {"error": "internal_error"}

        print(f"[MAIN_AI] Tool result: {name} -> {result}", flush=True)
        return result

    async def generate_reply(self, db: AsyncSession, dialog_id: int, combined_text: str) -> str:
        print(f"[MAIN_AI] Calling model={settings.MAIN_AI_MODEL}...", flush=True)

        today = date.today()
        knowledge_context = await get_knowledge_context(db)
        history = await self._load_history(db, dialog_id)
        if not history:
            # Defensive fallback in case a caller didn't save the current
            # message before calling here — see _load_history's docstring.
            history = [{"role": "user", "content": combined_text}]

        system_prompt = f"{BASE_SYSTEM_PROMPT}\n\nСегодня {today.isoformat()} ({today.strftime('%A')})."
        if len(history) <= 1:
            system_prompt += FIRST_MESSAGE_INSTRUCTION
        system_prompt += knowledge_context

        messages: list[dict] = [{"role": "system", "content": system_prompt}, *history]

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = await self._client.chat.completions.create(
                    model=settings.MAIN_AI_MODEL,
                    max_tokens=1024,
                    tools=TOOLS,
                    messages=messages,
                )
                message = response.choices[0].message

                if not message.tool_calls:
                    reply_text = message.content or FALLBACK_REPLY
                    print(f"[MAIN_AI] Reply: {reply_text}", flush=True)
                    return reply_text

                messages.append(message.model_dump(exclude_none=True))
                for tool_call in message.tool_calls:
                    tool_result = await self._execute_tool(
                        db, dialog_id, tool_call.function.name, tool_call.function.arguments, history
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )

            print("[MAIN_AI] Exceeded MAX_TOOL_ROUNDS without a final reply — falling back", flush=True)
            return FALLBACK_REPLY
        except openai.APIError as exc:
            print(f"[MAIN_AI] API Error: {exc}", flush=True)
            return FALLBACK_REPLY
        except Exception as exc:
            print(f"[MAIN_AI] Unexpected error: {exc}", flush=True)
            return FALLBACK_REPLY


main_ai_service = MainAIService()
