"""Interactive terminal chat for manually testing the bot pipeline.

Run from the project root and type messages as if you were the client.
Every message goes through the exact same app.services.pipeline.handle_message()
used by the real webhook, so guardrail/tool-call/escalation logs print
exactly as they would in production — this script just adds the "Вы:"/"Бот:"
prompts and a small status summary around them.

Under database-per-tenant, every business has its own isolated database, so
one must be selected before chatting:
    --tenant-id 3     use an existing tenant (registry id) by id
    --register        register a brand-new business (prompts for business
                       name, email, password, WhatsApp number) and use it
With neither flag, existing tenants are listed and you're prompted to pick
one (or register a new one).

Every launch of this script already starts a brand new dialog_id (a fresh
client_external_id is generated below) — restarting the process is always a
clean slate. To start a clean dialog *without* restarting the process
(e.g. to test several unrelated scenarios back to back in one terminal
session), type 'new' at the "Вы:" prompt.

Usage:
    python scripts/chat_cli.py --tenant-id 3
    python scripts/chat_cli.py --register
    python scripts/chat_cli.py
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app import registry_models  # noqa: E402,F401  (registers Tenant on Base.metadata)
from app.models import Dialog, DialogStatus, Message, SenderType  # noqa: E402
from app.registry_models import Tenant  # noqa: E402
from app.services import pipeline  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402
from app.tenant_db import get_tenant_sessionmaker, provision_tenant_database  # noqa: E402
from app.text_utils import sanitize_text  # noqa: E402

EXIT_WORDS = {"exit", "quit"}
NEW_DIALOG_WORDS = {"new", "новый", "/new"}


async def _register_tenant() -> Tenant:
    business_name = input("Название бизнеса: ").strip()
    email = input("Email для входа в админку: ").strip()
    password = input("Пароль (мин. 8 символов): ").strip()
    business_phone_number = input("Номер WhatsApp бизнеса: ").strip()

    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            business_name=business_name,
            email=email,
            password_hash=hash_password(password),
            business_phone_number=business_phone_number,
            database_name="pending",
        )
        db.add(tenant)
        await db.flush()
        tenant.database_name = f"tenant_{tenant.id}_db"
        await provision_tenant_database(tenant.database_name)
        await db.commit()
        await db.refresh(tenant)
        print(f"Зарегистрирован новый тенант id={tenant.id} ({business_name!r}), database={tenant.database_name}.")
        return tenant


async def _resolve_tenant(args: argparse.Namespace) -> Tenant:
    if args.register:
        return await _register_tenant()

    if args.tenant_id is not None:
        async with AsyncSessionLocal() as db:
            tenant = await db.get(Tenant, args.tenant_id)
        if tenant is None:
            print(f"Тенант с id={args.tenant_id} не найден.")
            sys.exit(1)
        return tenant

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().all()

    if not tenants:
        print("В реестре нет ни одного тенанта. Регистрируем новый.")
        return await _register_tenant()

    print("Существующие тенанты:")
    for tenant in tenants:
        print(f"  {tenant.id}: {tenant.business_name} ({tenant.business_phone_number})")
    choice = input("Введите tenant_id для использования (или 'new' + Enter, чтобы зарегистрировать новый): ").strip()
    if choice.lower() == "new":
        return await _register_tenant()

    try:
        tenant_id = int(choice)
    except ValueError:
        print("Некорректный ввод. Отменено.")
        sys.exit(1)
    tenant = next((t for t in tenants if t.id == tenant_id), None)
    if tenant is None:
        print(f"Тенант с id={tenant_id} не найден. Отменено.")
        sys.exit(1)
    return tenant


async def _create_test_dialog(sessionmaker) -> tuple[int, str]:
    client_external_id = f"cli-test-{uuid.uuid4().hex[:8]}"
    async with sessionmaker() as db:
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


def _print_banner(tenant: Tenant, dialog_id: int, client_external_id: str) -> None:
    print("=" * 70)
    print("Интерактивный тест бота салона красоты")
    print(
        f"tenant_id={tenant.id}  business={tenant.business_name!r}  "
        f"database={tenant.database_name}  dialog_id={dialog_id}  "
        f"client_external_id={client_external_id!r}"
    )
    print("Вводите сообщения клиента. 'exit'/'quit' — выход, 'new' — начать новый диалог.")
    print("=" * 70)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=int, default=None, help="Use an existing tenant (registry id) by id")
    parser.add_argument("--register", action="store_true", help="Register a brand-new business and use it")
    args = parser.parse_args()

    # Registry schema must exist before we can look up/insert tenants.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tenant = await _resolve_tenant(args)
    sessionmaker = get_tenant_sessionmaker(tenant.database_name)

    dialog_id, client_external_id = await _create_test_dialog(sessionmaker)
    _print_banner(tenant, dialog_id, client_external_id)

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
            dialog_id, client_external_id = await _create_test_dialog(sessionmaker)
            _print_banner(tenant, dialog_id, client_external_id)
            continue

        db: AsyncSession
        async with sessionmaker() as db:
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
