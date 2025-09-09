# bot/app.py
import os
import asyncio
import logging
import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from services import db as dbsvc
from middlewares.rate_limit import RateLimitMiddleware, CallbackRateLimitMiddleware
from filters.free_text_guard import FreeTextGuard
from middlewares.input_guard import InputSanitizerMiddleware

logging.basicConfig(level=logging.INFO)

async def main() -> None:
    token = os.environ["BOT_TOKEN"]
    db_url = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/appdb")

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    dbsvc.set_pool(pool)

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # Анти-спам
    dp.message.middleware(RateLimitMiddleware(per_seconds=2.0))
    dp.callback_query.middleware(CallbackRateLimitMiddleware(per_seconds=0.7))

    # Санитайзер текстового ввода (в разрешённых шагах)
    dp.message.middleware(InputSanitizerMiddleware())

    # Глобальный guard: запрещаем свободный текст вне нужных шагов
    dp.message.filter(FreeTextGuard(
        allow_suffixes={"NAME", "GENDER", "SYSTEM", "DATE", "TIME", "CITY"}
    ))

    # Подключаем ВСЕ хэндлеры из handlers.py
    from handlers import router as flow_router
    dp.include_router(flow_router)

    try:
        await dp.start_polling(bot)
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
