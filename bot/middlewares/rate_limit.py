# bot/middlewares/rate_limit.py
import time
import asyncio
from typing import Callable, Awaitable, Dict, Any
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, per_seconds: float = 2.0, ephemeral_seconds: float = 2.0):
        super().__init__()
        self.per_seconds = per_seconds
        self.ephemeral_seconds = ephemeral_seconds
        self._last: Dict[int, float] = {}

    async def __call__(self, handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]], event: Message, data: Dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        uid = event.from_user.id if event.from_user else 0
        now = time.monotonic()
        last = self._last.get(uid, 0.0)
        if now - last < self.per_seconds:
            warn = await event.answer("Подожди секунду и используй кнопки, пожалуйста 🙂")
            try:
                await event.delete()
            except Exception:
                pass
            if warn and self.ephemeral_seconds > 0:
                async def _del():
                    try:
                        await asyncio.sleep(self.ephemeral_seconds)
                        await warn.delete()
                    except Exception:
                        pass
                asyncio.create_task(_del())
            return
        self._last[uid] = now
        return await handler(event, data)


class CallbackRateLimitMiddleware(BaseMiddleware):
    """Мягкий лимит для нажатий на inline-кнопки."""
    def __init__(self, per_seconds: float = 0.7):
        super().__init__()
        self.per_seconds = per_seconds
        self._last: Dict[int, float] = {}

    async def __call__(self, handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]], event: CallbackQuery, data: Dict[str, Any]) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        uid = event.from_user.id if event.from_user else 0
        now = time.monotonic()
        last = self._last.get(uid, 0.0)
        if now - last < self.per_seconds:
            # просто короткий toast, без алертов и без шумных сообщений
            try:
                await event.answer("Секундочку…", show_alert=False)
            except Exception:
                pass
            return
        self._last[uid] = now
        return await handler(event, data)
