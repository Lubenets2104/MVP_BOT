-- 004_geocode_cache.sql
-- Кэш геокодера (нормализованный ключ q, уникальный).
CREATE TABLE IF NOT EXISTS public.geocode_cache (
  q TEXT PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  tz  TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- На будущее: быстрый выбор по свежести
CREATE INDEX IF NOT EXISTS idx_geocode_cache_updated ON public.geocode_cache (updated_at DESC);
