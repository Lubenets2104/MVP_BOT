import os
import re
import time as _time
import logging
import asyncio
from typing import Tuple, Optional

import httpx
from timezonefinder import TimezoneFinder
from datetime import date, datetime, time as dtime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .db import _require_pool

_LOG = logging.getLogger(__name__)

# --- Headers/locale ---
_LANGS = os.getenv("GEOCODE_LANGS", "ru,en")
_CONTACT = os.getenv("GEOCODER_EMAIL", os.getenv("ADMIN_EMAIL", "admin@example.com"))
_UA = {"User-Agent": f"astro-bot/1.0 (+contact: {_CONTACT})"}

# --- rate-limit: не чаще 1 запрос/сек на процесс ---
_RATE_LOCK = asyncio.Lock()
_last_call_at: float = 0.0

# timezonefinder лучше держать в памяти
_tzf = TimezoneFinder(in_memory=True)

# нормализатор ключа кэша: нижний регистр, одинарные пробелы
_norm_spaces = re.compile(r"\s+")


async def _rl_get_json(client: httpx.AsyncClient, url: str, *, params: dict, headers: dict, retries: int = 2):
    """GET c rate-limit (>=1.1s между вызовами) и ретраями на 429/сетевые ошибки."""
    global _last_call_at
    for attempt in range(retries + 1):
        # rate limit
        async with _RATE_LOCK:
            delta = _time.monotonic() - _last_call_at
            wait_for = 1.1 - delta
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            _last_call_at = _time.monotonic()

        try:
            resp = await client.get(url, params=params, headers=headers, timeout=20.0)
            if resp.status_code == 429:
                backoff = 2 ** attempt
                _LOG.warning("geocode 429 from %s, retry in %ss", url, backoff)
                await asyncio.sleep(backoff)
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, httpx.ReadTimeout) as e:
            if attempt >= retries:
                _LOG.error("geocode HTTP error %s on %s params=%s", e, url, params)
                raise
            backoff = 2 ** attempt
            _LOG.warning("geocode network error, retry in %ss", backoff)
            await asyncio.sleep(backoff)

    raise RuntimeError("geocode: exhausted retries")


async def geocode_city(q: str) -> Tuple[float, float, str]:
    """
    Возвращает (lat, lon, tz). Сначала пробует кэш (таблица geocode_cache),
    при промахе — Nominatim, при пустом ответе — Photon, затем пишет в кэш.
    Гарантирует rate-limit и обработку 429.
    """
    pool = _require_pool()

    # Нормализуем ключ кэша
    norm_q = _norm_spaces.sub(" ", (q or "").strip().lower())
    if not norm_q:
        raise ValueError("Город не указан")

    # 1) HIT?
    row = await pool.fetchrow("SELECT lat, lon, tz FROM geocode_cache WHERE q=$1", norm_q)
    if row:
        _LOG.info("geocode cache HIT: %s -> (%s, %s) %s", norm_q, row["lat"], row["lon"], row["tz"])
        return float(row["lat"]), float(row["lon"]), str(row["tz"])

    lat: Optional[float] = None
    lon: Optional[float] = None

    async with httpx.AsyncClient() as client:
        # 2) Nominatim
        try:
            params = {
                "q": q,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 0,
                "accept-language": _LANGS,
            }
            data = await _rl_get_json(client, "https://nominatim.openstreetmap.org/search", params=params, headers=_UA)
            if isinstance(data, list) and data:
                try:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    _LOG.info("geocode Nominatim OK: %s -> (%s, %s)", q, lat, lon)
                except Exception:
                    lat = lon = None
        except Exception as e:
            _LOG.warning("Nominatim failed: %s", e)

        # 3) Fallback: Photon
        if lat is None or lon is None:
            p = {
                "q": q,
                "limit": 1,
                "lang": (_LANGS.split(",")[0] if _LANGS else "en"),
            }
            pdata = await _rl_get_json(client, "https://photon.komoot.io/api", params=p, headers=_UA)
            feats = (pdata or {}).get("features") or []
            if not feats:
                raise RuntimeError("Не удалось определить координаты города")
            coords = feats[0]["geometry"]["coordinates"]
            lon = float(coords[0])
            lat = float(coords[1])
            _LOG.info("geocode Photon OK: %s -> (%s, %s)", q, lat, lon)

    # 4) Таймзона по координатам
    tz = _tz_from_latlon(lat, lon) or "UTC"

    # 5) UPSERT кэш
    await pool.execute(
        """
        INSERT INTO geocode_cache (q, lat, lon, tz)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (q) DO UPDATE
        SET lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            tz  = EXCLUDED.tz,
            updated_at = now()
        """,
        norm_q, lat, lon, tz,
    )
    _LOG.info("geocode cache STORE: %s", norm_q)

    return lat, lon, tz


def _tz_from_latlon(lat: float, lon: float) -> Optional[str]:
    tz = _tzf.timezone_at(lng=lon, lat=lat)
    if tz:
        return tz
    return _tzf.closest_timezone_at(lng=lon, lat=lat)


def to_utc(birth_date: date, birth_time: Optional[dtime], tz_name: str) -> datetime:
    """
    Конвертирует локальные дату/время (в таймзоне tz_name) в UTC-datetime.
    Если время неизвестно — берём 12:00 (можешь поменять на 00:00).
    Учитываем неоднозначность на границах DST: используем fold=0 (первое наступление времени).
    """
    t = birth_time or dtime(12, 0)
    try:
        z = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        z = timezone.utc

    naive = datetime.combine(birth_date, t)
    # две интерпретации на «двойном» часу
    dt_fold0 = naive.replace(tzinfo=z, fold=0)
    dt_fold1 = naive.replace(tzinfo=z, fold=1)
    off0 = dt_fold0.utcoffset()
    off1 = dt_fold1.utcoffset()
    if off0 != off1:
        _LOG.info("DST ambiguous local time: %s %s in %s (using fold=0)", birth_date, t, tz_name)
    return dt_fold0.astimezone(timezone.utc)
