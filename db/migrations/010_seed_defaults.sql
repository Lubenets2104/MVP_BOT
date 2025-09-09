-- 010_seed_defaults.sql
-- Идемпотентные сид-данные для админки и сценариев (совместимо с наличием NOT NULL на admin_scenarios.scenario)

-- 1) Базовые настройки админки
INSERT INTO admin_settings (
    id, greeting_text,
    enable_referrals, enable_channel_gate, referral_bonus_threshold, telegram_channel_id,
    bonus_sections, enable_compat, enable_periodic_horoscopes
)
VALUES (
    1,
    'Привет! Я твой астро-ассистент. Нажми «Начать», и я построю твою карту 🌟',
    TRUE, TRUE, 3, '@Lub2104',
    '{"karma":"channel","year_forecast":"referrals"}'::jsonb,
    FALSE, FALSE
)
ON CONFLICT (id) DO NOTHING;

-- 2) Сценарии и их JSON-схемы
-- ВАЖНО: включаем колонку scenario (NOT NULL в твоей схеме), дублируем code
INSERT INTO admin_scenarios (code, scenario, title, prompt_template, json_schema)
VALUES
-- Миссия
('mission','mission',
 'Миссия',
 'Сформулируй миссию пользователя на основе ASTRO_JSON и FACTS. Ответ строго JSON { "mission": "..." }.',
 '{"type":"object","properties":{"mission":{"type":"string"}},"required":["mission"]}'),

-- Сильные стороны (10 пунктов)
('strengths','strengths',
 'Сильные стороны',
 'Дай 10 сильных сторон пользователя. Ответ строго JSON { "items": ["...", "..."] } на 10 элементов.',
 '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}},"required":["items"]}'),

-- Слабые стороны (10 пунктов)
('weaknesses','weaknesses',
 'Слабые стороны',
 'Дай 10 слабых сторон пользователя. Ответ строго JSON { "items": ["...", "..."] } на 10 элементов.',
 '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}},"required":["items"]}'),

-- Топ-5 стран
('countries','countries',
 'Топ-5 стран',
 'Подбери топ-5 стран форматом "Страна – краткое обоснование", учитывая миссию/силы. Ответ JSON { "items": ["...x5"] }.',
 '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":5,"maxItems":5}},"required":["items"]}'),

-- Топ-10 бизнесов
('business','business',
 'Топ-10 бизнесов',
 'Подбери 10 бизнес-идей форматом "Идея – почему подходит". Ответ JSON { "items": ["...x10"] }.',
 '{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}},"required":["items"]}'),

-- Личная жизнь (текст)
('love','love',
 'Личная жизнь',
 'Краткий разбор личной жизни. Ответ строго JSON { "text": "..." }.',
 '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}'),

-- Карма (пример раздела, гейтится подпиской)
('karma','karma',
 'Кармический разбор',
 'Краткий кармический разбор. Ответ строго JSON { "text": "..." }.',
 '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}')
ON CONFLICT (code) DO UPDATE
SET title = EXCLUDED.title,
    prompt_template = EXCLUDED.prompt_template,
    json_schema = EXCLUDED.json_schema,
    scenario = COALESCE(EXCLUDED.scenario, admin_scenarios.scenario);

-- 3) Приветствие — если пустое, подставим дефолт
UPDATE admin_settings
SET greeting_text = COALESCE(NULLIF(greeting_text, ''), 'Привет! Я твой астро-ассистент. Нажми «Начать», и я построю твою карту 🌟')
WHERE id = 1;
