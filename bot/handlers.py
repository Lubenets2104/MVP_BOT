import re
import asyncio
from datetime import date, time as dtime
from aiogram.exceptions import TelegramBadRequest
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, MessageEntity
from aiogram.enums import ChatAction, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.utils.formatting import CustomEmoji
import json, logging, os

from states import Flow
from keyboards import start_kb, gender_kb, system_kb, time_known_kb, back_kb, main_menu_kb
from services import db as dbsvc
from services import geocode as geosvc
from services import astro as astrosvc
from services import llm as llmsvc
from services.db import _require_pool
from scenarios import SCN  # ← оставляем пакетный импорт


router = Router()

SCN_PREFIX = "scn:"  # префикс для callback_data сценариев


# helpers

YEAR_ONLY_RE = re.compile(r"^\s*(?:19|20)\d{2}\s*$")

def _needs_year_regen(text: str | None) -> bool:
    """Нужно ли пересоздать годовой отчёт: пусто / только год / слишком коротко."""
    if text is None:
        return True
    s = text.strip()
    if not s:
        return True
    if YEAR_ONLY_RE.fullmatch(s):
        return True
    if len(s) < 40:  # слишком короткий текст для отчёта
        return True
    return False


async def _get_admin_value(key: str):
    try:
        return await dbsvc.get_admin_value(key)
    except Exception as e:
        logging.warning("get_admin_value(%s) failed: %s", key, e)
        return None


async def _scenarios_kb():
    """Клавиатура из включённых сценариев admin_scenarios."""
    items = await dbsvc.list_enabled_scenarios()  # [{scenario,title}]
    kb = InlineKeyboardBuilder()
    for s in items:
        kb.button(text=s["title"], callback_data=f"{SCN_PREFIX}{s['scenario']}")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(2, 2, 1)
    return kb.as_markup()

def _parse_ref_code(s: str | None) -> int | None:
    """
    Принимает аргументы диплинка (?start=...), поддерживает:
      - 'ref<tg_id>' (наш формат из меню)
      - просто число '<tg_id>'
    Возвращает tg_id инвайтера или None.
    """
    if not s:
        return None
    s = s.strip()
    if s.startswith("ref"):
        s = s[3:]
    s = s.strip()
    if s.isdigit():
        try:
            val = int(s)
            return val if val > 0 else None
        except Exception:
            return None
    return None

def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "t", "yes", "on")
    return False

def _as_json_obj(v) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


async def _locks_for_menu_from_message(m: Message) -> dict:
    """Получить замочки, имея только Message (после спиннера)."""
    class _Dummy:
        def __init__(self, bot, uid):
            self.bot = bot
            self.from_user = type("U", (), {"id": uid})()
    dummy = _Dummy(m.bot, m.from_user.id)
    return await _locks_for_menu(dummy)

def _fmt_bullets(items: list[str]) -> str:
    return "\n".join(f"• {str(x)}" for x in items[:10])

# ===== Helpers для главного экрана =====

async def _first_breakdown_text(session_id: int) -> str | None:
    """Текст «10 сильных / 10 слабых» из БД, если уже сгенерировано."""
    facts = await dbsvc.get_session_facts(session_id) or {}
    s_items = (facts.get("strengths") or {}).get("items") or []
    w_items = (facts.get("weaknesses") or {}).get("items") or []
    if not s_items and not w_items:
        return None

    lines = ["🔮 Твоя карта готова. Вот первый разбор:", ""]
    if s_items:
        lines.append("10 сильных сторон")
        lines += [f"• {x}" for x in s_items[:10]]
        lines.append("")
    if w_items:
        lines.append("10 слабых сторон")
        lines += [f"• {x}" for x in w_items[:10]]
    return "\n".join(lines)


async def _session_id_from_state_or_db(cb: CallbackQuery, state: FSMContext) -> int | None:
    """Берём session_id из FSM, иначе — ищем активную сессию в БД по tg_id."""
    data = await state.get_data()
    sid = data.get("session_id")
    if sid:
        return sid
    user_id = await dbsvc.get_user_id_by_tg(cb.from_user.id)
    if not user_id:
        return None
    return await dbsvc.get_active_session_id(user_id)


async def _render_main(cb: CallbackQuery, state: FSMContext):
    """Главный экран: если есть 10/10 — показываем их, иначе просто «Главное меню:»."""
    sid = await _session_id_from_state_or_db(cb, state)
    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)

    text = "Главное меню:"
    if sid:
        first = await _first_breakdown_text(sid)
        if first:
            text = first

    await safe_edit(cb, text, reply_markup=markup)



