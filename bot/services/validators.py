import re
from datetime import date, time, datetime

# Разрешаем буквы латиницы/кириллицы, пробел, дефис, точку. 2–80 символов.
CITY_RE = re.compile(r"^[A-Za-zÀ-ÿ\u0400-\u04FF\s\.\-]{2,80}$")

# Имя: только буквы и дефис, 1–50 символов
NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ\u0400-\u04FF\-]{1,50}$")

def validate_name(s: str) -> str:
    s = (s or "").strip()
    if not NAME_RE.fullmatch(s):
        raise ValueError("Пожалуйста, введи корректное имя (только буквы и дефис, до 50 символов).")
    # Нормализуем: первая буква заглавная, остальное как есть
    return s[:50]

def validate_city(s: str) -> str:
    s = (s or "").strip()
    if not CITY_RE.fullmatch(s):
        raise ValueError("Город должен содержать только буквы, пробелы, точку или дефис (2–80 символов).")
    return s[:80]

def parse_date_ddmmyyyy(s: str) -> date:
    s = (s or "").strip()
    try:
        d = datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        raise ValueError("Неверный формат. Введи дату как ДД.ММ.ГГГГ, например: 25.12.1990.")
    # Простейшая здравость: не в будущем и не слишком старая дата
    if d > date.today():
        raise ValueError("Дата из будущего не принимается 🙂")
    if d.year < 1900:
        raise ValueError("Укажи год не раньше 1900.")
    return d

def parse_time_hhmm(s: str) -> time:
    s = (s or "").strip()
    try:
        t = datetime.strptime(s, "%H:%M").time()
    except Exception:
        raise ValueError("Введи время в формате ЧЧ:ММ, например: 09:15.")
    return t
