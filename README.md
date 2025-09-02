# Telegram Greeting Bot — микро‑MVP (бот + мини‑админка + БД)


## Стек
- **Bot:** Python, **aiogram 3.7** (polling), asyncpg
- **Web (админка):** FastAPI, Jinja2, asyncpg, HTTP Basic Auth
- **DB:** PostgreSQL 16 (инициализация через `db/init.sql`)
- **Infra:** Docker Compose

## Что умеет
- `/start` — ответ берётся из `settings.greeting_text` в Postgres.
- Мини‑админка на `http://localhost:8080` — меняем `greeting_text`, бот отдаёт новый текст **сразу**, без рестартов.
- `/api/greeting` — JSON ручка, отдаёт текущий текст.

## Быстрый старт

### 1) Подготовка `.env`
Скопируйте `.env.example` → `.env` и заполните:

```env
BOT_TOKEN=ВАШ_ТОКЕН_ОТ_BOTFATHER

POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_DB=appdb
DATABASE_URL=postgresql://app:app@db:5432/appdb

# Basic Auth для админки
ADMIN_USER=admin
ADMIN_PASS=admin
```

> Рекомендация: токен бота не хранить в публичных репозиториях. **Не коммитьте `.env`**.

### 2) Запуск
```bash
docker compose up -d --build
```

Админка: http://localhost:8080  
Бот: отправьте `/start` — получите текст из БД.


# Посмотреть запись в БД
docker compose exec -it db psql -U app -d appdb -c "select * from settings;"

# Перезапуск отдельных сервисов
docker compose restart web
docker compose restart bot

# Остановить / снести с данными
docker compose down
docker compose down -v
```

## Архитектура и структура

```
project/
├─ bot/
│  ├─ app.py                 # aiogram 3.7, polling, SELECT greeting_text
│  ├─ requirements.txt       # aiogram>=3.7,<3.8; asyncpg
│  └─ Dockerfile
├─ web/
│  ├─ app.py                 # FastAPI + HTTP Basic Auth + asyncpg
│  ├─ templates/
│  │  └─ index.html          # форма редактирования greeting_text
│  ├─ requirements.txt
│  └─ Dockerfile
├─ db/
│  └─ init.sql               # таблица settings + дефолтное значение
├─ docker-compose.yml        # db + web + bot
├─ .env.example
└─ README.md
```

**Сервисы в Compose**

- `db` — PostgreSQL 16, healthcheck, volume `dbdata`.
- `web` — FastAPI, порт **8080:8000**, Basic Auth (логин/пароль из `.env`).
- `bot` — aiogram (polling). Для стабильного резолва DNS добавлен блок:
  ```yaml
  dns:
    - 8.8.8.8
    - 1.1.1.1
  ```

## Эндпоинты
- `GET /` — форма редактирования (Basic Auth).
- `POST /` — сохранение текста (Basic Auth).
- `GET /api/greeting` — `{ "greeting_text": "..." }`
- `GET /health` — `{ "status": "ok" }`

## Переменные окружения
- `BOT_TOKEN` — токен Telegram-бота (обязательно).
- `DATABASE_URL` — строка подключения (по умолчанию `postgresql://app:app@db:5432/appdb`).
- `ADMIN_USER`, `ADMIN_PASS` — логин/пароль для Basic Auth в админке.

## Траблшутинг

### Бот молчит
1. Проверь токен:
   ```bash
   curl -s "https://api.telegram.org/bot<ТОКЕН>/getMe"
   ```
   Если `{"ok":false,"error_code":401}` — токен неверный.
2. Удали webhook (если стоял), мы используем polling:
   ```bash
   curl -s "https://api.telegram.org/bot<ТОКЕН>/deleteWebhook?drop_pending_updates=true"
   ```
3. Проверь логи:
   ```bash
   docker compose logs -f bot
   ```



### DNS/интернет внутри контейнера
Если видите `ClientConnectorDNSError: Temporary failure in name resolution`, оставьте в `docker-compose.yml` у `bot` блок `dns:` (как выше) или задайте DNS глобально в Docker Desktop.

Мы публикуем админку на `8080:8000`. Если нужно, смените порт снаружи (например, `9090:8000`).

## Безопасность
- Админка закрыта Basic Auth. Задайте **сложный пароль** (`ADMIN_PASS`).

