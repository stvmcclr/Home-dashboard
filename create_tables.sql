-- ============================================================
-- Home Intelligence Tables for Supabase
-- Run this in the Supabase SQL Editor:
--   https://supabase.com/dashboard/project/pfmmkyoygialzysjqksp/sql
-- ============================================================

-- Camera/sensor observations
CREATE TABLE IF NOT EXISTS home_observations (
  id              INTEGER PRIMARY KEY,
  timestamp       TIMESTAMPTZ,
  source          TEXT,
  source_type     TEXT,
  location        TEXT,
  summary         TEXT,
  confidence      REAL,
  model_version   TEXT,
  entities        JSONB DEFAULT '[]'::jsonb
);

-- Create index for fast recent-data queries
CREATE INDEX IF NOT EXISTS home_observations_ts_idx ON home_observations(timestamp DESC);

-- Intelligence insights/alerts
CREATE TABLE IF NOT EXISTS home_insights (
  id            INTEGER PRIMARY KEY,
  timestamp     TIMESTAMPTZ,
  insight_type  TEXT,
  severity      TEXT,
  summary       TEXT,
  acted_on_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS home_insights_ts_idx ON home_insights(timestamp DESC);

-- Current home state (single row, id = 'current')
CREATE TABLE IF NOT EXISTS home_state (
  id            TEXT PRIMARY KEY DEFAULT 'current',
  who_is_home   JSONB DEFAULT '[]'::jsonb,
  active_rooms  JSONB DEFAULT '[]'::jsonb,
  lights_on     JSONB DEFAULT '[]'::jsonb,
  music_playing JSONB DEFAULT '[]'::jsonb,
  last_motion   JSONB DEFAULT '{}'::jsonb,
  last_updated  TIMESTAMPTZ
);

-- Enable Row Level Security (optional, allows anon read)
ALTER TABLE home_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE home_insights     ENABLE ROW LEVEL SECURITY;
ALTER TABLE home_state        ENABLE ROW LEVEL SECURITY;

-- Allow anonymous reads (dashboard is public-facing)
CREATE POLICY "Public read home_observations" ON home_observations FOR SELECT USING (true);
CREATE POLICY "Public read home_insights"     ON home_insights     FOR SELECT USING (true);
CREATE POLICY "Public read home_state"        ON home_state        FOR SELECT USING (true);

-- Allow service role (sync script) to write
CREATE POLICY "Service write home_observations" ON home_observations FOR ALL USING (true);
CREATE POLICY "Service write home_insights"     ON home_insights     FOR ALL USING (true);
CREATE POLICY "Service write home_state"        ON home_state        FOR ALL USING (true);
