# bot/filters/free_text_guard.py
import asyncio
from typing import Any, Dict, Optional, Set
from aiogram.filters import BaseFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

class FreeTextGuard(BaseFilter):
    """
    Блокирует произвольный текст вне ожидаемых шагов.
    - Видит текущее FSM-состояние
    - Разрешает текст на указанных шагах (по суффиксу)
    - При блокировке удаляет сообщение пользователя и своё предупреждение (ephemeral)
    """
    def __init__(
        self,
        allow_suffixes: Optional[Set[str]] = None,
        ephemeral_seconds: float = 2.5
    ):
        self.allow_suffixes = allow_suffixes or {"NAME", "DATE", "TIME", "CITY", "GENDER", "SYSTEM"}
        self.ephemeral_seconds = ephemeral_seconds

    async def __call__(self, message: Message, state: FSMContext, **data: Dict[str, Any]) -> bool:
        # пропускаем команды и не-текст (кнопки/инлайн-колбэки сюда не попадают)
        if not message.text or message.text.startswith("/"):
            return True

        current_state = await state.get_state()

        # если на ожидаемом шаге — пропускаем
        if current_state and any(current_state.endswith(suf) for suf in self.allow_suffixes):
            return True

        # иначе — блокируем, показываем предупреждение и чистим следы
        warn = await message.answer("Используй, пожалуйста, кнопки ниже.")
        # пытаемся удалить текст пользователя (в приватном чате боту можно)
        try:
            await message.delete()
        except Exception:
            pass

        # удалим и предупреждение через N секунд
        if warn and self.ephemeral_seconds > 0:
            async def _del():
                try:
                    await asyncio.sleep(self.ephemeral_seconds)
                    await warn.delete()
                except Exception:
                    pass
            asyncio.create_task(_del())

        return False
