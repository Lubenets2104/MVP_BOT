CREATE TABLE IF NOT EXISTS settings (
    id    SERIAL PRIMARY KEY,
    key   TEXT UNIQUE NOT NULL,
    value TEXT
);

INSERT INTO settings(key, value)
VALUES ('greeting_text', 'Привет! Я бот. Текст берётся из БД.')
ON CONFLICT (key) DO NOTHING;