async def _spinner(bot, chat_id: int, stop: asyncio.Event):
    """Показываем «печатает…» каждые ~4 сек, пока stop не выставлен."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        await asyncio.sleep(4)

def _gate_keyboard(scenario: str, link: str | None):
    kb = InlineKeyboardBuilder()
    if link:
        kb.button(text="Перейти в канал", url=link)
    kb.button(text="✅ Я подписался", callback_data=f"gate:recheck:{scenario}")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(1, 1, 1)
    return kb.as_markup()

async def _gate_check_and_prompt(cb: CallbackQuery, scenario: str) -> bool:
    need, link = await _need_channel_gate(cb, scenario)
    if not need:
        return False
    txt = "Для доступа к этому разделу нужна подписка на канал."
    if link:
        txt += f"\nПерейди: {link}\nПосле этого нажми «✅ Я подписался»."
    else:
        txt += "\nПодпишись, затем нажми «✅ Я подписался»."
    await safe_edit(cb, txt, reply_markup=_gate_keyboard(scenario, link))
    return True

from typing import Any, Optional


async def _user_is_channel_member(cb: CallbackQuery, channel_id: str) -> bool:
    try:
        mem = await cb.bot.get_chat_member(chat_id=channel_id, user_id=cb.from_user.id)
        return mem.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def _need_channel_gate(cb: CallbackQuery, scenario: str) -> tuple[bool, str | None]:
    """
    True/ссылка если для сценария требуется подписка и её нет.
    Сценарий под замком, если bonus_sections[scenario] == 'channel'
    и включён enable_channel_gate.
    """
    enable_gate_raw = await dbsvc.get_admin_value("enable_channel_gate")
    enable_gate = _as_bool(enable_gate_raw)
    if not enable_gate:
        return (False, None)

    bonus_raw = await dbsvc.get_admin_value("bonus_sections")
    bonus = _as_json_obj(bonus_raw)
    if bonus.get(scenario) != "channel":
        return (False, None)

    # читаем id/handle и явный URL из админки
    channel_id = await dbsvc.get_admin_value("telegram_channel_id") or ""
    url_override = await dbsvc.get_admin_value("telegram_channel_url") or ""

    # приведение типов + трим пробелов/кавычек, на всякий
    if not isinstance(channel_id, str):
        channel_id = str(channel_id)
    if not isinstance(url_override, str):
        url_override = str(url_override)
    channel_id = channel_id.strip().strip('"').strip("'")
    url_override = url_override.strip().strip('"').strip("'")

    # уже подписан?
    if channel_id and await _user_is_channel_member(cb, channel_id):
        return (False, None)

    # собираем ссылку
    link = None
    if url_override:
        link = url_override
    elif channel_id.startswith("@"):
        link = f"https://t.me/{channel_id.lstrip('@')}"
    # для -100... без username линк не строим
    return (True, link)

# ---------- Реферальный гейт ----------

async def _referral_count(user_id: int) -> int:
    """Сколько уникальных приглашённых у пользователя (по таблице referrals)."""
    pool = _require_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS c FROM referrals WHERE inviter_user_id=$1",
        user_id,
    )
    return int(row["c"] if row and row["c"] is not None else 0)

async def _need_referral_gate(cb: CallbackQuery, scenario: str) -> tuple[bool, int, int]:
    """
    True/текущий/порог если для сценария нужен реф-гейт и он ещё не выполнен.
    Управляется:
      - admin_settings.enable_referrals (bool)
      - admin_settings.referral_bonus_threshold (int)
      - admin_settings.bonus_sections -> {"year": "referral", ...}
    """
    enabled = _as_bool(await _get_admin_value("enable_referrals"))
    if not enabled:
        return (False, 0, 0)

    bonus = _as_json_obj(await _get_admin_value("bonus_sections"))
    if bonus.get(scenario) != "referral":
        return (False, 0, 0)

    try:
        threshold = int(await _get_admin_value("referral_bonus_threshold") or 3)
    except Exception:
        threshold = 3

    # user_id в БД
    pool = _require_pool()
    row = await pool.fetchrow("SELECT id FROM users WHERE tg_id=$1", cb.from_user.id)
    if not row:
        return (True, 0, threshold)

    cnt = await _referral_count(row["id"])
    return (cnt < threshold, cnt, threshold)


async def _locks_for_menu(cb: CallbackQuery) -> dict:
    """Собирает замочки по bonus_sections из админки."""
    locked = {}
    bonus = _as_json_obj(await _get_admin_value("bonus_sections")) or {}

    for scen, mode in bonus.items():
        mode = (mode or "").strip().lower()
        if mode == "channel":
            need, _ = await _need_channel_gate(cb, scen)
            if need:
                locked[f"menu:{scen}"] = True
        elif mode in {"referral", "referrals"}:
            need, _, _ = await _need_referral_gate(cb, scen)
            if need:
                locked[f"menu:{scen}"] = True

    return locked

NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ\u0400-\u04FF\s.-]{1,50}$")
DATE_RE = re.compile(r"^([0-2][0-9]|3[01])\.(0[1-9]|1[0-2])\.(\d{4})$")
TIME_RE = re.compile(r"^(?:[01]?[0-9]|2[0-3]):[0-5][0-9]$")
CITY_RE = re.compile(r"^[A-Za-zÀ-ÿ\u0400-\u04FF\s.-]{2,80}$")


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, state: FSMContext):
    """
    Обрабатывает /start c дип-линком (?start=ref<tg_id>) и без него.
    - Создаёт (или находит) пользователя.
    - Если есть валидный реф-код и это не сам пользователь — записывает связь.
    - Показывает приветствие и кнопку "Начать".
    """
    tg = m.from_user
    invited_user_id = await dbsvc.ensure_user(tg_id=tg.id, user_name=tg.full_name or None)

    inviter_tg_id = _parse_ref_code(command.args if command else None)
    if inviter_tg_id and inviter_tg_id != tg.id:
        inviter_user_id = await dbsvc.get_user_id_by_tg(inviter_tg_id)
        if inviter_user_id:
            try:
                await dbsvc.register_referral(inviter_user_id, invited_user_id)
                logging.info(f"Referral linked: inviter={inviter_user_id} invited={invited_user_id}")
            except Exception as e:
                logging.warning(f"register_referral failed: {e}")

    greeting = await dbsvc.get_greeting_text()
    await m.answer(greeting, reply_markup=start_kb())
    await state.clear()



@router.callback_query(F.data == "nav:begin")
async def ask_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.NAME)
    await safe_edit(cb,
        "Привет! Я твой личный астро-помощник.\n\nКак к тебе обращаться? "
        "<i>(только буквы, до 50 символов)</i>"
    )


@router.message(Flow.NAME)
async def set_name(m: Message, state: FSMContext):
    name = (m.text or "").strip()
    if not NAME_RE.match(name):
        await m.reply("Пожалуйста, введи корректное имя (только буквы, до 50 символов).")
        return

    tg = m.from_user
    user_id = await dbsvc.ensure_user(tg_id=tg.id, user_name=tg.full_name or None)
    await dbsvc.set_user_name(user_id, name)

    await state.update_data(user_id=user_id, user_name=name)
    await state.set_state(Flow.GENDER)
    await m.answer(f"Принято, {name}! Теперь выбери пол:", reply_markup=gender_kb())


@router.callback_query(Flow.GENDER, F.data.startswith("gender:"))
async def set_gender(cb: CallbackQuery, state: FSMContext):
    gender = cb.data.split(":", 1)[1]
    data = await state.get_data()
    user_id = data.get("user_id")
    if not user_id:
        tg = cb.from_user
        user_id = await dbsvc.ensure_user(tg_id=tg.id, user_name=tg.full_name or None)
        await state.update_data(user_id=user_id)

    await dbsvc.set_user_gender(user_id, gender)
    await state.update_data(gender=gender)
    await state.set_state(Flow.SYSTEM)
    await safe_edit(cb, "Выберите систему астрологии:", reply_markup=system_kb())


@router.callback_query(Flow.GENDER, F.data == "nav:back")
async def back_to_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.NAME)
    await safe_edit(cb, "Окей, давай ещё раз. Введи имя:")



@router.callback_query(Flow.SYSTEM, F.data.startswith("system:"))
async def set_system(cb: CallbackQuery, state: FSMContext):
    system = cb.data.split(":", 1)[1]  # western|vedic|bazi
    data = await state.get_data()
    user_id = data.get("user_id")
    name = data.get("user_name", "друг")

    await dbsvc.deactivate_sessions(user_id)
    session_id = await dbsvc.create_session(user_id, system)
    await state.update_data(system=system, session_id=session_id)

    await state.set_state(Flow.BIRTH_DATE)
    title = {"western": "Западная", "vedic": "Ведическая", "bazi": "БаЦзы"}[system]
    await safe_edit(cb,
                    f"Отлично, {name}! Выбрана система: <b>{title}</b>.\n\n"
                    "Введите дату рождения в формате <b>ДД.ММ.ГГГГ</b> (например: <code>25.12.1990</code>).",
                    reply_markup=back_kb()
                    )


@router.callback_query(Flow.SYSTEM, F.data == "nav:back")
async def back_to_gender(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.GENDER)
    await safe_edit(cb, "Вернулись к выбору пола:", reply_markup=gender_kb())


@router.message(Flow.BIRTH_DATE)
async def set_birth_date(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    mm = DATE_RE.match(text)
    if not mm:
        await m.reply("Неверный формат. Введите в виде ДД.ММ.ГГГГ, например: 25.12.1990")
        return
    dd, mm_, yyyy = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
    try:
        d = date(yyyy, mm_, dd)
    except ValueError:
        await m.reply("Такой даты не существует. Проверь, пожалуйста.")
        return

    data = await state.get_data()
    session_id = data["session_id"]
    await dbsvc.set_birth_date(session_id, d)
    await state.update_data(birth_date=d)

    await state.set_state(Flow.TIME_KNOWN)
    await m.answer("Вы знаете точное время рождения?", reply_markup=time_known_kb())


@router.callback_query(Flow.BIRTH_DATE, F.data == "nav:back")
async def back_to_system(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.SYSTEM)
    await safe_edit(cb, "Выберите систему астрологии:", reply_markup=system_kb())


@router.callback_query(Flow.TIME_KNOWN, F.data == "time:known")
async def time_known_yes(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.BIRTH_TIME)
    await safe_edit(cb,
        "Введите время рождения в формате <b>ЧЧ:ММ</b> (например: <code>09:15</code>).",
        reply_markup=back_kb()
    )


@router.callback_query(Flow.TIME_KNOWN, F.data == "time:unknown")
async def time_known_no(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.CITY)
    await safe_edit(cb, "Введите место рождения (город/населённый пункт).", reply_markup=back_kb())


@router.callback_query(Flow.TIME_KNOWN, F.data == "nav:back")
async def back_to_date(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.BIRTH_DATE)
    await safe_edit(cb,
        "Введите дату рождения в формате <b>ДД.ММ.ГГГГ</b> (например: <code>25.12.1990</code>).",
        reply_markup=back_kb()
    )


@router.message(Flow.BIRTH_TIME)
async def set_birth_time(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    if not TIME_RE.match(t):
        await m.reply("Введите время в виде ЧЧ:ММ, например 09:15")
        return
    hh, mn = map(int, t.split(":"))
    t_obj = dtime(hour=hh, minute=mn)

    data = await state.get_data()
    await dbsvc.set_birth_time(data["session_id"], t_obj)
    await state.update_data(birth_time=t_obj)

    await state.set_state(Flow.CITY)
    await m.answer("Введите место рождения (город/населённый пункт).", reply_markup=back_kb())


@router.callback_query(Flow.BIRTH_TIME, F.data == "nav:back")
async def back_to_time_known(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.TIME_KNOWN)
    await safe_edit(cb, "Вы знаете точное время рождения?", reply_markup=time_known_kb())


@router.message(Flow.CITY)
async def set_city(m: Message, state: FSMContext):
    city = (m.text or "").strip()
    if not CITY_RE.match(city):
        await m.reply("Пожалуйста, укажи город (2–80 символов, буквы/пробел/точка/дефис).")
        return

    try:
        lat, lon, tz = await geosvc.geocode_city(city)
    except Exception:
        await m.reply("Не удалось определить. Попробуйте указать ближайший крупный город.")
        return


    data = await state.get_data()
    await dbsvc.set_location(data["session_id"], lat, lon, tz)
    await state.update_data(lat=lat, lon=lon, tz=tz)

    # Спиннер + сообщение-заглушка
    await state.set_state(Flow.CALC_SPINNER)
    msg = await m.answer("⚡️ Строю твою карту… подожди немного")
    spinner_msg = None
    stop = asyncio.Event()
    typing_task = asyncio.create_task(_spinner(m.bot, m.chat.id, stop))  # "печатает…"
    spinner_msg = await _send_spinner(m)  # единоразовый шар (<tg-emoji> или обычный)

    try:
        # Конвертация в UTC и расчёт карты
        bd = data["birth_date"]
        bt = data.get("birth_time")
        b = astrosvc.BirthInput(
            system=data["system"], birth_date=bd, birth_time=bt, lat=lat, lon=lon, tz=tz
        )
        dt_utc = astrosvc.to_utc_datetime(b)  # учитывает TZ и DST
        astro_json = astrosvc.compute_all(b, dt_utc)

        await dbsvc.save_raw_calc(data["session_id"], astro_json)
        await dbsvc.set_unknown_time(data["session_id"], bt is None)

        # Первичная генерация: 10 сильных / 10 слабых
        session_id = data["session_id"]
        strengths = await llmsvc.generate_list_or_mock(
            scenario="strengths", n=10, astro_json=astro_json, session_summary=None, session_id=session_id
        )
        weaknesses = await llmsvc.generate_list_or_mock(
            scenario="weaknesses", n=10, astro_json=astro_json, session_summary=None, session_id=session_id
        )
        await dbsvc.upsert_session_facts(session_id, strengths=strengths, weaknesses=weaknesses)

        # Версии фактов — делаем текущие активными
        await dbsvc.add_fact_version(session_id, "strengths", strengths, make_active=True)
        await dbsvc.add_fact_version(session_id, "weaknesses", weaknesses, make_active=True)

        # Короткая сводка по сессии (для LLM-контекста)
        name = data.get("user_name") or "пользователь"
        gender = data.get("gender") or "-"
        sys_title = {"western": "Западная", "vedic": "Ведическая", "bazi": "БаЦзы"}.get(data["system"], data["system"])
        city_str = f"lat={lat}, lon={lon}, tz={tz}"
        summary = (
                f"Имя: {name}; пол: {gender}; система: {sys_title}; дата: {bd}"
                + (f", время: {bt}" if bt else ", время: неизвестно")
                + f"; место: {city_str}. "
                  f"Сильные: {', '.join(strengths.get('items', [])[:3])}. "
                  f"Слабые: {', '.join(weaknesses.get('items', [])[:3])}."
        )
        await dbsvc.upsert_session_summary(session_id, summary)

        # Текст первого экрана: 10/10 + главное меню
        s_items = strengths.get("items", [])
        w_items = weaknesses.get("items", [])
        first_text = (
            "🔮 <b>Твоя карта готова. Вот первый разбор:</b>\n\n"
            "<b>10 сильных сторон</b>\n"
            f"{_fmt_bullets(s_items) if s_items else '—'}\n\n"
            "<b>10 слабых сторон</b>\n"
            f"{_fmt_bullets(w_items) if w_items else '—'}"
        )

        # Переходим в меню и рисуем клавиатуру
        await state.set_state(Flow.MENU)
        locks = await _locks_for_menu_from_message(m)
        markup = await _main_menu_markup_for_user(m.from_user.id, locks)
        try:
            if spinner_msg:
                await _safe_delete_message(m.bot, m.chat.id, spinner_msg.message_id)
                spinner_msg = None
        except Exception:
            pass

        await msg.edit_text(first_text, reply_markup=markup)

    except Exception as e:
        logging.exception("calc/generate failed: %s", e)
        await msg.edit_text("😕 Что-то пошло не так при расчёте карты. Попробуй ещё раз или укажи другой город.")
        await state.set_state(Flow.CITY)
    finally:
        stop.set()
        try:
            typing_task.cancel()
        except Exception:
            pass
        # подстраховка: если не удалили выше
        try:
            if spinner_msg:
                await _safe_delete_message(m.bot, m.chat.id, spinner_msg.message_id)
        except Exception:
            pass
        try:
            if spinner_msg:
                await _safe_delete_message(m.bot, m.chat.id, spinner_msg.message_id)
                spinner_msg = None
        except Exception:
            pass


@router.callback_query(Flow.CITY, F.data == "nav:back")
async def back_from_city(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # Если пользователь уже вводил точное время, возвращаем к нему,
    # иначе — к вопросу "знаете ли точное время?"
    if data.get("birth_time"):
        await state.set_state(Flow.BIRTH_TIME)
        await safe_edit(
            cb,
            "Введите время рождения в формате <b>ЧЧ:ММ</b> (например: <code>09:15</code>).",
            reply_markup=back_kb(),
        )
    else:
        await state.set_state(Flow.TIME_KNOWN)
        await safe_edit(cb, "Вы знаете точное время рождения?", reply_markup=time_known_kb())

# ---------- Helpers ----------

def _fmt_list(items: list[str]) -> str:
    lines = [f"{i+1}. {str(x)}" for i, x in enumerate(items)]
    return "\n".join(lines)

async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None):
    """
    Пытается отредактировать сообщение. Если текст/markup не изменились —
    мягко гасим крутилку, без исключения.
    """
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # попробуем всё-таки обновить только разметку (вдруг она изменилась)
            try:
                await cb.message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest:
                pass
            await cb.answer("Уже на экране 🙂", show_alert=False)
            return
        raise
    else:
        await cb.answer()

async def _safe_delete_message(bot, chat_id: int, message_id: int | None):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _show_year(tg_id: int) -> bool:
    """Годовой отчёт открыт? Зависит от админки и числа приглашённых."""
    enabled = _as_bool(await _get_admin_value("enable_referrals"))
    if not enabled:
        return False

    bonus = _as_json_obj(await _get_admin_value("bonus_sections"))
    mode = (bonus.get("year") or "referral").strip().lower()
    if mode not in {"referral", "referrals"}:
        return False

    try:
        thr = int(await _get_admin_value("referral_bonus_threshold") or 0)
    except Exception:
        thr = 0
    if thr <= 0:
        return False

    pool = _require_pool()
    # получаем внутренний user_id по tg_id
    row = await pool.fetchrow("SELECT id FROM users WHERE tg_id=$1", tg_id)
    if not row:
        return False

    have = await _referral_count(row["id"])   # считаем по inviter_user_id
    return have >= thr


async def _main_menu_markup_for_user(tg_id: int, locks: dict):
    # "Годовой отчёт" теперь всегда в меню; замок управляется locks["menu:year"]
    return main_menu_kb(locks)


async def _send_spinner(m: Message):
    """
    Если у бота есть купленный @username (Fragment/TON), отправим кастом-эмодзи через <tg-emoji>.
    Иначе пользователю отобразится обычный 🔮.
    """
    st_id = (os.getenv("SPINNER_STICKER_ID") or "5361837567463399422").strip().strip('"').strip("'")
    html = f"<tg-emoji emoji-id='{st_id}'>🔮</tg-emoji>"
    try:
        return await m.answer(html, parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        # на всякий случай явный фолбэк
        return await m.answer("🔮")


async def _spinner_anim_loop(bot, chat_id: int, stop: asyncio.Event):
    """
    Переотправляет «спиннер» каждые REFRESH сек, чтобы анимация начиналась заново.
    Если задан SPINNER_STICKER_ID — шлёт его; иначе шлёт '🔮'.
    Все предыдущие спиннер-сообщения удаляются, чтобы не мусорить чат.
    """
    refresh = float(os.getenv("SPINNER_REFRESH_SEC", "4.0"))
    sticker_id = os.getenv("SPINNER_STICKER_ID", "").strip() or None

    last_msg_id = None
    try:
        while not stop.is_set():
            # удалить предыдущий спиннер
            if last_msg_id:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
                except Exception:
                    pass
                last_msg_id = None

            # отправить новый спиннер
            try:
                if sticker_id:
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        **CustomEmoji("🔮", custom_emoji_id=sticker_id).as_kwargs()
                    )
                else:
                    msg = await bot.send_message(chat_id=chat_id, text="🔮")
                last_msg_id = msg.message_id
            except Exception as e:
                logging.warning(f"spinner loop send failed: {e}")
                last_msg_id = None

            # ждём до следующего перезапуска или выхода
            try:
                await asyncio.wait_for(stop.wait(), timeout=refresh)
            except asyncio.TimeoutError:
                continue
    finally:
        # подчистить спиннер в конце
        if last_msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
            except Exception:
                pass


async def _gen_and_store(session_id: int, code: str) -> tuple[dict, str]:
    """
    Универсально дергаем LLM-сценарий (через admin_scenarios), сохраняем в БД и
    возвращаем (исходный_json, превью_для_экрана).
    Логика сохранения:
      - mission / love -> в колонки mission/love (текст)
      - finance / karma / year -> в session_facts.extra[code] (текст)
      - strengths / weaknesses / business / countries -> списки ("items")
      - всё остальное -> session_facts.extra[code] = как есть (dict)
    """
    from services import llm as llmsvc

    pool = _require_pool()
    # дергаем LLM и получаем dict
    data = await llmsvc.run_scenario(session_id, code) or {}

    # вытащим краткое превью: либо первые пункты, либо короткий текст/сырой json
    def _preview_from_data(d: dict) -> str:
        if isinstance(d, dict):
            if isinstance(d.get("items"), list):
                return "\n".join(f"• {str(x)}" for x in d["items"][:10]) or "—"
            # распространённые поля-тексты
            for k in (code, "text", "mission", "love", "finance", "karma", "year"):
                if isinstance(d.get(k), str) and d[k].strip():
                    return d[k]
        # fallback — компактный json
        try:
            return json.dumps(d, ensure_ascii=False)[:1000]
        except Exception:
            return str(d)[:1000]

    # текущие факты
    facts = await dbsvc.get_session_facts(session_id) or {}
    extra_raw = facts.get("extra")
    extra = extra_raw.copy() if isinstance(extra_raw, dict) else {}

    # Сохранение по типам
    if code in {"mission", "love"}:
        text = data.get("text") or data.get(code) or ""
        await dbsvc.add_fact_version(session_id, code, {"text": text}, make_active=True)
        await dbsvc.upsert_session_facts(session_id, **{code: text})

    elif code in {"finance", "karma", "year"}:
        text = data.get("text") or data.get(code) or ""
        await dbsvc.add_fact_version(session_id, code, {"text": text}, make_active=True)
        extra[code] = text
        await dbsvc.upsert_session_facts(session_id, extra=extra)

    elif code in {"strengths", "weaknesses", "business", "countries"}:
        # ожидаем {"items":[...]}
        items = data.get("items")
        payload = {"items": items if isinstance(items, list) else []}
        await dbsvc.add_fact_version(session_id, code, payload, make_active=True)
        await dbsvc.upsert_session_facts(session_id, **{code: payload})

    else:
        # неизвестный/кастомный сценарий — сохраняем «как есть» в extra
        extra[code] = data
        await dbsvc.upsert_session_facts(session_id, extra=extra)

    # пересобираем summary
    await dbsvc.rebuild_session_summary(session_id)

    return data, _preview_from_data(data)




# ---------- Главное меню: сценарии ----------

@router.callback_query(Flow.MENU, F.data == "menu:mission")
async def menu_mission(cb: CallbackQuery, state: FSMContext):
    # Канальный гейт (если включён для этого сценария)
    if await _gate_check_and_prompt(cb, "mission"):
        return
    # Реферальный гейт (если включён для этого сценария)
    need_ref, _, _ = await _need_referral_gate(cb, "mission")
    if need_ref:
        return await menu_invite(cb, state)
    data = await state.get_data()
    session_id = data["session_id"]

    facts = await dbsvc.get_session_facts(session_id)
    mission = (facts or {}).get("mission")
    if not mission:
        from services.db import _require_pool
        pool = _require_pool()
        row = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row["raw_calc_json"] if row else None

        summary = await dbsvc.get_session_summary_text(session_id)
        mission = await llmsvc.generate_text_or_mock(
            scenario="mission",
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )

        # версионирование (храним текст в jsonb как {"text": "..."}), + каноническая запись
        await dbsvc.add_fact_version(session_id, "mission", {"text": mission}, make_active=True)
        await dbsvc.upsert_session_facts(session_id, mission=mission)
        await dbsvc.rebuild_session_summary(session_id)

    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, f"🌟 <b>Твоя миссия</b>\n\n{mission}", reply_markup=markup)


@router.callback_query(Flow.MENU, F.data == "menu:countries")
async def menu_countries(cb: CallbackQuery, state: FSMContext):
    # ГЕЙТ
    if await _gate_check_and_prompt(cb, "countries"):
        return

    data = await state.get_data()
    session_id = data["session_id"]

    facts = await dbsvc.get_session_facts(session_id)
    countries = (facts or {}).get("countries")
    if not countries or "items" not in countries:
        from services.db import _require_pool
        pool = _require_pool()
        row = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row["raw_calc_json"] if row else None

        summary = await dbsvc.get_session_summary_text(session_id)
        countries = await llmsvc.generate_list_or_mock(
            scenario="countries",
            n=5,
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )
        await dbsvc.add_fact_version(session_id, "countries", countries, make_active=True)
        await dbsvc.upsert_session_facts(session_id, countries=countries)
        await dbsvc.rebuild_session_summary(session_id)

    text = "🗺️ <b>Топ-5 стран для жизни</b>\n\n" + _fmt_list(countries.get("items", []))
    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, text, reply_markup=markup)


@router.callback_query(Flow.MENU, F.data == "menu:business")
async def menu_business(cb: CallbackQuery, state: FSMContext):
    if await _gate_check_and_prompt(cb, "business"):
        return
        # Реферальный гейт (если включён для этого сценария)
    need_ref, _, _ = await _need_referral_gate(cb, "business")
    if need_ref:
        return await menu_invite(cb, state)
    data = await state.get_data()
    session_id = data["session_id"]

    facts = await dbsvc.get_session_facts(session_id)
    business = (facts or {}).get("business")
    if not business or "items" not in business:
        from services.db import _require_pool
        pool = _require_pool()
        row = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row["raw_calc_json"] if row else None

        summary = await dbsvc.get_session_summary_text(session_id)
        business = await llmsvc.generate_list_or_mock(
            scenario="business",
            n=10,
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )
        await dbsvc.add_fact_version(session_id, "business", business, make_active=True)
        await dbsvc.upsert_session_facts(session_id, business=business)
        await dbsvc.rebuild_session_summary(session_id)

    text = "💼 <b>Топ-10 бизнес-идей</b>\n\n" + _fmt_list(business.get("items", []))
    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, text, reply_markup=markup)


@router.callback_query(Flow.MENU, F.data == "menu:love")
async def menu_love(cb: CallbackQuery, state: FSMContext):
    if await _gate_check_and_prompt(cb, "love"):
        return
        # Реферальный гейт (если включён для этого сценария)
    need_ref, _, _ = await _need_referral_gate(cb, "love")
    if need_ref:
        return await menu_invite(cb, state)
    data = await state.get_data()
    session_id = data["session_id"]

    facts = await dbsvc.get_session_facts(session_id)
    love = (facts or {}).get("love")
    if not love:
        from services.db import _require_pool
        pool = _require_pool()
        row = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row["raw_calc_json"] if row else None

        summary = await dbsvc.get_session_summary_text(session_id)
        love = await llmsvc.generate_text_or_mock(
            scenario="love",
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )
        await dbsvc.add_fact_version(session_id, "love", {"text": love}, make_active=True)
        await dbsvc.upsert_session_facts(session_id, love=love)
        await dbsvc.rebuild_session_summary(session_id)

    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, f"❤️ <b>Личная жизнь</b>\n\n{love}", reply_markup=markup)

@router.callback_query(Flow.MENU, F.data == "menu:invite")
async def menu_invite(cb: CallbackQuery, state: FSMContext):
    # username бота для t.me/...
    me = await cb.bot.get_me()
    bot_username = me.username or "yourbot"

    # ref-код: как в deep-link обработчике — обычно 'ref' + tg_id
    ref_code = f"ref{cb.from_user.id}"
    invite_url = f"https://t.me/{bot_username}?start={ref_code}"

    # прогресс
    pool = _require_pool()
    row = await pool.fetchrow("SELECT id FROM users WHERE tg_id=$1", cb.from_user.id)
    uid = row["id"] if row else None
    cnt = await _referral_count(uid) if uid else 0
    try:
        thr = int(await _get_admin_value("referral_bonus_threshold") or 3)
    except Exception:
        thr = 3

    enabled = _as_bool(await _get_admin_value("enable_referrals"))
    tail = "" if enabled else "\n\n<i>Реферальная система сейчас выключена админом.</i>"

    text = (
        "👥 <b>Пригласи друга → получи бонус</b>\n\n"
        f"Ваша персональная ссылка:\n<code>{invite_url}</code>\n\n"
        f"Прогресс: <b>{cnt}</b> из <b>{thr}</b> приглашённых.{tail}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    await safe_edit(cb, text, reply_markup=kb.as_markup())


@router.callback_query(Flow.MENU, F.data == "nav:back")
async def nav_back_in_menu(cb: CallbackQuery, state: FSMContext):
    await _render_main(cb, state)


@router.callback_query(Flow.MENU, F.data == "menu:finance")
async def menu_finance(cb: CallbackQuery, state: FSMContext):
    # ГЕЙТ: если нет подписки — покажем экран и выйдем
    if await _gate_check_and_prompt(cb, "finance"):
        return

    data = await state.get_data()
    session_id = data["session_id"]

    # пробуем взять из кэша (session_facts.extra.finance)
    facts = await dbsvc.get_session_facts(session_id)
    finance = None
    if facts:
        extra_raw = facts.get("extra")
        extra = extra_raw if isinstance(extra_raw, dict) else {}
        finance = extra.get("finance")

    if not finance:
        # достаём astro_json и session_summary
        from services.db import _require_pool
        pool = _require_pool()
        row = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row["raw_calc_json"] if row else None

        summary = await dbsvc.get_session_summary_text(session_id)

        # генерим текст
        finance = await llmsvc.generate_text_or_mock(
            scenario="finance",
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )

        # версия (для истории и «перегенерации» в будущем)
        await dbsvc.add_fact_version(session_id, "finance", {"text": finance}, make_active=True)

        # сохраняем в session_facts.extra -> finance (без изменения схемы таблицы)
        await pool.execute(
            """
            INSERT INTO session_facts (session_id, extra)
            VALUES ($1, jsonb_build_object('finance', to_jsonb($2::text)))
            ON CONFLICT (session_id) DO UPDATE
            SET extra = coalesce(session_facts.extra, '{}'::jsonb)
                       || jsonb_build_object('finance', to_jsonb($2::text))
            """,
            session_id, finance
        )
        await dbsvc.rebuild_session_summary(session_id)

    # рисуем меню с замочками
    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, f"💰 <b>Финансовый потенциал</b>\n\n{finance}", reply_markup=markup)

@router.callback_query(Flow.MENU, F.data == "menu:year")
async def menu_year(cb: CallbackQuery, state: FSMContext):
    # Если бонус НЕ открыт — сразу ведём на «Пригласи друга → бонус»
    need_ref, _, _ = await _need_referral_gate(cb, "year")
    if need_ref:
        return await menu_invite(cb, state)

    data = await state.get_data()
    session_id = data["session_id"]
    pool = _require_pool()

    # 1) читаем extra
    row = await pool.fetchrow("SELECT extra FROM session_facts WHERE session_id=$1", session_id)
    raw_extra = row["extra"] if row else None

    # 2) нормализуем к строке + миграции/починка «обёртки»
    year_text = None
    if isinstance(raw_extra, dict):
        year_raw = raw_extra.get("year")
    elif isinstance(raw_extra, str) and raw_extra:
        year_raw = raw_extra
        # миграция случая, когда ВЕСЬ extra был строкой
        await pool.execute(
            "UPDATE session_facts SET extra = jsonb_build_object('year', to_jsonb($2::text)) WHERE session_id=$1",
            session_id, year_raw
        )
    else:
        year_raw = None

    # если year_raw — словарь: берём .text/.year; если строка — распаковываем JSON-строку
    if isinstance(year_raw, dict):
        year_text = year_raw.get("text") or year_raw.get("year") or json.dumps(year_raw, ensure_ascii=False)
        # перезаписываем extra.year плоским текстом
        await pool.execute(
            """
            UPDATE session_facts
            SET extra = COALESCE(extra,'{}'::jsonb) || jsonb_build_object('year', to_jsonb($2::text))
            WHERE session_id=$1
            """,
            session_id, year_text
        )
    elif isinstance(year_raw, str):
        unwrapped = _unwrap_json_text(year_raw)
        if unwrapped != year_raw:
            await pool.execute(
                """
                UPDATE session_facts
                SET extra = COALESCE(extra,'{}'::jsonb) || jsonb_build_object('year', to_jsonb($2::text))
                WHERE session_id=$1
                """,
                session_id, unwrapped
            )
        year_text = unwrapped
    else:
        year_text = None

    # 3) если «мусор» (пусто/только год/слишком коротко) — СНАЧАЛА очищаем ключ, чтобы он не мешал
    if _needs_year_regen(year_text):
        await pool.execute(
            "UPDATE session_facts SET extra = COALESCE(extra,'{}'::jsonb) - 'year' WHERE session_id=$1",
            session_id
        )

        # 4) основная генерация
        row2 = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row2["raw_calc_json"] if row2 else None
        summary = await dbsvc.get_session_summary_text(session_id)

        year_text = await llmsvc.generate_text_or_mock(
            scenario="year",
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )

        # 5) фолбэк: если снова мусор (например, вернулось «2024») — пробуем админ-сценарий
        if _needs_year_regen(year_text):
            try:
                data_json = await llmsvc.run_scenario(session_id, "year") or {}
                year_text = (data_json.get("text") if isinstance(data_json, dict) else "") \
                            or "Годовой отчёт недоступен. Попробуй позже."
            except Exception:
                year_text = "Годовой отчёт недоступен. Попробуй позже."

        if isinstance(year_text, str):
            year_text = _unwrap_json_text(year_text)

        # 6) сохраняем в версии и в extra.year
        await dbsvc.add_fact_version(session_id, "year", {"text": year_text}, make_active=True)
        await pool.execute("""
            INSERT INTO session_facts (session_id, extra)
            VALUES ($1, jsonb_build_object('year', to_jsonb($2::text)))
            ON CONFLICT (session_id) DO UPDATE
            SET extra = COALESCE(session_facts.extra, '{}'::jsonb)
                     || jsonb_build_object('year', to_jsonb($2::text))
        """, session_id, year_text)
        await dbsvc.rebuild_session_summary(session_id)

    # 7) показать отчёт
    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, f"📅 <b>Годовой отчёт</b>\n\n{year_text}", reply_markup=markup)







@router.callback_query(Flow.MENU, F.data == "menu:reset")
async def menu_reset(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        await dbsvc.deactivate_sessions(user_id)

    await state.clear()
    await safe_edit(
        cb,"Данные сброшены. Готов начать заново 👇",
        reply_markup=start_kb()
    )


@router.callback_query(Flow.MENU, F.data == "menu:back")
async def menu_back(cb: CallbackQuery, state: FSMContext):
    await _render_main(cb, state)


@router.callback_query(Flow.MENU, F.data == "menu:karma")
async def menu_karma(cb: CallbackQuery, state: FSMContext):
    # гейт
    if await _gate_check_and_prompt(cb, "karma"):
        return

    data = await state.get_data()
    session_id = data["session_id"]

    facts = await dbsvc.get_session_facts(session_id)
    karma = None
    if facts:
        extra_raw = facts.get("extra")
        extra = extra_raw if isinstance(extra_raw, dict) else {}
        karma = extra.get("karma")

    if not karma:
        from services.db import _require_pool
        pool = _require_pool()
        row = await pool.fetchrow("SELECT raw_calc_json FROM sessions WHERE id=$1", session_id)
        astro_json = row["raw_calc_json"] if row else None
        summary = await dbsvc.get_session_summary_text(session_id)

        karma = await llmsvc.generate_text_or_mock(
            scenario="karma",
            astro_json=astro_json,
            session_summary=summary,
            session_id=session_id,
        )

        await dbsvc.add_fact_version(session_id, "karma", {"text": karma}, make_active=True)
        await pool.execute(
            """
            INSERT INTO session_facts (session_id, extra)
            VALUES ($1, jsonb_build_object('karma', to_jsonb($2::text)))
            ON CONFLICT (session_id) DO UPDATE
            SET extra = coalesce(session_facts.extra, '{}'::jsonb)
                       || jsonb_build_object('karma', to_jsonb($2::text))
            """,
            session_id, karma
        )
        await dbsvc.rebuild_session_summary(session_id)

    locks = await _locks_for_menu(cb)
    markup = await _main_menu_markup_for_user(cb.from_user.id, locks)
    await safe_edit(cb, f"🌀 <b>Кармический разбор</b>\n\n{karma}", reply_markup=markup)

@router.message(F.text.lower().in_({"расчёты", "расчеты"}))
@router.message(F.text.startswith("/calc"))
async def open_calc_menu_msg(m: Message):
    await m.answer("Выбери расчёт:", reply_markup=await _scenarios_kb())

@router.callback_query(Flow.MENU, F.data == "menu:calc")
async def open_calc_menu_cb(cb: CallbackQuery, state: FSMContext):
    await safe_edit(cb, "Выбери расчёт:", reply_markup=await _scenarios_kb())


def _scenario_view_kb(code: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="♻️ Пересчитать", callback_data=f"scnregen:{code}")
    kb.button(text="⬅️ В меню", callback_data="menu:back")
    kb.adjust(1, 1)
    return kb.as_markup()

@router.callback_query(Flow.MENU, F.data.startswith(SCN_PREFIX))
async def run_scenario(cb: CallbackQuery, state: FSMContext):
    code = cb.data[len(SCN_PREFIX):].strip().lower()

    # гейты как раньше
    if await _gate_check_and_prompt(cb, code):
        return

    # 2) реферальный гейт (если нужен для этого сценария)
    need_ref, _, _ = await _need_referral_gate(cb, code)
    if need_ref:
        await cb.answer("Бонус ещё не открыт. Раздел «Пригласи друга → бонус».", show_alert=True)
        return await menu_invite(cb, state)

    data = await state.get_data()
    session_id = data.get("session_id")
    if not session_id:
        user_id = await dbsvc.get_user_id_by_tg(cb.from_user.id)
        session_id = await dbsvc.get_active_session_id(user_id or 0)
        if not session_id:
            await cb.message.answer("Нет активной сессии. Нажми /start.")
            await cb.answer()
            return
        await state.update_data(session_id=session_id)

    await cb.answer()  # убрать часики
    await cb.message.answer("Готовлю раздел…")

    _, preview = await _gen_and_store(session_id, code)

    head = await _scenario_title(code)
    await cb.message.answer(f"<b>{head}</b>\n\n{preview}", reply_markup=_scenario_view_kb(code))


@router.callback_query(Flow.MENU, F.data.startswith("scnregen:"))
async def scenario_regen(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":", 1)[1]

    # те же гейты
    if code in {SCN.FINANCE.value, SCN.COUNTRIES.value, SCN.KARMA.value} and await _gate_check_and_prompt(cb, code):
        return
    if code == SCN.YEAR.value and not await _show_year(cb.from_user.id):
        await cb.answer("Бонус ещё не открыт. Раздел «Пригласи друга → бонус».", show_alert=True)
        return await menu_invite(cb, state)

    data = await state.get_data()
    session_id = data.get("session_id")
    if not session_id:
        user_id = await dbsvc.get_user_id_by_tg(cb.from_user.id)
        session_id = await dbsvc.get_active_session_id(user_id or 0)
        if not session_id:
            await cb.message.answer("Нет активной сессии. Нажми /start.")
            await cb.answer()
            return
        await state.update_data(session_id=session_id)

    await cb.answer("Пересчитываю…")
    _, preview = await _gen_and_store(session_id, code)
    head = await _scenario_title(code)
    await cb.message.answer(f"♻️ <b>{head}</b> (обновлено)\n\n{preview}", reply_markup=_scenario_view_kb(code))


async def _scenario_title(code: str) -> str:
    """Заголовок сценария из admin_scenarios, или сам code если не найден."""
    pool = _require_pool()
    row = await pool.fetchrow("SELECT title FROM admin_scenarios WHERE scenario=$1", code)
    return (row["title"] if row and row["title"] else code)

async def _log_spinner_kind(msg: Message):
    # Если это был стикер
    if msg.sticker:
        s = msg.sticker
        fmt = getattr(s, "format", None)
        logging.info(
            f"spinner sent as STICKER: "
            f"format={getattr(fmt, 'value', fmt)} "
            f"is_animated={getattr(s, 'is_animated', None)} "
            f"is_video={getattr(s, 'is_video', None)} "
            f"type={getattr(s, 'type', None)}"
        )
        return

    # Если это текст с custom emoji
    ents = msg.entities or []
    ce = next((e for e in ents if e.type == "custom_emoji"), None)
    if ce and ce.custom_emoji_id:
        try:
            stickers = await msg.bot.get_custom_emoji_stickers([ce.custom_emoji_id])
            s = stickers[0] if stickers else None
            fmt = getattr(s, "format", None) if s else None
            logging.info(
                f"spinner sent as CUSTOM_EMOJI: id={ce.custom_emoji_id} "
                f"format={getattr(fmt, 'value', fmt)} "
                f"is_animated={getattr(s, 'is_animated', None)} "
                f"is_video={getattr(s, 'is_video', None)}"
            )
        except Exception as e:
            logging.warning(f"custom emoji meta fetch failed: {e}")
    else:
        logging.info("spinner sent as plain text emoji (no sticker, no custom emoji).")

def _unwrap_json_text(s: str) -> str:
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj.get("text") or obj.get("year") or s
    except Exception:
        pass
    return s

# === Универсальная «Я подписался» для любых сценариев ===

# Мапа: код сценария -> его menu_* хендлер
SCENARIO_MENU_HANDLERS = {
    "finance":  menu_finance,
    "countries": menu_countries,
    "karma":    menu_karma,
    "love":     menu_love,
    "year":     menu_year,
    "business": menu_business,
    "mission":  menu_mission,
    # при необходимости добавишь сюда и другие
}

@router.callback_query(F.data.startswith("gate:recheck:"))
async def gate_recheck_any(cb: CallbackQuery, state: FSMContext):
    # из "gate:recheck:<scenario>" достаём <scenario>
    code = cb.data.split(":", 2)[2].strip().lower()

    # если всё ещё не подписан — останемся на экране гейта
    locked, _ = await _need_channel_gate(cb, code)
    if locked:
        await cb.answer("Подписка пока не видна. Проверь и попробуй снова.", show_alert=True)
        return

    # иначе — открыть нужный раздел
    handler = SCENARIO_MENU_HANDLERS.get(code) if False else SCENARIO_MENU_HANDLERS.get(code)
    if handler:
        return await handler(cb, state)

    # если вдруг сценарий не в мапе
    await cb.answer("Ок!", show_alert=False)
