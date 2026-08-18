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
