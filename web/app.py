# web/app.py
import os
import json
import asyncpg
from fastapi import FastAPI, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.templating import Jinja2Templates
from scenario_routes import router as scenarios_router
from services.db import _require_pool

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
DB_URL     = os.getenv("DATABASE_URL", "postgresql://app:app@db:5432/appdb")

app = FastAPI()
app.include_router(scenarios_router)
security = HTTPBasic()
templates = Jinja2Templates(directory="/app/templates")
_pool: asyncpg.Pool | None = None

async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=5)
    return _pool


def require_basic(creds: HTTPBasicCredentials = Depends(security)):
    good = creds.username == ADMIN_USER and creds.password == ADMIN_PASS
    if not good:
        return None
    return creds.username


@app.on_event("shutdown")
async def _shutdown():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ready", tags=["health"])
async def ready():
    try:
        p = await pool()              # берём локальный asyncpg pool из этого файла
        await p.fetchval("SELECT 1")  # пингуем базу
        return {"status": "ok", "db": True}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": False, "error": str(e)},
        )

# ---------- helpers ----------
def _as_bool(v: str) -> bool:
    return str(v).lower() in ("1", "true", "on", "yes")

def _normalize_bonus_sections(bs):
    """
    Приводим bonus_sections к dict:
    - если dict -> вернуть как есть
    - если строка -> пробуем json.loads 1-2 раза (на случай двойной сериализации)
    - иначе -> {}
    """
    if bs is None:
        return {}
    if isinstance(bs, dict):
        return bs
    if isinstance(bs, str):
        try:
            d = json.loads(bs)
            if isinstance(d, str):
                d = json.loads(d)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}

def _force_json_object(raw: str) -> dict:
    """
    Жёстко парсим JSON-объект из textarea.
    Бросаем ошибку, если это не объект.
    """
    data = json.loads(raw or "{}")
    if isinstance(data, str):
        # двойная сериализация
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError('bonus_sections must be a JSON object like {"year":"referral"}')
    return data


# ---------- SETTINGS HTML ----------
@app.get("/settings", response_class=HTMLResponse)
async def settings_get(request: Request, user = Depends(require_basic)):
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    p = await pool()
    row = await p.fetchrow("SELECT * FROM admin_settings WHERE id=1;")
    if not row:
        await p.execute("INSERT INTO admin_settings(id) VALUES (1) ON CONFLICT (id) DO NOTHING;")
        row = await p.fetchrow("SELECT * FROM admin_settings WHERE id=1;")

    ctx = dict(row)

    # Дефолты для формы
    ctx.setdefault("greeting_text", "Привет! Я Астробот ✨")
    ctx.setdefault("system_prompt", "")
    ctx.setdefault("telegram_channel_id", "")
    ctx.setdefault("telegram_channel_url", "")
    ctx.setdefault("referral_bonus_threshold", 3)
    ctx.setdefault("enable_channel_gate", False)
    ctx.setdefault("enable_referrals", False)
    ctx.setdefault("enable_compat", False)
    ctx.setdefault("enable_periodic_horoscopes", False)
    ctx.setdefault("strict_json", True)
    ctx.setdefault("max_input_length", 80)

    # bonus_sections в шаблон — строго объект
    ctx["bonus_sections"] = _normalize_bonus_sections(ctx.get("bonus_sections"))

    return templates.TemplateResponse("settings.html", {"request": request, "s": ctx})


@app.post("/settings")
async def settings_post(
    request: Request,
    user = Depends(require_basic),
    greeting_text: str = Form(""),
    system_prompt: str = Form(""),

    enable_channel_gate: str = Form("off"),
    telegram_channel_id: str = Form(""),
    telegram_channel_url: str = Form(""),
    bonus_sections: str = Form("{}"),

    enable_referrals: str = Form("off"),
    referral_bonus_threshold: int = Form(3),

    # Доп. флаги из формы (есть в шаблоне)
    enable_compat: str = Form("off"),
    enable_periodic_horoscopes: str = Form("off"),
    strict_json: str = Form("off"),
    max_input_length: int = Form(80),
):
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # чекбоксы → bool
    en_gate      = _as_bool(enable_channel_gate)
    en_ref       = _as_bool(enable_referrals)
    en_compat    = _as_bool(enable_compat)
    en_periodic  = _as_bool(enable_periodic_horoscopes)
    en_strict    = _as_bool(strict_json)

    # bonus_sections — строгий парс
    try:
        bonus_obj = _force_json_object(bonus_sections)
    except Exception as e:
        # Вернём форму с ошибкой и уже введёнными данными
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "s": {
                    "greeting_text": greeting_text,
                    "system_prompt": system_prompt,
                    "enable_channel_gate": en_gate,
                    "enable_referrals": en_ref,
                    "enable_compat": en_compat,
                    "enable_periodic_horoscopes": en_periodic,
                    "strict_json": en_strict,
                    "max_input_length": max_input_length,
                    "telegram_channel_id": telegram_channel_id,
                    "telegram_channel_url": telegram_channel_url,
                    "referral_bonus_threshold": referral_bonus_threshold,
                    "bonus_sections": _normalize_bonus_sections(bonus_sections),
                },
                "error": f"bonus_sections: {e}",
            },
            status_code=400,
        )

    p = await pool()
    # Обновляем все поля. Если каких-то колонок нет — убери их из SQL.
    await p.execute(
        """
        UPDATE admin_settings
        SET greeting_text=$1,
            system_prompt=$2,
            enable_channel_gate=$3,
            enable_referrals=$4,
            referral_bonus_threshold=$5,
            telegram_channel_id=$6,
            telegram_channel_url=$7,
            bonus_sections=$8::jsonb,
            enable_compat=$9,
            enable_periodic_horoscopes=$10,
            strict_json=$11,
            max_input_length=$12,
            updated_at=now()
        WHERE id=1
        """,
        greeting_text,
        system_prompt,
        en_gate,
        en_ref,
        referral_bonus_threshold,
        telegram_channel_id.strip(),
        telegram_channel_url.strip(),
        json.dumps(bonus_obj),
        en_compat,
        en_periodic,
        en_strict,
        max_input_length,
    )

    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)
