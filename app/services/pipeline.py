from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dialog, DialogStatus
from app.services.dialog_summary_service import get_latest_summary_text
from app.services.gemini_service import gemini_service
from app.services.guardrail_service import guardrail_service
from app.services.main_ai_service import main_ai_service
from app.text_utils import sanitize_text

STOP_BOT_REPLY = (
    "Приносим извинения за доставленные неудобства! Я передал(а) ваше обращение "
    "управляющему, он свяжется с вами в ближайшее время для решения вопроса."
)

HOT_LEAD_REPLY = (
    "Спасибо за обращение! Я передала вашу заявку на запись администратору. "
    "В ближайшее время мы подтвердим бронирование и свяжемся с вами!"
)

GEMINI_STOP_BOT_REPLY = (
    "Жасалган ыңгайсыздык үчүн кечирим сурайбыз! Сиздин кайрылууңузду жетекчиге "
    "жеткирдим, ал маселени чечүү үчүн жакында сиз менен байланышат."
)


async def handle_message(db: AsyncSession, dialog_id: int, combined_text: str) -> str | None:
    """Runs the guardrail, then routes to Main AI (ru) or Gemini (ky).

    Returns the bot's reply text, or None if the dialog was closed and the
    chain should stop without generating a reply. Every branch that produces
    a reply logs it via "[PIPELINE] Reply: ..." right before returning, so
    the sent text is always visible in the console regardless of which path
    was taken.
    """
    print(f"[PIPELINE] Starting pipeline for dialog_id={dialog_id}", flush=True)

    combined_text = sanitize_text(combined_text)

    dialog = await db.get(Dialog, dialog_id)

    # Passing the dialog's current language lets the guardrail keep it
    # ("sticky") for short/ambiguous messages (a lone name, phone number,
    # etc.) that carry no real linguistic signal on their own — otherwise
    # a Kyrgyz-sounding name alone can flip the whole dialog to Gemini.
    dialog_summary = await get_latest_summary_text(db, dialog_id)
    guardrail = await guardrail_service.check(
        combined_text, current_language=dialog.language, dialog_summary=dialog_summary
    )
    dialog.language = guardrail.detected_language

    if guardrail.is_stop_bot:
        dialog.status = DialogStatus.escalated
        dialog.escalation_reason = guardrail.reason or "stop_bot"
        print(f"[PIPELINE] Dialog {dialog_id} escalated (stop_bot): {dialog.escalation_reason}", flush=True)
        print(f"[PIPELINE] Reply: {STOP_BOT_REPLY}", flush=True)
        return STOP_BOT_REPLY

    if guardrail.is_hot_lead:
        dialog.status = DialogStatus.escalated
        dialog.escalation_reason = guardrail.reason or "hot_lead"
        print(f"[PIPELINE] Dialog {dialog_id} escalated (hot_lead): {dialog.escalation_reason}", flush=True)

        # Main AI can actually search slots and create the booking via
        # function calling, so let it try instead of just acknowledging.
        # Gemini has no booking tools yet, so ky hot leads still get the
        # static acknowledgment below.
        if guardrail.detected_language == "ru":
            print(f"[PIPELINE] Hot lead routed to Main AI (ru) to attempt booking", flush=True)
            reply_text = await main_ai_service.generate_reply(db, dialog_id, combined_text)
            print(f"[PIPELINE] Reply: {reply_text}", flush=True)
            return reply_text

        print(f"[PIPELINE] Reply: {HOT_LEAD_REPLY}", flush=True)
        return HOT_LEAD_REPLY

    if guardrail.is_refusal:
        dialog.status = DialogStatus.closed
        dialog.closed_reason = guardrail.reason or "client_refusal"
        print(f"[PIPELINE] Dialog {dialog_id} closed: refusal", flush=True)
        return None

    if guardrail.detected_language == "ky":
        print(f"[PIPELINE] Routing dialog {dialog_id} to Gemini (ky)", flush=True)
        gemini_result = await gemini_service.generate_reply(db, combined_text)
        if gemini_result.is_stop_bot:
            dialog.status = DialogStatus.escalated
            dialog.escalation_reason = gemini_result.stop_reason or "gemini_flagged_topic"
            print(
                f"[PIPELINE] Dialog {dialog_id} escalated by Gemini: {dialog.escalation_reason}",
                flush=True,
            )
            print(f"[PIPELINE] Reply: {GEMINI_STOP_BOT_REPLY}", flush=True)
            return GEMINI_STOP_BOT_REPLY
        print(f"[PIPELINE] Reply: {gemini_result.text}", flush=True)
        return gemini_result.text

    print(f"[PIPELINE] Routing dialog {dialog_id} to Main AI (ru)", flush=True)
    reply_text = await main_ai_service.generate_reply(db, dialog_id, combined_text)
    print(f"[PIPELINE] Reply: {reply_text}", flush=True)
    return reply_text
