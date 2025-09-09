CREATE TABLE IF NOT EXISTS settings (
    id    SERIAL PRIMARY KEY,
    key   TEXT UNIQUE NOT NULL,
    value TEXT
);

INSERT INTO settings(key, value)
VALUES ('greeting_text', 'Привет! Я бот. Текст берётся из БД.')
ON CONFLICT (key) DO NOTHING;
CREATE UNIQUE INDEX IF NOT EXISTS ux_referrals_invited ON referrals (invited_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_referrals_pair ON referrals (inviter_user_id, invited_user_id);
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS unknown_time boolean;

ALTER TABLE llm_messages
  ADD COLUMN IF NOT EXISTS schema_ok boolean;
CREATE INDEX IF NOT EXISTS ix_llm_messages_schema_ok
  ON llm_messages (schema_ok);
