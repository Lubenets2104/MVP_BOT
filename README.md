
# Астробот (Telegram, aiogram + PostgreSQL + LLM)

> MVP‑бот, который собирает дату/время/место рождения, строит карту (через внешний калькулятор), генерирует разборы (LLM) и поддерживает **growth‑механики**: рефералки и доступ по подписке на канал. Настройки и тексты управляются через БД/админку.

---

## ✨ Функции

- Онбординг: имя → пол → система астрологии (Западная/Ведическая/БаЦзы) → дата/время/город.
- Геокодинг города → координаты и таймзона; перевод в UTC; расчёт карты (внешний модуль).
- Первичный разбор после расчёта: **10 сильных** и **10 слабых**.
- Разделы (сценарии) главного меню:
  - `mission` — Миссия
  - `love` — Личная жизнь
  - `finance` — Финансовый потенциал
  - `countries` — Топ‑5 стран для жизни
  - `business` — Топ‑10 бизнес‑идей
  - `karma` — Кармический разбор
  - `year` — Годовой отчёт
- **Кэш + версии** ответов: `session_facts` хранит данные и историю версий (`add_fact_version`).
- **Гейты (замочки)** на разделы:
  - `referral` — откроется при достижении порога приглашённых.
  - `channel` — откроется при подписке на канал.
  - что именно закрыто — задаётся **динамически** в `bonus_sections` (JSON) в админке.
- Реферальная система: deep‑link вида `?start=ref<tg_id>`, учёт приглашённых в таблице `referrals`.
- Поддержка «✅ Я подписался» (универсально для любого сценария).

---

## 📦 Структура (основное)

```
project/
├─ bot/
│  ├─ handlers.py        # основной флоу и меню, гейты, сценарии
│  ├─ states.py          # FSM‑состояния (Flow)
│  ├─ keyboards.py       # Inline‑кнопки
├─ services/
│  ├─ db.py              # доступ к Postgres, upsert/queries, версии фактов, summary
│  ├─ geocode.py         # геокодинг города → (lat, lon, tz)
│  ├─ astro.py           # перевод в UTC, вызов внешнего/встроенного калькулятора
│  ├─ llm.py             # генерация текстов/списков (OpenAI), mock‑режимы
├─ scenarios/
│  └─ __init__.py        # enum SCN и служебное
├─ web/                  # (если подключено) простая админка/страницы
├─ docker-compose.yml
├─ requirements.txt
└─ README.md             # этот файл
```

> Конкретные пути/имена могут отличаться; смотри свой репозиторий.

---

## ⚙️ Быстрый старт

### 1) .env (создать рядом с `docker-compose.yml`)

> **Не публикуйте реальные ключи!** Пример ниже — шаблон, замените на свои значения.

```dotenv
# Telegram
BOT_OWNER_ID=805687695
BOT_TOKEN=<PUT_NEW_TELEGRAM_BOT_TOKEN_HERE>

# DB
POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_DB=appdb
DATABASE_URL=postgresql://app:app@db:5432/appdb

# OpenAI
OPENAI_API_KEY=<PUT_NEW_OPENAI_KEY_HERE>
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0.2
OPENAI_TOP_P=1.0

# Прочее
SPINNER_STICKER_ID=5361837567463399422
SPINNER_REFRESH_SEC=4.5
LOG_LEVEL=INFO
TZ=Europe/Moscow
```

Рекомендации:
- **никогда** не добавляйте `.env` в git (`.gitignore`).
- `TZ` влияет на логи/время по умолчанию (на расчёты карты не влияет, там берётся tz из геокодинга).

### 2) Запуск в Docker

```bash
docker compose up --build -d
docker compose logs -f bot
```

> Убедитесь, что `docker-compose.yml` пробрасывает переменные окружения из `.env` в контейнер бота/веб‑сервиса.

