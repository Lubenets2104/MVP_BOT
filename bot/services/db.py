# bot/services/db.py
import json
import logging
from typing import Optional, Any, Dict
import asyncpg

_pool: Optional[asyncpg.Pool] = None


def set_pool(pool: asyncpg.Pool) -> None:
    """Передаём пул из app.py, чтобы все сервисы использовали одну коннекцию."""
    global _pool
    _pool = pool


def _require_pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool is not initialized. Call set_pool(pool) in app startup."
    return _pool


# ---------- admin_settings ----------

async def get_setting_text(key: str, default: str = "") -> str:
    """
    admin_settings.value — jsonb; достаём как текст (весь JSON как строку).
    Для строковых значений этого достаточно. Если значение — объект, вернём JSON-строку.
    """
    pool = _require_pool()
    row = await pool.fetchrow("SELECT value #>> '{}' FROM admin_settings WHERE key=$1", key)
    if row and row[0]:
        return str(row[0])
    return default


async def upsert_setting_text(key: str, text: str) -> None:
    pool = _require_pool()
    await pool.execute(
        """
        INSERT INTO admin_settings(key, value)
        VALUES ($1, to_jsonb($2::text))
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, text
    )


# ---------- admin_scenarios (для меню бота) ----------

async def list_enabled_scenarios() -> list[dict[str, str]]:
    """
    Вернёт список включённых сценариев для кнопок меню.
    [{ "scenario": "mission", "title": "Миссия" }, ...]
    """
    pool = _require_pool()
    rows = await pool.fetch(
        """
        SELECT scenario, title
        FROM admin_scenarios
        WHERE enabled = true
        ORDER BY scenario
        """
    )
    return [{"scenario": r["scenario"], "title": r["title"]} for r in rows]



# ---------- users ----------

async def ensure_user(tg_id: int, user_name: Optional[str] = None) -> int:
    """Возвращает id пользователя в нашей БД, создаёт при первом заходе."""
    pool = _require_pool()
    row = await pool.fetchrow("SELECT id FROM users WHERE tg_id=$1", tg_id)
    if row:
        return int(row[0])
    row = await pool.fetchrow(
        "INSERT INTO users(tg_id, user_name) VALUES($1, $2) RETURNING id",
        tg_id, user_name,
    )
    return int(row[0])


async def set_user_name(user_id: int, name: str) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE users SET user_name=$2 WHERE id=$1", user_id, name)


async def set_user_gender(user_id: int, gender: str) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE users SET gender=$2 WHERE id=$1", user_id, gender)


# ---------- sessions ----------

async def get_active_session_id(user_id: int) -> Optional[int]:
    pool = _require_pool()
    row = await pool.fetchrow(
        "SELECT id FROM sessions WHERE user_id=$1 AND is_active=true ORDER BY id DESC LIMIT 1",
        user_id,
    )
    return int(row[0]) if row else None


async def deactivate_sessions(user_id: int) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE sessions SET is_active=false WHERE user_id=$1 AND is_active=true", user_id)


async def create_session(user_id: int, system: str) -> int:
    """Создаём новую активную сессию под выбранную систему (дату/время/город добавим позже)."""
    pool = _require_pool()
    row = await pool.fetchrow(
        "INSERT INTO sessions(user_id, system, birth_date) VALUES($1, $2, CURRENT_DATE) RETURNING id",
        user_id, system,
    )
    return int(row[0])


async def set_birth_date(session_id: int, date_obj) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE sessions SET birth_date=$2 WHERE id=$1", session_id, date_obj)


async def set_birth_time(session_id: int, time_obj) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE sessions SET birth_time=$2 WHERE id=$1", session_id, time_obj)


async def set_location(session_id: int, lat: float, lon: float, tz: str) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE sessions SET lat=$2, lon=$3, tz=$4 WHERE id=$1", session_id, lat, lon, tz)


async def save_raw_calc(session_id: int, astro_json: dict) -> None:
    pool = _require_pool()
    await pool.execute(
        "UPDATE sessions SET raw_calc_json=$2::jsonb WHERE id=$1",
        session_id,
        json.dumps(astro_json, ensure_ascii=False),
    )



# ---------- session_facts ----------

async def upsert_session_facts(
    session_id: int,
    *,
    mission: Optional[str] = None,
    strengths: Optional[dict] = None,
    weaknesses: Optional[dict] = None,
    countries: Optional[dict] = None,
    business: Optional[dict] = None,
    love: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    pool = _require_pool()

    def _j(v):
        return None if v is None else json.dumps(v, ensure_ascii=False)

    await pool.execute(
        """
        INSERT INTO session_facts (session_id, mission, strengths, weaknesses, countries, business, love, extra)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8::jsonb)
        ON CONFLICT (session_id) DO UPDATE SET
            mission    = COALESCE(EXCLUDED.mission,    session_facts.mission),
            strengths  = COALESCE(EXCLUDED.strengths,  session_facts.strengths),
            weaknesses = COALESCE(EXCLUDED.weaknesses, session_facts.weaknesses),
            countries  = COALESCE(EXCLUDED.countries,  session_facts.countries),
            business   = COALESCE(EXCLUDED.business,   session_facts.business),
            love       = COALESCE(EXCLUDED.love,       session_facts.love),
            extra      = COALESCE(EXCLUDED.extra,      session_facts.extra),
            updated_at = now()
        """,
        session_id,
        mission,
        _j(strengths),
        _j(weaknesses),
        _j(countries),
        _j(business),
        love,
        _j(extra),
    )


    # динамически собираем апдейт
    sets, values = [], [session_id]
    idx = 2
    for col, val in [
        ("mission", mission),
        ("strengths", strengths),
        ("weaknesses", weaknesses),
        ("countries", countries),
        ("business", business),
        ("love", love),
        ("extra", extra),
    ]:
        if val is not None:
            sets.append(f"{col} = ${idx}")
            values.append(json.dumps(val) if isinstance(val, (dict, list)) else val)
            idx += 1

    if sets:
        q = f"UPDATE session_facts SET {', '.join(sets)}, updated_at=now() WHERE session_id=$1"
        await pool.execute(q, *values)

async def get_session_facts(session_id: int) -> dict:
    pool = _require_pool()
    row = await pool.fetchrow(
        """
        SELECT mission, strengths, weaknesses, countries, business, love, extra
        FROM session_facts WHERE session_id=$1
        """,
        session_id,
    )
    if not row:
        return {}

    result = dict(row)

    def _maybe_json(x):
        if isinstance(x, str):
            try:
                return json.loads(x)
            except Exception:
                return x
        return x

    # поля jsonb могут прийти строкой — приводим к dict/list
    for key in ("strengths", "weaknesses", "countries", "business", "extra"):
        if key in result:
            result[key] = _maybe_json(result[key])

    return result

async def log_llm_message(
    session_id: int,
    scenario: str,
    role: str,
    content: str,
    *,
    schema_ok: Optional[bool] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    status: Optional[str] = "ok",
) -> None:
    pool = _require_pool()
    await pool.execute(
        """
        INSERT INTO llm_messages(session_id, scenario, role, content, schema_ok, input_tokens, output_tokens, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        session_id, scenario, role, content, schema_ok, input_tokens, output_tokens, status,
    )

