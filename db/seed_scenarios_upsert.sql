-- Обновляет (или вставляет) сценарии с prompt_template и schema_json
WITH data AS (
  SELECT * FROM (VALUES
    ('mission','Миссия',
     $$Верни JSON: {"mission":"string"}. Учитывай FACTS и ASTRO_JSON. Кратко, 2–4 предложения.$$,
     $${"type":"object","required":["mission"],"properties":{"mission":{"type":"string"}}}$$::jsonb),

    ('strengths','Сильные',
     $$Верни JSON: {"items":["string",...]} c ровно 10 пунктами. Краткие формулировки.$$,
     $${"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}$$::jsonb),

    ('weaknesses','Слабые',
     $$Верни JSON: {"items":["string",...]} c ровно 10 пунктами. Корректные формулировки.$$,
     $${"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}$$::jsonb),

    ('countries','Страны',
     $$Верни JSON: {"items":["Страна — краткое обоснование",...]} c ровно 5 пунктами. Опирайся на миссию/силы.$$,
     $${"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":5,"maxItems":5}}}$$::jsonb),

    ('business','Бизнес',
     $$Верни JSON: {"items":["Бизнес — почему подходит",...]} c ровно 10 пунктами.$$,
     $${"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}$$::jsonb),

    ('love','Любовь',
     $$Верни JSON: {"love":"string"}. Учитывай пол/имя/контекст. Без медицинских/юридических советов.$$,
     $${"type":"object","required":["love"],"properties":{"love":{"type":"string"}}}$$::jsonb),

    ('finance','Финансовый потенциал',
     $$Верни JSON: {"finance":"string"}. Коротко и по делу.$$,
     $${"type":"object","required":["finance"],"properties":{"finance":{"type":"string"}}}$$::jsonb),

    ('karma','Кармический разбор',
     $$Верни JSON: {"karma":"string"}. Без эзотерических диагнозов, мягко и этично.$$,
     $${"type":"object","required":["karma"],"properties":{"karma":{"type":"string"}}}$$::jsonb),

    ('year','Годовой отчёт',
     $$Верни JSON: {"year":"string"}. Коротко: главные тенденции.$$,
     $${"type":"object","required":["year"],"properties":{"year":{"type":"string"}}}$$::jsonb)
  ) AS v(scenario,title,prompt_template,schema_json)
)
INSERT INTO public.admin_scenarios (scenario, title, prompt_template, schema_json, enabled)
SELECT scenario, title, prompt_template, schema_json, TRUE FROM data
ON CONFLICT (scenario) DO UPDATE
SET title           = EXCLUDED.title,
    prompt_template = EXCLUDED.prompt_template,
    schema_json     = EXCLUDED.schema_json,
    enabled         = TRUE,
    updated_at      = now();
