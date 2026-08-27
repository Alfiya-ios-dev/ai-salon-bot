from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessInfo, RagDocument, Service

KNOWLEDGE_HEADER = (
    "\n\n---\n"
    "База знаний салона (информация о салоне, прайс-лист, правила записи). "
    "Отвечай на вопросы о ценах, услугах и правилах СТРОГО на основе этой "
    "информации. Если ответа в базе знаний нет — так и скажи клиенту, не "
    "придумывай:\n\n"
)

# Simple keyword gate for conditional RAG: the client's current message is
# checked against these stems (substring match) before the knowledge base
# is pulled into the prompt at all. Plain "привет"/"спасибо" messages match
# nothing and cost 0 RAG tokens; anything about prices/services/booking
# does.
PRICE_KEYWORDS = ["цена", "стоимость", "услуга", "сколько", "мастер", "запис", "длит", "прайс", "процедур"]

# No tokenizer dependency for this — ~4 chars/token is a standard rough
# estimate, good enough for a hard token-budget cap on RAG content.
_CHARS_PER_TOKEN = 4
RAG_TOKEN_LIMIT = 1200
_RAG_CHAR_LIMIT = RAG_TOKEN_LIMIT * _CHARS_PER_TOKEN

BUSINESS_INFO_LABELS = {
    "name": "Название салона",
    "address": "Адрес",
    "working_hours": "Часы работы",
    "cancellation_policy": "Правила отмены записи",
}


async def _business_info_section(db: AsyncSession) -> str:
    rows = (await db.execute(select(BusinessInfo))).scalars().all()
    if not rows:
        return ""
    lines = [f"{BUSINESS_INFO_LABELS.get(row.key, row.key)}: {row.value}" for row in rows]
    return "### Информация о салоне\n" + "\n".join(lines)


async def _price_list_section(db: AsyncSession) -> str:
    """Built live from the Service table (not a hand-typed blob), so the
    price list the bot quotes can never drift out of sync with the real
    price list an admin panel would edit.
    """
    services = (await db.execute(select(Service).order_by(Service.category, Service.name))).scalars().all()
    if not services:
        return ""

    by_category: dict[str, list[Service]] = {}
    for service in services:
        by_category.setdefault(service.category or "Услуги", []).append(service)

    blocks = []
    for category, items in by_category.items():
        lines = [f"- {s.name} — {s.price} сом, {s.duration_minutes} мин" for s in items]
        blocks.append(f"**{category}:**\n" + "\n".join(lines))

    return "### Прайс-лист\n" + "\n\n".join(blocks)


async def get_knowledge_context(db: AsyncSession) -> str:
    """Loads business info, the live price list, and any freeform knowledge
    documents, formatted as a block to append to an AI system prompt. The
    salon's knowledge base is small, so it's all stuffed into context
    rather than run through embeddings/vector search.

    Returns "" if there's nothing to show yet, so callers can unconditionally
    append the result to their system prompt.
    """
    sections = []

    business_info = await _business_info_section(db)
    if business_info:
        sections.append(business_info)

    price_list = await _price_list_section(db)
    if price_list:
        sections.append(price_list)

    documents = (await db.execute(select(RagDocument).order_by(RagDocument.id))).scalars().all()
    sections.extend(f"### {doc.title}\n{doc.content}" for doc in documents)

    if not sections:
        return ""
    return KNOWLEDGE_HEADER + "\n\n".join(sections)


def _mentions_price_or_service(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in PRICE_KEYWORDS)


async def get_relevant_knowledge_context(db: AsyncSession, client_message: str) -> str:
    """Conditional, capped version of get_knowledge_context for the reply
    models: only pulls the knowledge base into the prompt when the client's
    current message actually looks like a price/service/booking question
    (see PRICE_KEYWORDS) — anything else (a plain "привет", "спасибо", "ок")
    gets 0 RAG tokens.

    When it IS relevant: business info + the live price list are always
    included (that's what a "прайс" question needs), freeform rag_documents
    are included only if their own text also matches PRICE_KEYWORDS, and the
    whole block is capped at RAG_TOKEN_LIMIT tokens so a large knowledge
    base can't blow up the prompt.
    """
    if not _mentions_price_or_service(client_message):
        return ""

    sections = []

    business_info = await _business_info_section(db)
    if business_info:
        sections.append(business_info)

    price_list = await _price_list_section(db)
    if price_list:
        sections.append(price_list)

    documents = (await db.execute(select(RagDocument).order_by(RagDocument.id))).scalars().all()
    for doc in documents:
        if _mentions_price_or_service(f"{doc.title} {doc.content}"):
            sections.append(f"### {doc.title}\n{doc.content}")

    if not sections:
        return ""

    context = KNOWLEDGE_HEADER + "\n\n".join(sections)
    if len(context) > _RAG_CHAR_LIMIT:
        context = context[:_RAG_CHAR_LIMIT] + "\n…(сокращено)"
    return context