# Полная замена функции add_fact_version
async def add_fact_version(
    session_id: int,
    scenario: str,
    content,
    *,
    make_active: bool = False,
):
    """
    Сохраняет новую версию фактов для сценария.
    content — dict/str; в БД хранится jsonb.
    Если make_active=True — деактивируем старые версии и ставим новую активной.
    """
    pool = _require_pool()

    # Всегда приводим к строке JSON — так гарантированно совместимо с $3::jsonb
    if isinstance(content, (bytes, bytearray)):
        content_json = content.decode("utf-8", errors="replace")
    elif isinstance(content, str):
        content_json = content
    else:
        content_json = json.dumps(content, ensure_ascii=False)

    async with pool.acquire() as conn:
        async with conn.transaction():
            if make_active:
                # Снимем активность со старых версий этого сценария
                await conn.execute(
                    "UPDATE session_facts_versions SET is_active=false WHERE session_id=$1 AND scenario=$2",
                    session_id, scenario
                )

            # Вставляем новую версию (явный каст к jsonb)
            await conn.execute(
                """
                INSERT INTO session_facts_versions (session_id, scenario, content, is_active)
                VALUES ($1, $2, $3::jsonb, $4)
                """,
                session_id, scenario, content_json, make_active
            )

async def upsert_session_summary(session_id: int, summary_text: str | None) -> None:
    """
    Сохраняет краткую сводку по сессии (session_summary).
    Если запись уже есть — обновляет текст и updated_at.
    """
    pool = _require_pool()
    summary_text = summary_text or ""
    await pool.execute(
        """
        INSERT INTO session_summary (session_id, summary_text)
        VALUES ($1, $2)
        ON CONFLICT (session_id) DO UPDATE
          SET summary_text = EXCLUDED.summary_text,
              updated_at   = now()
        """,
        session_id, summary_text
    )

