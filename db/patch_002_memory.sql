-- LLM сообщения (лог запросов/ответов)
CREATE TABLE IF NOT EXISTS llm_messages (
  id           BIGSERIAL PRIMARY KEY,
  session_id   BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  scenario     TEXT   NOT NULL,
  role         TEXT   NOT NULL CHECK (role IN ('system','user','assistant')),
  content      TEXT   NOT NULL,
  schema_ok    BOOLEAN,
  tokens_in    INTEGER,
  tokens_out   INTEGER,
  created_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_llm_messages_session ON llm_messages(session_id, scenario, created_at DESC);

-- Краткая сводка контекста по сессии
CREATE TABLE IF NOT EXISTS session_summary (
  session_id   BIGINT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  summary_text TEXT NOT NULL,
  updated_at   TIMESTAMP NOT NULL DEFAULT now()
);

-- Версии фактов (для «перегенерировать»)
CREATE TABLE IF NOT EXISTS session_facts_versions (
  id          BIGSERIAL PRIMARY KEY,
  session_id  BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  scenario    TEXT   NOT NULL,
  content     JSONB  NOT NULL,        -- для текстовых: {"text":"..."}; для списков: {"items":[...]}
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMP NOT NULL DEFAULT now()
);
-- одна активная версия на (session_id, scenario)
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_active
ON session_facts_versions(session_id, scenario)
WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_fact_versions_session ON session_facts_versions(session_id, scenario, created_at DESC);
