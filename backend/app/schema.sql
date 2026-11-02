CREATE TABLE IF NOT EXISTS listings (
  id                TEXT PRIMARY KEY,        -- "<source>:<external_id>", e.g. "jobsch:12345"
  source            TEXT NOT NULL,           -- source key from sources.toml
  external_id       TEXT NOT NULL,           -- the site's own ID
  duplicate_of      TEXT REFERENCES listings(id),  -- set for cross-source duplicates
  title             TEXT NOT NULL,
  company           TEXT,
  location          TEXT,
  workload          TEXT,                    -- e.g. "80-100%", if available
  published_at      TEXT,
  url               TEXT,                    -- public link to the original listing
  description_text  TEXT,                    -- plain text, HTML stripped
  search_json       TEXT NOT NULL,           -- raw item from search response
  detail_json       TEXT,                    -- raw detail response
  detail_fetched_at TEXT,
  detail_error      TEXT,                    -- last error, NULL if ok
  detail_attempts   INTEGER NOT NULL DEFAULT 0,  -- failed detail requests so far
  first_seen_at     TEXT NOT NULL,
  last_seen_at      TEXT NOT NULL,
  is_active         INTEGER NOT NULL DEFAULT 1,  -- 0 = no longer in search results
  status            TEXT NOT NULL DEFAULT 'new',
  status_updated_at TEXT,
  note              TEXT,
  UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS ratings (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id        TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  backend           TEXT NOT NULL,           -- claude | systemone
  model             TEXT NOT NULL,           -- e.g. claude-haiku-5-5, jev-latest
  rating            INTEGER NOT NULL,        -- 1..100, computed in code
  summary           TEXT,                    -- one or two sentences (Claude)
  requirements_json TEXT,                    -- requirement list (Claude)
  dealbreakers_json TEXT,                    -- list of strings (Claude)
  missing_required  INTEGER,                 -- count of required items with match = no
  raw_score         REAL,                    -- score as returned (Jev/Laya only)
  confidence        REAL,                    -- Jev/Laya only
  response_json     TEXT NOT NULL,           -- full raw response
  profile_hash      TEXT NOT NULL,           -- sha256 of profile.md at rating time
  input_tokens      INTEGER,
  output_tokens     INTEGER,
  created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ratings_listing ON ratings(listing_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fetch_runs (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  source         TEXT NOT NULL,              -- source key
  started_at     TEXT NOT NULL,
  finished_at    TEXT,
  status         TEXT NOT NULL,              -- running | ok | partial | failed
  found          INTEGER,                    -- listings in search response
  new            INTEGER,
  details_ok     INTEGER,
  details_failed INTEGER,
  error          TEXT
);
