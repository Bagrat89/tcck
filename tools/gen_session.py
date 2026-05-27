#!/usr/bin/env python3
"""
tools/gen_session.py — генерация StringSession для Render/облака.

Запускать ОДИН РАЗ локально:
    cd tcck-map
    python tools/gen_session.py

Результат вставить в .env как TELEGRAM_STRING_SESSION=...
"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


async def main():
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        sys.exit("Установи telethon: pip install telethon")

    print("\n" + "="*50)
    print("  Telethon StringSession Generator")
    print("="*50 + "\n")

    api_id   = input("TELEGRAM_API_ID   : ").strip()
    api_hash = input("TELEGRAM_API_HASH  : ").strip()
    phone    = input("Phone (+380...)    : ").strip()

    try:
        api_id = int(api_id)
    except ValueError:
        sys.exit("API_ID должен быть числом")

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start(phone=phone)
        if not await client.is_user_authorized():
            sys.exit("Авторизация не удалась")
        me = await client.get_me()
        ss = client.session.save()

    print(f"\n✓ Авторизован как: {me.first_name} (id={me.id})")
    print("\nВставь в .env:\n")
    print(f"TELEGRAM_STRING_SESSION={ss}")
    print("\n⚠  Храни в секрете — даёт полный доступ к аккаунту!")
    print("⚠  Никогда не коммить в git!\n")


if __name__ == "__main__":
    asyncio.run(main())
