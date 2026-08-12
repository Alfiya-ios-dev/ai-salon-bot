from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dialog, DialogStatus
from app.services.gemini_service import gemini_service
from app.services.guardrail_service import guardrail_service
from app.services.main_ai_service import main_ai_service


async def handle_message(db: AsyncSession, dialog_id: int, combined_text: str) -> str | None:
    """Runs the guardrail, then routes to Main AI (ru) or Gemini (ky).

    Returns the bot's reply text, or None if the dialog was escalated/closed
    and the chain should stop without generating a reply.
    """
    print(f"[PIPELINE] Starting pipeline for dialog_id={dialog_id}", flush=True)

    guardrail = await guardrail_service.check(combined_text)

    dialog = await db.get(Dialog, dialog_id)

    if guardrail.is_stop_bot or guardrail.is_hot_lead:
        dialog.status = DialogStatus.escalated
        dialog.escalation_reason = guardrail.reason or (
            "hot_lead" if guardrail.is_hot_lead else "stop_bot"
        )
        print(f"[PIPELINE] Dialog {dialog_id} escalated: {dialog.escalation_reason}", flush=True)
        return None

    if guardrail.is_refusal:
        dialog.status = DialogStatus.closed
        dialog.closed_reason = guardrail.reason or "client_refusal"
        print(f"[PIPELINE] Dialog {dialog_id} closed: refusal", flush=True)
        return None

    if guardrail.detected_language == "ky":
        print(f"[PIPELINE] Routing dialog {dialog_id} to Gemini (ky)", flush=True)
        gemini_result = await gemini_service.generate_reply(combined_text)
        if gemini_result.is_stop_bot:
            dialog.status = DialogStatus.escalated
            dialog.escalation_reason = gemini_result.stop_reason or "gemini_flagged_topic"
            print(
                f"[PIPELINE] Dialog {dialog_id} escalated by Gemini: {dialog.escalation_reason}",
                flush=True,
            )
            return None
        return gemini_result.text

    print(f"[PIPELINE] Routing dialog {dialog_id} to Main AI (ru)", flush=True)
    return await main_ai_service.generate_reply(combined_text)
