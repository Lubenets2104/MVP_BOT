from aiogram.utils.keyboard import InlineKeyboardBuilder

def start_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Начать", callback_data="nav:begin")
    return kb.as_markup()

def gender_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Мужской ♂️", callback_data="gender:male")
    kb.button(text="Женский ♀️", callback_data="gender:female")
    kb.button(text="🔙 Назад", callback_data="nav:back")
    kb.adjust(2, 1)
    return kb.as_markup()

def system_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Западная", callback_data="system:western")
    kb.button(text="Ведическая", callback_data="system:vedic")
    kb.button(text="БаЦзы", callback_data="system:bazi")
    kb.button(text="🔙 Назад", callback_data="nav:back")
    kb.adjust(2, 1, 1)
    return kb.as_markup()

def time_known_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Знаю", callback_data="time:known")
    kb.button(text="Не знаю", callback_data="time:unknown")
    kb.button(text="🔙 Назад", callback_data="nav:back")
    kb.adjust(2, 1)
    return kb.as_markup()

def main_menu_kb(locked: dict[str, bool] | None = None, show_year: bool = False):
    if locked is None:
        locked = {}
    kb = InlineKeyboardBuilder()
    items = [
        ("🔮 Какая моя миссия? 🔮", "menu:mission"),
        ("💼 Топ-10 бизнесов 💼", "menu:business"),
        ("❤️ Что с личной жизнью? ❤️", "menu:love"),
        ("📅 Годовой отчёт", "menu:year"),
        ("💰 Финансовый потенциал", "menu:finance"),
        ("🌍 Топ-5 стран для жизни", "menu:countries"),
        ("🌀 Кармический разбор", "menu:karma"),
        ("👥 Пригласи друга → бонус", "menu:invite"),
        ("⚙️ Ввести данные заново", "menu:reset"),
        ("⬅️ Назад", "menu:back"),
    ]

    for title, data in items:
        if locked.get(data, False):
            title = f"{title} 🔒"
        kb.button(text=title, callback_data=data)
    kb.adjust(1)
    return kb.as_markup()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="nav:back")
    return kb.as_markup()