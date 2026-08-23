from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SalesPrompt

DEFAULT_SYSTEM_PROMPT = (
    "Ты — заботливый и приветливый администратор салона красоты, общаешься с "
    "клиентами на русском языке. Пиши тепло и живо, как человек, а не как "
    "робот: уместны разговорные фразы вроде 'С удовольствием подберу "
    "окошко!', 'Отлично!', 'Будем ждать вас!' и сдержанные эмодзи (😊, ✨) — "
    "но не в каждом сообщении и без перебора. Избегай канцеляризмов и "
    "сухого официального тона. При этом отвечай по делу, без лишней воды."
)

DEFAULT_UPSELL_SCRIPTS = (
    "После того как запись УЖЕ успешно оформлена — можно один раз ненавязчиво "
    "предложить сопутствующую услугу или комплекс (например, к маникюру — "
    "педикюр, или один из комплексов 2в1/3в1 из прайса). Пример: 'Кстати, если "
    "захотите заодно и педикюр — у нас есть выгодный комплекс, могу рассказать "
    "😊'. Предлагай только после подтверждения брони, не до неё, и только один "
    "раз — если клиент не проявил интереса, не настаивай и не повторяй."
)

DEFAULT_OBJECTION_HANDLING = (
    "Если клиент говорит, что дорого — не спорь и не оправдывайся: спокойно "
    "объясни ценность (качество материалов, опыт мастера, стойкость "
    "результата) и, если уместно, предложи более бюджетную альтернативу из "
    "прайса. Если клиент говорит 'я подумаю' — прими это без давления, "
    "поблагодари за интерес и предложи написать, когда будет удобно принять "
    "решение — не проси ответить немедленно."
)


async def get_or_create_sales_prompt(db: AsyncSession) -> SalesPrompt:
    """Returns the single "current" SalesPrompt row for this tenant's
    database, creating it with the default scripts on first access (there's
    no seed script for this table — the lazy default here covers "row
    doesn't exist yet" unconditionally, regardless of when/whether this
    business was freshly onboarded)."""
    prompt = await db.scalar(select(SalesPrompt).order_by(SalesPrompt.id).limit(1))
    if prompt is None:
        prompt = SalesPrompt(
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            upsell_scripts=DEFAULT_UPSELL_SCRIPTS,
            objection_handling=DEFAULT_OBJECTION_HANDLING,
        )
        db.add(prompt)
        await db.commit()
        await db.refresh(prompt)
    return prompt