# -- get session summary text ---------------------------------------------------
async def get_session_summary_text(session_id: int) -> str:
    """
    Возвращает текст сводки для сессии или пустую строку.
    """
    pool = _require_pool()
    row = await pool.fetchrow(
        "SELECT summary_text FROM session_summary WHERE session_id=$1",
        session_id
    )
    return (row["summary_text"] if row and row["summary_text"] else "") or ""

# ---------- admin_settings (нормализованная схема; одна строка id=1) ----------
from typing import Any, Optional
import json

# Маппинг поддерживаемых настроек на колонки таблицы
_ADMIN_COL_MAP: dict[str, str] = {
    "greeting_text": "greeting_text",
    "system_prompt": "system_prompt",
    "enable_referrals": "enable_referrals",
    "referral_bonus_threshold": "referral_bonus_threshold",
    "enable_channel_gate": "enable_channel_gate",
    "telegram_channel_id": "telegram_channel_id",
    "telegram_channel_url": "telegram_channel_url",
    "bonus_sections": "bonus_sections",
    "enable_compat": "enable_compat",
    "enable_periodic_horoscopes": "enable_periodic_horoscopes",
    "strict_json": "strict_json",
    "max_input_length": "max_input_length",
}

async def get_admin_value(key: str) -> Optional[Any]:
    """
    Возвращает значение настройки из admin_settings (id=1).
    """
    col = _ADMIN_COL_MAP.get(key)
    if not col:
        return None
    pool = _require_pool()
    row = await pool.fetchrow(f"SELECT {col} FROM admin_settings WHERE id=1")
    if not row:
        return None
    val = row[col]
    # JSONB может прийти строкой — попробуем распарсить
    if col == "bonus_sections" and isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            pass
    return val

async def get_greeting_text() -> str:
    """
    Удобный хелпер для приветствия.
    """
    val = await get_admin_value("greeting_text")
    return (str(val).strip() if val else "Привет! Я твой личный астро-нейросетевой помощник.")

async def get_user_id_by_tg(tg_id: int) -> int | None:
    pool = _require_pool()
    row = await pool.fetchrow("SELECT id FROM users WHERE tg_id=$1", tg_id)
    return row["id"] if row else None

async def register_referral(inviter_user_id: int, invited_user_id: int) -> bool:
    if inviter_user_id == invited_user_id:
        return False

    pool = _require_pool()
    async with pool.acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                """
                INSERT INTO referrals (inviter_user_id, invited_user_id)
                VALUES ($1, $2)
                ON CONFLICT (invited_user_id) DO NOTHING
                RETURNING 1
                """,
                inviter_user_id, invited_user_id
            )
            created = bool(row)
            if created:
                # не критично; если колонки нет/упадёт — просто залогируем
                try:
                    await con.execute(
                        """
                        UPDATE users
                        SET invited_by_user_id=$1
                        WHERE id=$2 AND invited_by_user_id IS NULL
                        """,
                        inviter_user_id, invited_user_id
                    )
                except Exception as e:
                    logging.warning("optional invited_by_user_id update failed: %s", e)
            return created



async def count_referrals(inviter_user_id: int) -> int:
    pool = _require_pool()
    row = await pool.fetchrow(
        "SELECT count(*) AS c FROM referrals WHERE inviter_user_id=$1",
        inviter_user_id,
    )
    return int(row["c"]) if row else 0

