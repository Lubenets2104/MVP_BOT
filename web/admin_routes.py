from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict
from datetime import datetime
from starlette.status import HTTP_303_SEE_OTHER

import os
import json
from psycopg import connect  # psycopg[binary]
from fastapi.templating import Jinja2Templates


def get_db_dsn() -> str:
    user = os.getenv("POSTGRES_USER", "postgres")
    pwd = os.getenv("POSTGRES_PASSWORD", "postgres")
    db = os.getenv("POSTGRES_DB", "postgres")
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"dbname={db} user={user} password={pwd} host={host} port={port}"


router = APIRouter()
templates = Jinja2Templates(directory="templates")


class AdminSettingsModel(BaseModel):
    greeting_text: Optional[str] = None
    system_prompt: Optional[str] = None
    enable_referrals: bool = False
    referral_bonus_threshold: int = 3
    enable_channel_gate: bool = False
    telegram_channel_id: Optional[str] = None
    telegram_channel_url: Optional[str] = None
    bonus_sections: Dict[str, Any] = Field(default_factory=dict)
    enable_compat: bool = False
    enable_periodic_horoscopes: bool = False
    strict_json: bool = True
    max_input_length: int = 80


def fetch_settings() -> Dict[str, Any]:
    with connect(get_db_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT greeting_text, system_prompt, enable_referrals, referral_bonus_threshold,
                       enable_channel_gate, telegram_channel_id, telegram_channel_url, bonus_sections,
                       enable_compat, enable_periodic_horoscopes, strict_json, max_input_length
                FROM admin_settings WHERE id=1
            """)
            row = cur.fetchone()
            if not row:
                return AdminSettingsModel().dict()

            keys = ["greeting_text","system_prompt","enable_referrals","referral_bonus_threshold",
                    "enable_channel_gate","telegram_channel_id","telegram_channel_url","bonus_sections",
                    "enable_compat","enable_periodic_horoscopes","strict_json","max_input_length"]
            data = dict(zip(keys, row))
            # normalize bonus_sections to dict
            if isinstance(data.get("bonus_sections"), str):
                try:
                    data["bonus_sections"] = json.loads(data["bonus_sections"])
                except Exception:
                    data["bonus_sections"] = {}
            return data


def save_settings(data: AdminSettingsModel) -> None:
    with connect(get_db_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE admin_settings
                SET greeting_text=%s,
                    system_prompt=%s,
                    enable_referrals=%s,
                    referral_bonus_threshold=%s,
                    enable_channel_gate=%s,
                    telegram_channel_id=%s,
                    telegram_channel_url=%s,
                    bonus_sections=%s::jsonb,
                    enable_compat=%s,
                    enable_periodic_horoscopes=%s,
                    strict_json=%s,
                    max_input_length=%s,
                    updated_at=now()
                WHERE id=1
            """, (
                data.greeting_text, data.system_prompt, data.enable_referrals, data.referral_bonus_threshold,
                data.enable_channel_gate, data.telegram_channel_id, data.telegram_channel_url,
                json.dumps(data.bonus_sections), data.enable_compat, data.enable_periodic_horoscopes,
                data.strict_json, data.max_input_length
            ))
            if cur.rowcount == 0:
                cur.execute("""
                    INSERT INTO admin_settings (
                        id, greeting_text, system_prompt, enable_referrals, referral_bonus_threshold,
                        enable_channel_gate, telegram_channel_id, telegram_channel_url, bonus_sections,
                        enable_compat, enable_periodic_horoscopes, strict_json, max_input_length
                    ) VALUES (
                        1, %s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s
                    )
                """, (
                    data.greeting_text, data.system_prompt, data.enable_referrals, data.referral_bonus_threshold,
                    data.enable_channel_gate, data.telegram_channel_id, data.telegram_channel_url,
                    json.dumps(data.bonus_sections), data.enable_compat, data.enable_periodic_horoscopes,
                    data.strict_json, data.max_input_length
                ))
        conn.commit()


@router.get("/health")
def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@router.get("/settings", response_class=HTMLResponse)
def get_settings(request: Request):
    s = fetch_settings()
    return templates.TemplateResponse("settings.html", {"request": request, "s": s})


@router.post("/settings")
def post_settings(
    request: Request,
    greeting_text: str = Form(""),
    system_prompt: str = Form(""),
    enable_referrals: Optional[str] = Form(None),
    referral_bonus_threshold: int = Form(3),
    enable_channel_gate: Optional[str] = Form(None),
    telegram_channel_id: str = Form(""),
    telegram_channel_url: str = Form(""),
    bonus_sections: str = Form("{}"),
    enable_compat: Optional[str] = Form(None),
    enable_periodic_horoscopes: Optional[str] = Form(None),
    strict_json: Optional[str] = Form("on"),
    max_input_length: int = Form(80),
):
    # parse JSON field
    try:
        bonus_sections_obj = json.loads(bonus_sections or "{}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"bonus_sections must be valid JSON: {e}")

    model = AdminSettingsModel(
        greeting_text=greeting_text or "",
        system_prompt=system_prompt or "",
        enable_referrals=bool(enable_referrals),
        referral_bonus_threshold=referral_bonus_threshold,
        enable_channel_gate=bool(enable_channel_gate),
        telegram_channel_id=telegram_channel_id or None,
        telegram_channel_url=telegram_channel_url or None,
        bonus_sections=bonus_sections_obj,
        enable_compat=bool(enable_compat),
        enable_periodic_horoscopes=bool(enable_periodic_horoscopes),
        strict_json=bool(strict_json),
        max_input_length=max_input_length,
    )
    save_settings(model)
    return RedirectResponse(url="/settings", status_code=HTTP_303_SEE_OTHER)


# JSON API вариант (удобно для автоматизации/тестов)
@router.get("/api/settings")
def get_settings_json():
    return JSONResponse(fetch_settings())


@router.post("/api/settings")
def post_settings_json(payload: AdminSettingsModel):
    save_settings(payload)
    return {"ok": True}
