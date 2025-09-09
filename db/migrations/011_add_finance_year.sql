-- 011_add_finance_year.sql
-- Добавляем недостающие сценарии: finance (текст) и year (текст)

INSERT INTO admin_scenarios (code, scenario, title, prompt_template, json_schema)
VALUES
-- Финансы
('finance','finance',
 'Финансовый потенциал',
 'Сформируй сжатый разбор финансового потенциала пользователя на основе ASTRO_JSON и FACTS. '
 'Учитывай сильные/слабые стороны. Формат ответа строго JSON: { "text": "..." }.',
 '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}'),

-- Годовой прогноз
('year','year',
 'Годовой прогноз',
 'Дай краткий годовой прогноз с ключевыми периодами/акцентами. Учитывай миссию и сильные стороны. '
 'Формат ответа строго JSON: { "text": "..." }.',
 '{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}')
ON CONFLICT (code) DO UPDATE
SET scenario = EXCLUDED.scenario,
    title = EXCLUDED.title,
    prompt_template = EXCLUDED.prompt_template,
    json_schema = EXCLUDED.json_schema;

-- Подчистим/допишем bonus_sections для гейтов (по желанию):
-- year через рефералы, finance через подписку (если включён канал-гейт)
UPDATE admin_settings
SET bonus_sections = COALESCE(bonus_sections, '{}'::jsonb)
                      || jsonb_build_object('year','referral');

UPDATE admin_settings
SET bonus_sections = bonus_sections || jsonb_build_object('finance','channel')
WHERE COALESCE(enable_channel_gate, true);
