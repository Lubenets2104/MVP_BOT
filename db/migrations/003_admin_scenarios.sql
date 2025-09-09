-- 003_admin_scenarios.sql
-- Таблица для хранения промптов и JSON-схем по сценариям LLM.

CREATE TABLE IF NOT EXISTS public.admin_scenarios (
  scenario TEXT PRIMARY KEY,            -- mission | strengths | weaknesses | countries | business | love
  title TEXT,
  prompt_template TEXT,                 -- текст промпта (инструкции) для LLM
  schema_json JSONB,                    -- ожидаемая JSON-схема ответа (для валидации)
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Заполним дефолтами, если пусто. ЯВНОЕ приведение к jsonb.
INSERT INTO public.admin_scenarios (scenario, title, prompt_template, schema_json)
SELECT v.scenario, v.title, v.prompt_template, (v.schema_json)::jsonb
FROM (
  VALUES
    ('mission',    'Миссия',
     'Верни JSON: {"mission":"string"}. Учитывай FACTS и ASTRO_JSON. Кратко, 2–4 предложения.',
     '{"type":"object","required":["mission"],"properties":{"mission":{"type":"string"}}}'),

    ('strengths',  'Сильные стороны',
     'Верни JSON: {"items":["string",...]} c ровно 10 пунктами. Краткие формулировки.',
     '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}'),

    ('weaknesses', 'Слабые стороны',
     'Верни JSON: {"items":["string",...]} c ровно 10 пунктами. Корректные формулировки.',
     '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}'),

    ('countries',  'Страны для жизни',
     'Верни JSON: {"items":["Страна — краткое обоснование",...]} c ровно 5 пунктами. Опирайся на миссию/силы.',
     '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":5,"maxItems":5}}}'),

    ('business',   'Топ-10 бизнесов',
     'Верни JSON: {"items":["Бизнес — почему подходит",...]} c ровно 10 пунктами.',
     '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}'),

    ('love',       'Личная жизнь',
     'Верни JSON: {"love":"string"}. Учитывай пол/имя/контекст. Без медицинских/юридических советов.',
     '{"type":"object","required":["love"],"properties":{"love":{"type":"string"}}}')
) AS v(scenario,title,prompt_template,schema_json)
WHERE NOT EXISTS (SELECT 1 FROM public.admin_scenarios s WHERE s.scenario = v.scenario);

CREATE INDEX IF NOT EXISTS idx_admin_scenarios_enabled ON public.admin_scenarios(enabled);