### 3) Локальный запуск (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export $(cat .env | xargs)  # Windows: set переменные руками или через dotenv
python -m bot
```

---

## 🗄️ База данных

Минимально используются таблицы (названия/схема могут отличаться в вашем проекте):
- `users (id, tg_id, user_name, gender, ...)`
- `sessions (id, user_id, system, raw_calc_json, is_active, ...)`
- `session_facts (session_id, mission, love, countries, business, strengths, weaknesses, extra jsonb, ...)`
- `session_summary (session_id, summary_text)`
- `admin_settings (id=1, key/value поля)` — глобальные настройки
- `admin_scenarios (scenario, title, enabled, ...)` — включённые сценарии в меню
- `referrals (inviter_user_id, invited_user_id, created_at)`

> Инициализация схемы может выполняться через скрипты или автоматически в `services.db`. Если у вас есть миграции — примените их перед запуском.

### Полезные SQL‑шпаргалки (через docker)

```bash
docker compose exec db psql -U app -d appdb -c "\dt"
docker compose exec db psql -U app -d appdb -c "SELECT COUNT(*) FROM users;"
```

Очистить/починить кэш годового отчёта:
```sql
-- удалить ключ year из extra
UPDATE session_facts SET extra = COALESCE(extra,'{}'::jsonb) - 'year'
WHERE session_id = <SID>;
```

---

## 🔐 Growth‑механики и админ‑настройки

Все флаги читаются из `admin_settings`. Настроить можно через вашу веб‑админку или via SQL.

### 1) Рефералка

Ключи:
- `enable_referrals` — `true/false` (вкл/выкл систему)
- `referral_bonus_threshold` — порог приглашённых (например `3`)

Реф‑ссылка формируется автоматически как:
```
https://t.me/<bot_username>?start=ref<tg_id>
```

### 2) Гейты разделов

Главный ключ — `bonus_sections` (JSON). Пример:
```json
{
  "love": "referral",
  "finance": "channel",
  "countries": "channel"
}
```
Допустимые значения:  
- `"referral"` — раздел откроется после достижения порога приглашений.  
- `"channel"` — раздел откроется после подписки на канал.

Для `channel` также нужны ключи:
- `enable_channel_gate = true`
- `telegram_channel_id` — например `"@my_channel"` или `-1001234567890`
- `telegram_channel_url` — (опционально) явная ссылка, если нет username

> Кнопка «✅ Я подписался» работает **универсально**: `callback_data="gate:recheck:<scenario>"`. Хендлер автоматически вернёт пользователя в нужный раздел, если подписка подтверждена.

### 3) Какие разделы можно закрывать?

Любые из: `mission`, `love`, `business`, `finance`, `countries`, `karma`, `year`.  
Вы просто добавляете нужную пару в `bonus_sections`.

---

## 🤖 Сценарии и генерация

- Для отображения сценариев в меню используется таблица `admin_scenarios` (`list_enabled_scenarios()`).
- Генерация происходит через `services.llm`:
  - Тексты: `generate_text_or_mock(...)` (`mission`, `love`, `finance`, `karma`, `year`)
  - Списки: `generate_list_or_mock(...)` (`strengths`, `weaknesses`, `business`, `countries`)
  - Универсальный путь: `run_scenario(session_id, code)` — вернёт `dict` (используется в регене/кастомных).
- Сохранение:
  - `mission`, `love` → поля в `session_facts` (строка)
  - `finance`, `karma`, `year` → `session_facts.extra[code]` (строка)
  - списки (`strengths`, `weaknesses`, `business`, `countries`) → `{"items":[...]}`
  - прочее/кастом → как есть в `extra[code]`
- Для истории и «перегенерации» используется `add_fact_version(...)` + `rebuild_session_summary(...)`.

---

## 🧭 Пользовательский сценарий (flow)

1. `/start` — бот создаёт/находит пользователя, привязывает рефералку (если была).
2. Имя → Пол → Система → Дата → Время/«не знаю» → Город.
3. Геокодинг и расчёт карты → генерация **10/10** → показ главного меню.
4. Пользователь выбирает разделы. Если раздел «закрыт», показывается экран гейта:
   - `channel` — предложит подписаться и нажать «✅ Я подписался».
   - `referral` — отправит в «Пригласи друга → бонус» с прогрессом.
5. Любой раздел можно «♻️ Пересчитать» (кнопка внутри сценария). Работает с гейтами.

---

## 🧪 Проверка и отладка

- **Гейты не открываются после подписки**  
  Убедитесь, что `telegram_channel_id` корректен:  
  - `@username` — можно строить ссылку и проверять членство.  
  - `-100...` (приватный без username) — ссылку не строим, но членство проверяется по ID.  
  Нажимайте «✅ Я подписался». Если всё ещё закрыто — бот не видит вас в участниках (проверьте права бота и задержку Telegram).

- **Рефералка не считает приглашённых**  
  Проверьте, что приглашённые заходили **по вашей** ссылке, и что `register_referral(...)` не падает (см. логи).  
  Порог берётся из `referral_bonus_threshold`.

- **В годовом отчёте показывается `{"year": ...}`**  
  В `handlers.py` добавлена нормализация/распаковка и перезапись кэша. Если видите старое поведение — очистите ключ:
  ```sql
  UPDATE session_facts SET extra = coalesce(extra, '{}'::jsonb) - 'year' WHERE session_id=<SID>;
  ```
  и запросите раздел заново.

- **Aiogram: "message is not modified"**  
  Ловится и подавляется в `safe_edit(...)`. Это не ошибка, просто Telegram не меняет идентичный текст.

- **Кастомный спиннер**  
  Укажите `SPINNER_STICKER_ID` (custom emoji id). Если нет — бот пошлёт обычный 🔮.

---

## 🔒 Безопасность

- Ревокуйте и **никогда не публикуйте** реальные `BOT_TOKEN` и `OPENAI_API_KEY`.
- Добавьте `.env` в `.gitignore`.
- Ограничьте доступ к БД и логам.

---

## 🛠️ Команды разработчика (psql под Docker)

```bash
# Подключиться к БД
docker compose exec db psql -U app -d appdb

