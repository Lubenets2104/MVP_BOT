-- init_full.sql
-- Generated: 2025-09-08 11:26:03
-- This file consolidates all DB migrations to allow Docker's /docker-entrypoint-initdb.d bootstrap.
-- Idempotent clauses (IF NOT EXISTS / ON CONFLICT) are preserved where possible.
-- Safe to re-run on empty databases; for existing DBs prefer running discrete migrations.

-- ===== BEGIN 000_admin_settings_prepatch.sql =====

-- Подготовка admin_settings (если ещё не было)
CREATE TABLE IF NOT EXISTS admin_settings (
    id                    INTEGER PRIMARY KEY,
    greeting_text         TEXT,
    system_prompt         TEXT,
    enable_channel_gate   BOOLEAN NOT NULL DEFAULT false,
    telegram_channel_id   TEXT,
    telegram_channel_url  TEXT,
    bonus_sections        JSONB,
    enable_referrals      BOOLEAN NOT NULL DEFAULT false,
    referral_bonus_threshold INTEGER NOT NULL DEFAULT 3,
    strict_json           BOOLEAN NOT NULL DEFAULT true,
    enable_compat         BOOLEAN NOT NULL DEFAULT false,
    enable_periodic_horoscopes BOOLEAN NOT NULL DEFAULT false
);

-- ===== END 000_admin_settings_prepatch.sql =====


-- ===== BEGIN 001_core.sql =====

-- Пользователи
CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    tg_id      BIGINT UNIQUE NOT NULL,
    user_name  TEXT,
    gender     TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Сессии (ввод данных и результат расчёта)
CREATE TABLE IF NOT EXISTS sessions (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    system        TEXT,                         -- western|vedic|bazi
    birth_date    DATE,
    birth_time    TIME,
    lat           DOUBLE PRECISION,
    lon           DOUBLE PRECISION,
    tz            TEXT,
    raw_calc_json JSONB,                        -- ASTRO_JSON
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);

-- Канонические факты (кэш ответов)
CREATE TABLE IF NOT EXISTS session_facts (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
    mission     TEXT,
    strengths   JSONB,
    weaknesses  JSONB,
    countries   JSONB,
    business    JSONB,
    love        TEXT,
    extra       JSONB
);

