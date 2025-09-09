from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.status import HTTP_303_SEE_OTHER
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import os, json, re
from psycopg import connect  # psycopg[binary]

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------- DB DSN ----------
def get_dsn() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    user = os.getenv("POSTGRES_USER", "app")
    pwd  = os.getenv("POSTGRES_PASSWORD", "app")
    db   = os.getenv("POSTGRES_DB", "appdb")
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

# ---------- helpers ----------
SAFE_KEY_RE = re.compile(r"[^a-z0-9_]+")
def sanitize_key(s: str) -> str:
    s = (s or "").strip().lower().replace(" ", "_")
    s = SAFE_KEY_RE.sub("", s)
    return s[:40]

def dumps_pretty(obj: Any) -> str:
    try:
        return json.dumps(obj or {}, ensure_ascii=False, indent=2)
    except Exception:
        return "{}"

# ---------- data access (schema: scenario/title/prompt_template/schema_json/enabled) ----------
def fetch_scenarios() -> List[Dict[str, Any]]:
    with connect(get_dsn()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
              scenario,
              title,
              prompt_template,
              schema_json,
              enabled,
              updated_at
            FROM admin_scenarios
            ORDER BY scenario
        """)
        rows = cur.fetchall() or []
    out = []
    for scenario, title, prompt_template, schema_json, enabled, updated_at in rows:
        out.append({
            "scenario": scenario,
            "title": title,
            "prompt_template": (prompt_template or ""),
            "schema_json": _parse_jsonb(schema_json),
            "enabled": bool(enabled),
            "updated_at": updated_at,
        })
    return out


def fetch_scenario(scenario: str) -> Optional[Dict[str, Any]]:
    with connect(get_dsn()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT scenario, title, prompt_template, schema_json, enabled, updated_at
            FROM admin_scenarios
            WHERE scenario = %s
            LIMIT 1
        """, (scenario,))
        row = cur.fetchone()
    if not row:
        return None

    scenario, title, prompt_template, schema_json, enabled, updated_at = row
    return {
        "scenario": scenario,
        "title": title,
        "prompt_template": (prompt_template or ""),
        "schema_json": _parse_jsonb(schema_json),
        "enabled": bool(enabled),
        "updated_at": updated_at,
    }


def upsert_scenario(
    scenario: str,
    title: str,
    prompt_template: str,
    schema_json: Dict[str, Any],
    enabled: bool,
) -> None:
    with connect(get_dsn()) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO admin_scenarios (scenario, title, prompt_template, schema_json, enabled, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s, now())
            ON CONFLICT (scenario) DO UPDATE SET
              title = EXCLUDED.title,
              prompt_template = EXCLUDED.prompt_template,
              schema_json = EXCLUDED.schema_json,
              enabled = EXCLUDED.enabled,
              updated_at = now()
        """, (scenario, title, prompt_template, json.dumps(schema_json), enabled))
        conn.commit()

def _parse_jsonb(v: Any) -> Any:
    """Аккуратно привести jsonb из psycopg к обычному dict/list."""
    if v is None or v == "":
        return {}
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, (bytes, bytearray, memoryview)):
        try:
            v = bytes(v).decode("utf-8", "ignore")
        except Exception:
            return {}
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


# ---------- Pydantic (JSON API) ----------
class ScenarioModel(BaseModel):
    scenario: str = Field(..., pattern=r"^[a-z0-9_]{2,40}$")
    title: str = Field(..., min_length=1, max_length=120)
    prompt_template: str = Field("", min_length=0)
    schema_json: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

# ---------- HTML ----------
@router.get("/scenarios", response_class=HTMLResponse)
def scenarios_list(request: Request):
    items = fetch_scenarios()
    return templates.TemplateResponse("scenarios.html", {"request": request, "items": items})

@router.get("/scenarios/new", response_class=HTMLResponse)
def scenario_new(request: Request):
    s = {"scenario": "", "title": "", "prompt_template": "", "schema_json": {}, "enabled": True, "updated_at": None}
    return templates.TemplateResponse(
        "scenario_detail.html",
        {"request": request, "s": s, "is_new": True, "schema_json_str": dumps_pretty({})}
    )

@router.post("/scenarios/new")
def scenario_new_post(
    request: Request,
    scenario_key: str = Form(...),
    title: str = Form(...),
    prompt_template: str = Form(""),
    schema_json: str = Form("{}"),
    enabled: Optional[str] = Form(None),
):
    key = sanitize_key(scenario_key)
    if not key or not re.fullmatch(r"^[a-z0-9_]{2,40}$", key):
        raise HTTPException(status_code=400, detail="Некорректный ключ (a-z, 0-9, '_', 2–40).")
    try:
        schema_obj = json.loads(schema_json or "{}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"schema_json должен быть валидным JSON: {e}")
    upsert_scenario(key, title.strip(), prompt_template.strip(), schema_obj, bool(enabled))
    return RedirectResponse(url=f"/scenarios/{key}", status_code=HTTP_303_SEE_OTHER)

@router.get("/scenarios/{scenario}", response_class=HTMLResponse)
def scenario_detail(request: Request, scenario: str):
    s = fetch_scenario(scenario) or {"scenario": scenario, "title": "", "prompt_template": "", "schema_json": {}, "enabled": True, "updated_at": None}
    return templates.TemplateResponse(
        "scenario_detail.html",
        {"request": request, "s": s, "is_new": False, "schema_json_str": dumps_pretty(s.get("schema_json") or {})}
    )

@router.post("/scenarios/{scenario}")
def scenario_save(
    request: Request,
    scenario: str,
    title: str = Form(...),
    prompt_template: str = Form(""),
    schema_json: str = Form("{}"),
    enabled: Optional[str] = Form(None),
):
    key = sanitize_key(scenario)
    if not key:
        raise HTTPException(status_code=400, detail="Некорректный ключ сценария.")
    try:
        schema_obj = json.loads(schema_json or "{}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"schema_json должен быть валидным JSON: {e}")
    upsert_scenario(key, title.strip(), prompt_template.strip(), schema_obj, bool(enabled))
    return RedirectResponse(url=f"/scenarios/{key}", status_code=HTTP_303_SEE_OTHER)

# ---------- JSON API ----------
@router.get("/api/scenarios")
def api_scenarios_list():
    return JSONResponse(fetch_scenarios())

@router.get("/api/scenarios/{scenario}")
def api_scenario_get(scenario: str):
    s = fetch_scenario(scenario)
    if not s:
        raise HTTPException(status_code=404, detail="scenario not found")
    return JSONResponse(s)

@router.post("/api/scenarios/{scenario}")
def api_scenario_upsert(scenario: str, payload: ScenarioModel):
    key = sanitize_key(scenario or payload.scenario)
    upsert_scenario(key, payload.title, payload.prompt_template, payload.schema_json, payload.enabled)
    return {"ok": True, "scenario": key}