# Посмотреть включённые сценарии меню
SELECT scenario, title, enabled FROM admin_scenarios ORDER BY scenario;

# Проверить настройки
SELECT * FROM admin_settings WHERE id=1;

# Поставить гейт для разделов (пример)
UPDATE admin_settings
SET bonus_sections = '{
  "love": "referral",
  "finance": "channel"
}';
```

---

## 🙋 FAQ

**Как сделать, чтобы бонусом по рефералке был не «Годовой отчёт», а «Личная жизнь»?**  
В `admin_settings.bonus_sections` поставьте:
```json
{"love": "referral"}
```
и включите `enable_referrals=true` с нужным `referral_bonus_threshold`.

**Как включить доступ по каналу для нескольких разделов?**  
```json
{"finance": "channel", "countries": "channel"}
```
а также `enable_channel_gate=true` и заполните `telegram_channel_id`/`telegram_channel_url`.

**Где редактировать тексты/заголовки сценариев?**  
В таблицах/админке: `admin_scenarios` (заголовки/включение), `admin_settings` (тексты приветствия, промпты, др.).

---

## 🧩 Версии и кэширование

- Каждая генерация пишется в историю (`add_fact_version`), можно сделать интерфейс отката.
- В `session_facts.extra` текстовые сценарии лежат «плоскими» строками, списочные — под `{"items":[...]}`.
- Для очищения кэша конкретного сценария в `extra`:
  ```sql
  UPDATE session_facts SET extra = COALESCE(extra,'{}'::jsonb) - '<code>' WHERE session_id=<SID>;
  ```

---

## 📄 Лицензия

Укажите лицензию в корне репозитория (например, MIT) или удалите этот раздел.
