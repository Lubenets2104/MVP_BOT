# bot/middlewares/input_guard.py
import re
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message

# мягкий набор «запрещённых» токенов: ссылки/код/инъекции
URL_RE   = re.compile(r'(https?://|www\.|t\.me/|@\w{2,})', re.I)
CODE_RE  = re.compile(r'(<\s*script\b|`{1,3}|</?code>|data:|base64,|-----BEGIN )', re.I)
INJ_RE   = re.compile(r'\b(ignore (previous|all)|disregard instructions|reveal .*prompt|system prompt|api key)\b', re.I)

# импортируем FSM-состояния, где ожидается текст
try:
    from states import Flow
    TEXT_STATES = {
        Flow.NAME.state,
        Flow.BIRTH_DATE.state,
        Flow.BIRTH_TIME.state,
        Flow.CITY.state,
    }
except Exception:
    TEXT_STATES = set()

# безопасное чтение значения из админки
async def _get_max_len(dbsvc) -> int:
    try:
        raw = await dbsvc.get_admin_value("max_input_length")
        return int(raw or 80)
    except Exception:
        return 80


class InputSanitizerMiddleware(BaseMiddleware):
    """
    Пропускаем только «чистый» текст в состояниях, где он ожидается.
    - Лимит длины из admin_settings.max_input_length (по умолчанию 80)
    - Запрет ссылок/кода/инъекций
    """
    def __init__(self):
        super().__init__()
        # ленивый импорт, чтобы не городить циклических зависимостей
        from services import db as dbsvc   # type: ignore
        self.dbsvc = dbsvc

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        # интересует только текст
        if not isinstance(event, Message) or not event.text:
            return await handler(event, data)

        # команды не трогаем
        if event.text.startswith("/"):
            return await handler(event, data)

        # проверяем состояние FSM
        st = None
        state = data.get("state")
        if state is not None:
            try:
                st = await state.get_state()
            except Exception:
                st = None

        if st not in TEXT_STATES:
            # вне «текстовых» шагов — пусть решает другой guard (из шага 2)
            return await handler(event, data)

        text = event.text.strip()

        # 1) лимит длины
        max_len = await _get_max_len(self.dbsvc)
        if len(text) > max_len:
            await event.answer(f"Слишком длинно. Пожалуйста, укоротите до {max_len} символов.")
            return

        # 2) запреты на ссылки/код/инъекции
        if URL_RE.search(text) or CODE_RE.search(text) or INJ_RE.search(text):
            # подсказка по контексту
            hint = "только имя" if st == Flow.NAME.state else \
                   "только дату формата ДД.ММ.ГГГГ" if st == Flow.BIRTH_DATE.state else \
                   "время формата ЧЧ:ММ" if st == Flow.BIRTH_TIME.state else \
                   "только название города" if st == Flow.CITY.state else "корректный ввод"
            await event.answer(f"Пожалуйста, укажите {hint} — без ссылок, кода и лишних символов.")
            return

        # ок — дальше отработают твои хендлеры (NAME/DATE/TIME/CITY с их регэкспами)
        return await handler(event, data)
