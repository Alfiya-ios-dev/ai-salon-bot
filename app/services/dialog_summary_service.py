from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DialogSummary


async def get_latest_summary_text(db: AsyncSession, dialog_id: int) -> str:
    """Returns this dialog's most recent summary text, or "" if none exists.

    Nothing currently writes to DialogSummary, so today this is always "" —
    but Main AI and the guardrail already read from it instead of loading
    full conversation history, so a future summarization step can start
    populating this table without any further prompt-assembly changes.
    """
    summary = await db.scalar(
        select(DialogSummary)
        .where(DialogSummary.dialog_id == dialog_id)
        .order_by(DialogSummary.id.desc())
        .limit(1)
    )
    if summary is None:
        return ""
    data = summary.summary_data or {}
    if isinstance(data, str):
        return data
    return str(data.get("text", "") or "")
