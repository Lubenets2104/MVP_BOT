-- USERS
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  tg_id BIGINT UNIQUE NOT NULL,
  user_name TEXT,
  gender TEXT,
  invited_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id);

-- SESSIONS
CREATE TABLE IF NOT EXISTS sessions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  system TEXT NOT NULL CHECK (system IN ('western','vedic','bazi')),
  birth_date DATE NOT NULL,
  birth_time TIME,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  tz TEXT,
  raw_calc_json JSONB,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON sessions(user_id, is_active);

-- REFERRALS
CREATE TABLE IF NOT EXISTS referrals (
  id BIGSERIAL PRIMARY KEY,
  inviter_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  invited_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(invited_user_id)
);

-- ADMIN SETTINGS
CREATE TABLE IF NOT EXISTS admin_settings (
  key TEXT PRIMARY KEY,
  value JSONB
);
INSERT INTO admin_settings(key,value) VALUES
 ('greeting_text', to_jsonb('Привет! Я Астробот ✨'::text)),
 ('system_prompt', to_jsonb('Жёсткие правила и стиль ответа…'::text)),
 ('bonus_sections', '{"karma":"channel","year_forecast":"referrals"}'::jsonb),
 ('telegram_channel_id', to_jsonb(''::text)),
 ('referral_bonus_threshold', to_jsonb(3)),
 ('enable_referrals', to_jsonb(true)),
 ('enable_channel_gate', to_jsonb(true))
ON CONFLICT (key) DO NOTHING;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='settings') THEN
    INSERT INTO admin_settings(key,value)
    SELECT 'greeting_text', to_jsonb(value)
    FROM settings WHERE key='greeting_text'
    ON CONFLICT (key) DO NOTHING;
  END IF;
END $$;

-- SESSION FACTS
CREATE TABLE IF NOT EXISTS session_facts (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  mission TEXT,
  strengths JSONB,
  weaknesses JSONB,
  countries JSONB,
  business JSONB,
  love TEXT,
  extra JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_session_facts_session ON session_facts(session_id);

-- VERSIONS
CREATE TABLE IF NOT EXISTS session_facts_versions (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  scenario TEXT NOT NULL,
  content JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  is_active BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_facts_versions_session ON session_facts_versions(session_id);

-- LLM MESSAGES
CREATE TABLE IF NOT EXISTS llm_messages (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('system','user','assistant')),
  scenario TEXT,
  content TEXT NOT NULL,
  schema_ok BOOLEAN,
  input_tokens INT,
  output_tokens INT,
  status TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_llm_session ON llm_messages(session_id);

-- SESSION SUMMARY
CREATE TABLE IF NOT EXISTS session_summary (
  session_id BIGINT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  summary_text TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);
