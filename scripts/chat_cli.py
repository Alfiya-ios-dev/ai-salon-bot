"""Interactive terminal chat for manually testing the bot pipeline.

Run from the project root (see README note below) and type messages as if
you were the client. Every message goes through the exact same
app.services.pipeline.handle_message() used by the real webhook, so
guardrail/tool-call/escalation logs print exactly as they would in
production — this script just adds the "Вы:"/"Бот:" prompts and a small
status summary around them.

Every launch of this script already starts a brand new dialog_id (a fresh
client_external_id is generated below) — restarting the process is always a
clean slate. To start a clean dialog *without* restarting the process
(e.g. to test several unrelated scenarios back to back in one terminal
session), type 'new' at the "Вы:" prompt.

Usage:
    python scripts/chat_cli.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Dialog, DialogStatus, Message, SenderType  # noqa: E402
from app.services import pipeline  # noqa: E402
from app.text_utils import sanitize_text  # noqa: E402

EXIT_WORDS = {"exit", "quit"}
NEW_DIALOG_WORDS = {"new", "новый", "/new"}


async def _create_test_dialog() -> tuple[int, str]:
    client_external_id = f"cli-test-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        dialog = Dialog(
            client_external_id=client_external_id,
            channel="cli",
            language="ru",
            status=DialogStatus.bot_active,
        )
        db.add(dialog)
        await db.commit()
        await db.refresh(dialog)
        return dialog.dialog_id, client_external_id


def _print_banner(dialog_id: int, client_external_id: str) -> None:
    print("=" * 70)
    print("Интерактивный тест бота салона красоты")
    print(f"dialog_id={dialog_id}  client_external_id={client_external_id!r}")
    print("Вводите сообщения клиента. 'exit'/'quit' — выход, 'new' — начать новый диалог.")
    print("=" * 70)


async def main() -> None:
    dialog_id, client_external_id = await _create_test_dialog()
    _print_banner(dialog_id, client_external_id)

    while True:
        try:
            user_input = await asyncio.to_thread(input, "Вы: ")
        except (EOFError, KeyboardInterrupt):
            print("\nЗавершение работы.")
            break

        text = sanitize_text(user_input).strip()
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            print("Завершение работы.")
            break
        if text.lower() in NEW_DIALOG_WORDS:
            dialog_id, client_external_id = await _create_test_dialog()
            _print_banner(dialog_id, client_external_id)
            continue

        async with AsyncSessionLocal() as db:
            db.add(
                Message(
                    message_id=f"cli-{uuid.uuid4()}",
                    dialog_id=dialog_id,
                    sender_type=SenderType.client,
                    text=text,
                )
            )
            await db.commit()

            print("-" * 70)
            reply = await pipeline.handle_message(db, dialog_id=dialog_id, combined_text=text)
            print("-" * 70)

            dialog = await db.get(Dialog, dialog_id)
            print(
                f"[CLI] status={dialog.status.value}  "
                f"escalation_reason={dialog.escalation_reason!r}  "
                f"closed_reason={dialog.closed_reason!r}"
            )

            if reply is not None:
                db.add(
                    Message(
                        message_id=f"cli-bot-{uuid.uuid4()}",
                        dialog_id=dialog_id,
                        sender_type=SenderType.bot,
                        text=reply,
                    )
                )
                await db.commit()
                print(f"Бот: {reply}")
            else:
                print("Бот: (ответа нет — диалог закрыт/эскалирован без реплики клиенту)")


if __name__ == "__main__":
    asyncio.run(main())
