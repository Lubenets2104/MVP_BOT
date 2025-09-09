# bot/services/astro.py
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Optional
from typing import Dict, Any
from zoneinfo import ZoneInfo
from lunar_python import Solar  # библиотека для БаЦзы

import swisseph as swe

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

VEDIC_RASHI = [
    "Mesha", "Vrishabha", "Mithuna", "Karkata", "Simha", "Kanya",
    "Tula", "Vrishchika", "Dhanu", "Makara", "Kumbha", "Meena",
]

PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
}

_STEM_EN = {
    "甲": ("Jia", "Wood", "Yang"),
    "乙": ("Yi", "Wood", "Yin"),
    "丙": ("Bing", "Fire", "Yang"),
    "丁": ("Ding", "Fire", "Yin"),
    "戊": ("Wu", "Earth", "Yang"),
    "己": ("Ji", "Earth", "Yin"),
    "庚": ("Geng", "Metal", "Yang"),
    "辛": ("Xin", "Metal", "Yin"),
    "壬": ("Ren", "Water", "Yang"),
    "癸": ("Gui", "Water", "Yin"),
}

_BRANCH_EN = {
    "子": ("Zi", "Water"),
    "丑": ("Chou", "Earth"),
    "寅": ("Yin", "Wood"),
    "卯": ("Mao", "Wood"),
    "辰": ("Chen", "Earth"),
    "巳": ("Si", "Fire"),
    "午": ("Wu", "Fire"),
    "未": ("Wei", "Earth"),
    "申": ("Shen", "Metal"),
    "酉": ("You", "Metal"),
    "戌": ("Xu", "Earth"),
    "亥": ("Hai", "Water"),
}

def _element_counts_init() -> Dict[str, int]:
    return {"wood": 0, "fire": 0, "earth": 0, "metal": 0, "water": 0}

def _inc_element(counts: Dict[str, int], elem_en: str) -> None:
    key = elem_en.lower()
    if key in counts:
        counts[key] += 1

def _pillar(stem_cn: str, branch_cn: str) -> Dict[str, Any]:
    stem_en, stem_elem, stem_yy = _STEM_EN[stem_cn]
    branch_en, branch_elem = _BRANCH_EN[branch_cn]
    return {
        "stem": stem_en,
        "branch": branch_en,
        "_stem_elem": stem_elem,
        "_stem_yinyang": stem_yy,
        "_branch_elem": branch_elem,
    }


@dataclass
class BirthInput:
    system: str                 # 'western' | 'vedic' | 'bazi'
    birth_date: "date"
    birth_time: Optional["time"]
    lat: float
    lon: float
    tz: str                     # IANA tz, e.g. 'Europe/Moscow'


def _utc_julday(dt_utc: datetime) -> float:
    h = dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, h)


