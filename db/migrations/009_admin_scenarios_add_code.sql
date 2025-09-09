-- 009_admin_scenarios_add_code.sql
-- Приводим admin_scenarios к ожидаемой схеме (добавляем code/prompt_template/json_schema, если их нет)

DO $$
BEGIN
  -- Добавим колонку code, если её нет
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'admin_scenarios' AND column_name = 'code'
  ) THEN
    ALTER TABLE admin_scenarios ADD COLUMN code TEXT;

    -- Попытаемся заполнить code из существующих колонок (name/slug/scenario), если они есть
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='admin_scenarios' AND column_name='name') THEN
      EXECUTE 'UPDATE admin_scenarios SET code = name WHERE code IS NULL';
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='admin_scenarios' AND column_name='slug') THEN
      EXECUTE 'UPDATE admin_scenarios SET code = slug WHERE code IS NULL';
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='admin_scenarios' AND column_name='scenario') THEN
      EXECUTE 'UPDATE admin_scenarios SET code = scenario WHERE code IS NULL';
    END IF;

    -- Уникальный индекс на code (если ещё нет)
    IF NOT EXISTS (
      SELECT 1 FROM pg_indexes
      WHERE tablename = 'admin_scenarios' AND indexname = 'admin_scenarios_code_key'
    ) THEN
      EXECUTE 'CREATE UNIQUE INDEX admin_scenarios_code_key ON admin_scenarios(code)';
    END IF;
  END IF;

  -- Добавим prompt_template, если нет
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'admin_scenarios' AND column_name = 'prompt_template'
  ) THEN
    ALTER TABLE admin_scenarios ADD COLUMN prompt_template TEXT;
  END IF;

  -- Добавим json_schema, если нет
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'admin_scenarios' AND column_name = 'json_schema'
  ) THEN
    ALTER TABLE admin_scenarios ADD COLUMN json_schema JSONB;
  END IF;
END $$;
