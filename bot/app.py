import os
import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

router = Router()
POOL: asyncpg.Pool | None = None


async def get_greeting() -> str:
    global POOL
    try:
        assert POOL is not None
        row = await POOL.fetchrow(
            "SELECT value FROM settings WHERE key = 'greeting_text';"
        )
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logging.warning("Failed to fetch greeting_text: %s", e)
    return "Привет!"


@router.message(CommandStart())
async def on_start(message: Message):
    text = await get_greeting()
    await message.answer(text)


async def main() -> None:
    # <-- СНАЧАЛА читаем токен/DB URL
    token = os.environ["BOT_TOKEN"]
    db_url = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/appdb")

    # Пул к БД
    global POOL
    POOL = await asyncpg.create_pool(db_url, min_size=1, max_size=5)

    # Bot для aiogram 3.7+
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)

    try:
        await dp.start_polling(bot)
    finally:
        if POOL:
            await POOL.close()


if __name__ == "__main__":
    asyncio.run(main())
