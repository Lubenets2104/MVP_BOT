import os
import asyncpg
import secrets
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Mini Admin")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/appdb")

templates = Jinja2Templates(directory="templates")
app.state.pool = None

# --- Basic Auth ---
security = HTTPBasic()

def ensure_auth(credentials: HTTPBasicCredentials = Depends(security)):
    user = os.getenv("ADMIN_USER", "admin")
    pwd = os.getenv("ADMIN_PASS", "admin")
    ok = secrets.compare_digest(credentials.username, user) and secrets.compare_digest(credentials.password, pwd)
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

@app.on_event("startup")
async def startup():
    app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

@app.on_event("shutdown")
async def shutdown():
    if app.state.pool:
        await app.state.pool.close()

@app.get("/")
async def index(request: Request, _=Depends(ensure_auth)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = 'greeting_text';"
        )
        greeting = row[0] if row and row[0] else "Привет!"
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "greeting": greeting},
    )

@app.post("/")
async def save_greeting(greeting_text: str = Form(...), _=Depends(ensure_auth)):
    async with app.state.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO settings(key, value)
            VALUES ('greeting_text', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            greeting_text,
        )
    return RedirectResponse(url="/", status_code=303)

@app.get("/api/greeting")
async def get_greeting_api():
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = 'greeting_text';"
        )
        greeting = row[0] if row and row[0] else "Привет!"
    return JSONResponse({"greeting_text": greeting})

@app.get("/health")
async def health():
    return {"status": "ok"}
