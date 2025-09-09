# bot/utils/spinner.py
import asyncio
from contextlib import asynccontextmanager, suppress
from aiogram.utils.formatting import CustomEmoji
from aiogram.enums import ChatAction

CRYSTAL_ORB_ID = "5361837567463399422"  # твой ID 🔮

@asynccontextmanager
async def orb_spinner(bot, chat_id: int, caption: str | None = None):
    """
    Пытается отправить custom emoji 🔮 и лупит его (клиент сам зацикливает).
    Если Telegram вдруг не даст отправить кастом-эмодзи — падаем в fallback: чат-экшен.
    """
    msg = None
    typing_task = None
    try:
        try:
            orb = CustomEmoji("🔮", custom_emoji_id=CRYSTAL_ORB_ID)
            kwargs = orb.as_kwargs()  # вернёт {"text": "🔮", "entities":[...]}
            if caption:
                kwargs["text"] += f"\n{caption}"
            msg = await bot.send_message(chat_id, disable_notification=True, **kwargs)
        except Exception:
            # Fallback: «бот печатает…» каждые ~5 сек
            async def pump():
                while True:
                    with suppress(Exception):
                        await bot.send_chat_action(chat_id, ChatAction.TYPING)
                    await asyncio.sleep(4.5)
            typing_task = asyncio.create_task(pump())

        yield msg
    finally:
        if typing_task:
            typing_task.cancel()
            with suppress(asyncio.CancelledError):
                await typing_task
        if msg:
            with suppress(Exception):
                await bot.delete_message(chat_id, msg.message_id)