def _sign_from_longitude(lon: float) -> str:
    idx = int(lon // 30) % 12
    return SIGNS[idx]


def _rashi_from_longitude(lon: float) -> str:
    idx = int(lon // 30) % 12
    return VEDIC_RASHI[idx]


def compute_western(dt_utc: datetime, unknown_time: bool, *, lat: Optional[float], lon: Optional[float]) -> dict:
    jd = _utc_julday(dt_utc)
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED  # тропическая система
    out: Dict[str, Any] = {"system": "western", "unknown_time": unknown_time, "planets": {}}

    # Планеты
    for name, code in PLANETS.items():
        res = swe.calc_ut(jd, code, flags)
        xx = res[0] if (isinstance(res, tuple) and len(res) == 2) else res
        lon_pl = float(xx[0])
        out["planets"][name] = {
            "sign": _sign_from_longitude(lon_pl),
            "degree": round(lon_pl % 30.0, 2),
        }

    # Дома/асцендент — только если знаем время и координаты
    if not unknown_time and lat is not None and lon is not None:
        hsys = b'P'  # Placidus
        cusps, ascmc = swe.houses_ex(jd, lat, lon, hsys, flags)
        asc_index = getattr(swe, "ASC", 0)
        asc_lon = float(ascmc[asc_index])
        out["ascendant"] = _sign_from_longitude(asc_lon)

        houses: Dict[str, Any] = {}
        for i in range(1, 13):
            lon_cusp = float(cusps[i])
            houses[str(i)] = f"{_sign_from_longitude(lon_cusp)} {round(lon_cusp % 30.0, 2)}°"
        out["houses"] = houses

    return out



def compute_vedic(dt_utc: datetime, unknown_time: bool, *, lat: Optional[float], lon: Optional[float]) -> dict:
    swe.set_sid_mode(swe.SIDM_LAHIRI)  # айанамса Лахири
    jd = _utc_julday(dt_utc)
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_SIDEREAL  # сидерические долготы
    out: Dict[str, Any] = {"system": "vedic", "ayanamsa": "Lahiri", "unknown_time": unknown_time, "grahas": {}}

    # Грахи
    for name, code in PLANETS.items():
        res = swe.calc_ut(jd, code, flags)
        xx = res[0] if (isinstance(res, tuple) and len(res) == 2) else res
        lon_pl = float(xx[0])
        out["grahas"][name] = {
            "rashi": _rashi_from_longitude(lon_pl),
            "degree": round(lon_pl % 30.0, 2),
        }

    # Лагна и дома
    if not unknown_time and lat is not None and lon is not None:
        hsys = b'P'  # Placidus — для MVP ок
        cusps, ascmc = swe.houses_ex(jd, lat, lon, hsys, flags)
        asc_index = getattr(swe, "ASC", 0)
        lagna_lon = float(ascmc[asc_index])
        out["lagna"] = _rashi_from_longitude(lagna_lon)

        houses: Dict[str, Any] = {}
        for i in range(1, 13):
            lon_cusp = float(cusps[i])
            houses[str(i)] = {"rashi": _rashi_from_longitude(lon_cusp), "degree": round(lon_cusp % 30.0, 2)}
        out["houses"] = houses

    return out



def compute_bazi(b: BirthInput) -> dict:
    """
    Возвращает JSON как в ТЗ:
    {
      "system": "bazi",
      "unknown_time": bool,
      "pillars": {
        "year": {"stem": "Geng", "branch": "Shen"},
        "month": {"stem": "Bing", "branch": "Yin"},
        "day": {"stem": "Wu", "branch": "Chen"},
        "hour": {"stem": "Ji", "branch": "Si", "present": true|false}
      },
      "day_master": "Metal Yang",
      "five_elements": {"wood": n, "fire": n, "earth": n, "metal": n, "water": n}
    }
    """
    unknown_time = b.birth_time is None

    # 1) Собираем локальное время (учитываем IANA tz)
    local_time = b.birth_time or dtime(12, 0)  # если время не знаем — середина дня
    if isinstance(b.birth_date, datetime):
        dt_local = b.birth_date
    else:
        dt_local = datetime.combine(b.birth_date, local_time)

    if b.tz:
        dt_local = dt_local.replace(tzinfo=ZoneInfo(b.tz))

    dt_local_naive = dt_local.replace(tzinfo=None)
    solar = Solar.fromDate(dt_local_naive)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()

    yg, yz = ec.getYearGan(), ec.getYearZhi()
    mg, mz = ec.getMonthGan(), ec.getMonthZhi()
    dg, dz = ec.getDayGan(), ec.getDayZhi()
    tg, tzhi = ec.getTimeGan(), ec.getTimeZhi()

    year_p = _pillar(yg, yz)
    month_p = _pillar(mg, mz)
    day_p = _pillar(dg, dz)

    # Часовой столп только если время известно
    if not unknown_time:
        hour_p = _pillar(tg, tzhi)
        hour_p_present = True
    else:
        hour_p = {"stem": "", "branch": ""}
        hour_p_present = False

    # 3) Day Master = элемент + инь/ян из дневного ствола
    dm_elem = day_p["_stem_elem"]
    dm_yy = day_p["_stem_yinyang"]
    day_master = f"{dm_elem} {dm_yy}"

    # 4) Пять элементов — считаем по стволам и ветвям (год/месяц/день и при наличии — час)
    counts = _element_counts_init()
    for p in (year_p, month_p, day_p):
        _inc_element(counts, p["_stem_elem"])
        _inc_element(counts, p["_branch_elem"])
    if hour_p_present:
        _inc_element(counts, hour_p["_stem_elem"])
        _inc_element(counts, hour_p["_branch_elem"])

    # 5) Вернём в формате ТЗ
    def _strip(p: Dict[str, Any]) -> Dict[str, Any]:
        return {"stem": p.get("stem", ""), "branch": p.get("branch", "")}

    return {
        "system": "bazi",
        "unknown_time": unknown_time,
        "pillars": {
            "year": _strip(year_p),
            "month": _strip(month_p),
            "day": _strip(day_p),
            "hour": {**_strip(hour_p), "present": hour_p_present},
        },
        "day_master": day_master,
        "five_elements": counts,
    }



def compute_all(b: BirthInput, dt_utc: datetime) -> dict:
    """
    Возвращает ASTRO_JSON по выбранной системе.
    """
    unknown_time = b.birth_time is None
    if b.system == "western":
        return compute_western(dt_utc, unknown_time, lat=b.lat, lon=b.lon)
    if b.system == "vedic":
        return compute_vedic(dt_utc, unknown_time, lat=b.lat, lon=b.lon)

    # bazi
    return compute_bazi(b)
def _calc_lon_deg(jd: float, body: int, flags: int) -> float:
    """
    Унифицированный доступ к calc_ut: возвращает длину по долготе (0..360).
    swe.calc_ut -> (xx, retflag), где xx[0] — долгота.
    """
    res = swe.calc_ut(jd, body, flags)
    if isinstance(res, tuple) and len(res) == 2:
        xx, _retflag = res
    else:
        xx = res  # на всякий случай
    return float(xx[0])

# --- helpers ---
def to_utc_datetime(b: BirthInput) -> datetime:
    """
    Локальные дата/время + IANA tz -> UTC datetime.
    Если времени нет, берём 12:00 локально (MVP).
    """
    local_time = b.birth_time or dtime(12, 0)
    if isinstance(b.birth_date, datetime):
        dt_local = b.birth_date
        if dt_local.tzinfo is None and b.tz:
            from zoneinfo import ZoneInfo
            dt_local = dt_local.replace(tzinfo=ZoneInfo(b.tz))
    else:
        from zoneinfo import ZoneInfo
        dt_local = datetime.combine(b.birth_date, local_time).replace(tzinfo=ZoneInfo(b.tz))
    return dt_local.astimezone(ZoneInfo("UTC"))
