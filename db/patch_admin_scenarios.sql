-- Нормализация схемы admin_scenarios под новый код

DO $$
BEGIN
  -- code -> scenario
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='admin_scenarios' AND column_name='code')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='admin_scenarios' AND column_name='scenario') THEN
    EXECUTE 'ALTER TABLE public.admin_scenarios RENAME COLUMN code TO scenario';
  END IF;

  -- json_schema -> schema_json
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='admin_scenarios' AND column_name='json_schema')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='admin_scenarios' AND column_name='schema_json') THEN
    EXECUTE 'ALTER TABLE public.admin_scenarios RENAME COLUMN json_schema TO schema_json';
  END IF;

  -- prompt -> prompt_template
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='admin_scenarios' AND column_name='prompt')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='admin_scenarios' AND column_name='prompt_template') THEN
    EXECUTE 'ALTER TABLE public.admin_scenarios RENAME COLUMN prompt TO prompt_template';
  END IF;
END$$;

ALTER TABLE public.admin_scenarios
  ADD COLUMN IF NOT EXISTS scenario         text,
  ADD COLUMN IF NOT EXISTS title            text,
  ADD COLUMN IF NOT EXISTS prompt_template  text,
  ADD COLUMN IF NOT EXISTS schema_json      jsonb DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS enabled          boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS created_at       timestamptz DEFAULT now(),
  ADD COLUMN IF NOT EXISTS updated_at       timestamptz DEFAULT now();

-- Уникальность по scenario (если ещё нет)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='admin_scenarios'
      AND constraint_type='UNIQUE' AND constraint_name='ux_admin_scenarios_scenario'
  ) THEN
    EXECUTE 'ALTER TABLE public.admin_scenarios ADD CONSTRAINT ux_admin_scenarios_scenario UNIQUE (scenario)';
  END IF;
END$$;