# рядом с set_birth_time / set_location
async def set_unknown_time(session_id: int, val: bool) -> None:
    pool = _require_pool()
    await pool.execute(
        "UPDATE sessions SET unknown_time=$2 WHERE id=$1",
        session_id, val
    )

async def set_unknown_time(session_id: int, flag: bool) -> None:
    pool = _require_pool()
    await pool.execute("UPDATE sessions SET unknown_time=$2 WHERE id=$1", session_id, flag)


# services/db.py
from typing import Optional

def _sys_title(code: Optional[str]) -> str:
    return {"western": "Западная", "vedic": "Ведическая", "bazi": "БаЦзы"}.get(code or "", code or "-")

def _first_sentence(text: str, lim: int = 160) -> str:
    if not text:
        return ""
    txt = str(text).strip()
    p = txt.find(".")
    if 0 <= p <= lim:
        return txt[: p + 1]
    return (txt[: lim] + "…") if len(txt) > lim else txt

def _join_items(obj: Optional[dict], n: int) -> str:
    if not obj or not isinstance(obj, dict):
        return ""
    items = obj.get("items") or []
    return ", ".join(map(str, items[:n]))

async def rebuild_session_summary(session_id: int) -> None:
    """
    Пересобирает SESSION_SUMMARY из sessions, users и session_facts.
    Вызывай после сохранения любого сценария.
    """
    pool = _require_pool()

    srow = await pool.fetchrow(
        """
        SELECT s.user_id, s.system, s.birth_date, s.birth_time, s.lat, s.lon, s.tz, s.unknown_time,
               u.user_name, u.gender
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = $1
        """,
        session_id,
    )
    if not srow:
        return

    frow = await pool.fetchrow(
        """
        SELECT mission, strengths, weaknesses, countries, business, love, extra
        FROM session_facts
        WHERE session_id = $1
        """,
        session_id,
    ) or {}

    name   = srow["user_name"] or "пользователь"
    gender = srow["gender"] or "-"
    sys_t  = _sys_title(srow["system"])
    bd     = srow["birth_date"]
    bt     = srow["birth_time"]
    loc    = f"lat={srow['lat']}, lon={srow['lon']}, tz={srow['tz']}"
    time_s = f", время: {bt}" if bt else ", время: неизвестно"

    # кусочки из фактов
    mission_val = frow.get("mission")
    m_snip = _first_sentence(
        mission_val if isinstance(mission_val, str) else (mission_val or {}).get("text","")
    )
    s3 = _join_items(frow.get("strengths"), 3)
    w3 = _join_items(frow.get("weaknesses"), 3)
    c3 = _join_items(frow.get("countries"), 3)
    b3 = _join_items(frow.get("business"), 3)

    love_val = frow.get("love")
    love_t = love_val if isinstance(love_val, str) else (love_val or {}).get("text","")
    love_snip = _first_sentence(love_t, 120)

    extra = _as_json_obj(frow.get("extra"))
    fin_snip   = _first_sentence(extra.get("finance",""), 120)
    karma_snip = _first_sentence(extra.get("karma",""), 120)
    year_snip  = _first_sentence(extra.get("year",""), 120)

    parts = [
        f"Имя: {name}; пол: {gender}; система: {sys_t}; дата: {bd}{time_s}; место: {loc}.",
    ]
    if m_snip:      parts.append(f" Миссия: {m_snip}")
    if s3:          parts.append(f" Сильные: {s3}.")
    if w3:          parts.append(f" Слабые: {w3}.")
    if c3:          parts.append(f" Страны: {c3}.")
    if b3:          parts.append(f" Бизнес: {b3}.")
    if love_snip:   parts.append(f" Любовь: {love_snip}")
    if fin_snip:    parts.append(f" Финансы: {fin_snip}")
    if karma_snip:  parts.append(f" Карма: {karma_snip}")
    if year_snip:   parts.append(f" Год: {year_snip}")

    summary_text = " ".join(parts).strip()
    await upsert_session_summary(session_id, summary_text)

def _as_json_obj(val):
    """Всегда вернуть dict. Допускаем None, str (json-строка), bytes; иначе {}."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, (bytes, bytearray)):
        try:
            val = val.decode("utf-8", "ignore")
        except Exception:
            return {}
    if isinstance(val, str):
        try:
            obj = json.loads(val)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}
