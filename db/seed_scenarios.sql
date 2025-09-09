INSERT INTO public.admin_scenarios (scenario, title, prompt_template, schema_json, enabled)
SELECT v.scenario, v.title, v.prompt_template, v.schema_json::jsonb, TRUE
FROM (VALUES
  ('mission','Миссия',
   'Верни JSON: {"mission":"string"}. Учитывай FACTS и ASTRO_JSON. Кратко, 2–4 предложения.',
   '{"type":"object","required":["mission"],"properties":{"mission":{"type":"string"}}}'),

  ('strengths','Сильные стороны',
   'Верни JSON: {"items":["string",...]} c ровно 10 пунктами. Краткие формулировки.',
   '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}'),

  ('weaknesses','Слабые стороны',
   'Верни JSON: {"items":["string",...]} c ровно 10 пунктами. Корректные формулировки.',
   '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}'),

  ('countries','Страны для жизни',
   'Верни JSON: {"items":["Страна — краткое обоснование",...]} c ровно 5 пунктами. Опирайся на миссию/силы.',
   '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":5,"maxItems":5}}}'),

  ('business','Топ-10 бизнесов',
   'Верни JSON: {"items":["Бизнес — почему подходит",...]} c ровно 10 пунктами.',
   '{"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"string"},"minItems":10,"maxItems":10}}}'),

  ('love','Личная жизнь',
   'Верни JSON: {"love":"string"}. Учитывай пол/имя/контекст. Без медицинских/юридических советов.',
   '{"type":"object","required":["love"],"properties":{"love":{"type":"string"}}}'),

  ('finance','Финансы',
   'Верни JSON: {"finance":"string"}. Кратко и по делу.',
   '{"type":"object","required":["finance"],"properties":{"finance":{"type":"string"}}}'),

  ('karma','Карма',
   'Верни JSON: {"karma":"string"}. Без эзотерических диагнозов, мягко и этично.',
   '{"type":"object","required":["karma"],"properties":{"karma":{"type":"string"}}}'),

  ('year','Прогноз на год',
   'Верни JSON: {"year":"string"}. Коротко: главные тенденции.',
   '{"type":"object","required":["year"],"properties":{"year":{"type":"string"}}}')
) AS v(scenario,title,prompt_template,schema_json)
ON CONFLICT (scenario) DO NOTHING;