-- Версионирование фактов (для перегенераций)
CREATE TABLE IF NOT EXISTS session_facts_versions (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    scenario    TEXT NOT NULL,
    content     JSONB,
    is_active   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sfv_session ON session_facts_versions(session_id);
CREATE INDEX IF NOT EXISTS ix_sfv_scenario ON session_facts_versions(scenario);

-- История LLM сообщений
CREATE TABLE IF NOT EXISTS llm_messages (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,                 -- system|assistant|user
    content     TEXT NOT NULL,
    scenario    TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);

-- Сводка контекста по сессии
CREATE TABLE IF NOT EXISTS session_summary (
    session_id   INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    summary_text TEXT
);

-- Рефералы
CREATE TABLE IF NOT EXISTS referrals (
    id               SERIAL PRIMARY KEY,
    inviter_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invited_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at       TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_referrals_pair ON referrals (inviter_user_id, invited_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_referrals_invited ON referrals (invited_user_id);

-- Флаг unknown_time для сессий (если ещё нет)
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS unknown_time BOOLEAN;

-- ===== END 001_core.sql =====


-- ===== BEGIN 002_admin_settings_patch.sql =====

-- Дополнительные поля админки (на случай, если таблица уже была)
ALTER TABLE admin_settings
    ADD COLUMN IF NOT EXISTS greeting_text TEXT,
    ADD COLUMN IF NOT EXISTS system_prompt TEXT,
    ADD COLUMN IF NOT EXISTS enable_channel_gate BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS telegram_channel_id TEXT,
    ADD COLUMN IF NOT EXISTS telegram_channel_url TEXT,
    ADD COLUMN IF NOT EXISTS bonus_sections JSONB,
    ADD COLUMN IF NOT EXISTS enable_referrals BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS referral_bonus_threshold INTEGER NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS strict_json BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS enable_compat BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS enable_periodic_horoscopes BOOLEAN NOT NULL DEFAULT false;

-- Гарантируем запись id=1
INSERT INTO admin_settings(id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- ===== END 002_admin_settings_patch.sql =====


-- ===== BEGIN 003_admin_scenarios.sql =====

-- Справочник сценариев: промпт + схема JSON для валидации
CREATE TABLE IF NOT EXISTS admin_scenarios (
    id        SERIAL PRIMARY KEY,
    code      TEXT UNIQUE NOT NULL,     -- 'mission','strengths','weaknesses','countries','business','love','finance','year','karma'
    title     TEXT NOT NULL,
    prompt    TEXT,
    json_schema JSONB
);

-- Примеры-заготовки (ON CONFLICT для идемпотентности)
INSERT INTO admin_scenarios(code, title, prompt, json_schema) VALUES
('mission',   'Миссия',   'Верни {"text": "..."} — краткое описание миссии.', '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}'),
('strengths', 'Сильные',  'Верни {"items":["...x10"]}',                       '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10}},"required":["items"]}'),
('weaknesses','Слабые',   'Верни {"items":["...x10"]}',                       '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10}},"required":["items"]}'),
('countries', 'Страны',   'Верни {"items":["Страна – обоснование",...x5]}',  '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":5}},"required":["items"]}'),
('business',  'Бизнес',   'Верни {"items":["Идея – почему подходит",...x10]}','{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10}},"required":["items"]}'),
('love',      'Любовь',   'Верни {"text":"..."}',                             '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}')
ON CONFLICT (code) DO NOTHING;

-- ===== END 003_admin_scenarios.sql =====


-- ===== BEGIN 004_geocode_cache.sql =====

-- Кэш геокодера
CREATE TABLE IF NOT EXISTS geocode_cache (
    q    TEXT PRIMARY KEY,             -- нормализованный запрос
    lat  DOUBLE PRECISION,
    lon  DOUBLE PRECISION,
    tz   TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

-- ===== END 004_geocode_cache.sql =====


-- ===== BEGIN 009_admin_scenarios_add_code.sql =====

-- Убедимся, что поле code в admin_scenarios есть и уникально (если схема отличалась)
ALTER TABLE admin_scenarios
    ADD COLUMN IF NOT EXISTS code TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_admin_scenarios_code ON admin_scenarios(code);

-- ===== END 009_admin_scenarios_add_code.sql =====


-- ===== BEGIN 010_seed_defaults.sql =====

-- Заполняем дефолтные значения админки (если пусто)
UPDATE admin_settings SET
    greeting_text = COALESCE(greeting_text, 'Привет! Я Астробот ✨'),
    system_prompt = COALESCE(system_prompt, ''),
    enable_channel_gate = COALESCE(enable_channel_gate, false),
    enable_referrals = COALESCE(enable_referrals, false),
    referral_bonus_threshold = COALESCE(referral_bonus_threshold, 3),
    strict_json = COALESCE(strict_json, true),
    enable_compat = COALESCE(enable_compat, false),
    enable_periodic_horoscopes = COALESCE(enable_periodic_horoscopes, false)
WHERE id = 1;

-- Бонус-секции по умолчанию: карма — по подписке; год — по рефералам
UPDATE admin_settings
SET bonus_sections = COALESCE(bonus_sections,
    '{"karma":"channel","year":"referrals"}'::jsonb)
WHERE id = 1;

-- ===== END 010_seed_defaults.sql =====


-- ===== BEGIN 011_add_finance_year.sql =====

-- Добавляем финансовый и годовой разделы в справочник сценариев (если их нет)
INSERT INTO admin_scenarios(code, title, prompt, json_schema) VALUES
('finance', 'Финансовый потенциал', 'Верни {"text":"..."}', '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}'),
('year',    'Годовой отчёт',         'Верни {"text":"..."}', '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}'),
('karma',   'Кармический разбор',    'Верни {"text":"..."}', '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}')
ON CONFLICT (code) DO NOTHING;

-- ===== END 011_add_finance_year.sql =====


-- ===== BEGIN patch_002_memory.sql =====

-- Патч на память/сводку (на случай старых схем)
CREATE TABLE IF NOT EXISTS session_summary (
    session_id   INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    summary_text TEXT
);

-- Таблица сообщений LLM (если не была создана)
CREATE TABLE IF NOT EXISTS llm_messages (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    scenario    TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);

-- Отдельные индексы для ускорения
CREATE INDEX IF NOT EXISTS ix_llm_messages_session ON llm_messages(session_id);
CREATE INDEX IF NOT EXISTS ix_llm_messages_scenario ON llm_messages(scenario);

-- ===== END patch_002_memory.sql =====


-- ===== BEGIN init.sql =====

-- Старый init.sql: сохраняем полезные части (идемпотентно)
CREATE TABLE IF NOT EXISTS settings (
    id    SERIAL PRIMARY KEY,
    key   TEXT UNIQUE NOT NULL,
    value TEXT
);

INSERT INTO settings(key, value)
VALUES ('greeting_text', 'Привет! Я бот. Текст берётся из БД.')
ON CONFLICT (key) DO NOTHING;

-- Индексы и флаги (на случай, если core ещё не применён)
CREATE UNIQUE INDEX IF NOT EXISTS ux_referrals_invited ON referrals (invited_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_referrals_pair ON referrals (inviter_user_id, invited_user_id);

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS unknown_time BOOLEAN;

-- ===== END init.sql =====
