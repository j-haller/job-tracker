# Job Tracker – Project Instructions

Oct 5, 2026 · @Jan

## Overview

Build a small, single-user web app that pulls job listings from the jobs.ch JSON API once an hour, stores them in SQLite, and shows them in a React UI where each listing can be rated 1–100 against the owner's skills profile using Claude through the Anthropic API. Jev (hosted) and Laya (local) are documented as alternative rating backends.

These instructions are written for Claude (as coding agent). Follow them in order; where something is marked as an open point, ask the owner instead of guessing.

**In scope for v1**

- One source adapter per job site, each configured on its own; jobs.ch is the first (hourly fetch of all result pages for one fixed search query, plus one detail request per new listing)
- SQLite storage with de-duplication by the jobs.ch listing ID
- React UI: list, filter, sort, detail view, link to the original listing
- Per-listing status (interested, applied, …), changeable from the UI via a POST endpoint
- Rating with Claude (Haiku 5.5), only on a button click: "Rate" per listing and "Rate all unrated"
- One Docker container, reachable only inside the home network

**Out of scope for v1**

- Authentication (LAN only)
- Backups
- Sources other than jobs.ch (the structure is prepared for them), several queries per source, editing source settings in the UI
- Notifications, email, automatic rating after each fetch

**Guiding principle:** lightweight. Few dependencies, one process, one container, no message queue, no ORM, no separate database server.

## Inputs the owner provides

Claude cannot build the fetcher against guessed endpoints. Before milestone 2, the owner hands over the items below; the skills profile can come after setup. Every later source needs the same set: its endpoints or page URLs, sample responses, and a check of its terms of use.

| Item | Needed by | Notes |
| --- | --- | --- |
| Search API URL, incl. the fixed query | Milestone 2 | The full GET URL that returns listings as JSON, up to 300 per page |
| Sample search response (JSON file) | Milestone 2 | Save to `samples/jobsch/search.json`; used to map fields and as a test fixture |
| Detail API URL pattern | Milestone 2 | e.g. `https://…/{id}`; plus any required headers |
| Sample detail response (JSON file) | Milestone 2 | Save to `samples/jobsch/detail.json` |
| Anthropic API key | Milestone 5 | From a separate Claude Console account (the Pro plan does not include API usage); set a monthly spend limit there; starts with `sk-`; goes into `.env`, never into the repo |
| Skills profile | After setup | Plain text or Markdown in `data/profile.md`; include a short "Target roles" line; rating is disabled until it exists |

If a sample response does not contain an obvious field (e.g. no public listing URL), Claude asks rather than constructing one.

## Architecture and stack

One Python process does everything: Flask serves the JSON API and the built React files, and an in-process scheduler runs the hourly fetch. SQLite is a single file on a mounted volume.

&#91;embedded content: architecture · one container, two external APIs\]

The browser talks only to Flask; the scheduler drives the fetcher, and the rating module calls Claude (or the alternative backend, if selected) only when a button is clicked.

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.12, Flask | Owner's choice; small |
| WSGI server | gunicorn, `--workers 1 --threads 4` | One worker so the scheduler and background rating run exactly once |
| Scheduler | APScheduler `BackgroundScheduler` | No cron container needed |
| HTTP client | `requests` | Simple; used for jobs.ch, and for Jev or Laya if selected |
| Database | SQLite via the standard `sqlite3` module, WAL mode | No ORM, no server |
| Frontend | React + TypeScript, built with Vite | Static build served by Flask |
| Frontend libraries | None beyond React; plain CSS | Keeps the bundle small |
| Packaging | One multi-stage Dockerfile, docker compose | Node only in the build stage |

Python dependencies should stay at roughly: `flask`, `gunicorn`, `apscheduler`, `requests`, `anthropic` (official SDK, for rating), plus `pytest` for development. Add nothing else without a clear reason.

**Project structure**

```
jobtracker/
  backend/
    app/
      __init__.py      # create_app(), starts scheduler
      config.py        # reads env vars and sources.toml
      db.py            # connection, schema init, queries
      schema.sql
      sources/
        __init__.py    # registry: adapter name -> class
        base.py        # ListingData, Source interface
        jobsch.py      # first adapter: jobs.ch API
      fetcher.py       # generic fetch run per source, dedup, details
      duplicates.py    # cross-source duplicate check (with 2nd source)
      rating/
        __init__.py    # get_backend() from RATING_BACKEND
        base.py        # RatingResult dataclass, backend interface
        claude.py      # default: Anthropic API, requirement list
        systemone.py   # alternative: Jev or Laya (same request format)
        score.py       # requirement list -> 1..100
        service.py     # rate one listing, store result
      batch.py         # "rate all unrated" background worker
      api.py           # Flask blueprint, /api/*
    tests/
    scripts/
      evaluate.py      # compare backends/models on chosen listings
    requirements.txt
  frontend/
    src/
    package.json
    vite.config.ts
  samples/
    jobsch/            # owner-provided JSON samples, one folder per source; not in git (real contact details)
  data/                # volume: jobs.db, profile.md, sources.toml
  Dockerfile
  docker-compose.yml
  .env.example
  sources.example.toml
  README.md
```

## Configuration

App-wide settings and all secrets come from environment variables, loaded from `.env` by docker compose. Ship a `.env.example` with every variable and no secrets.

| Variable | Example | Purpose |
| --- | --- | --- |
| `SOURCES_CONFIG` | `/data/sources.toml` | Per-source settings (below) |
| `RATING_BACKEND` | `claude` | `claude` (default) or `systemone` (Jev or Laya) |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Secret; never logged, never sent to the frontend |
| `CLAUDE_MODEL` | `claude-haiku-5-5` | Switch to `claude-sonnet-5-5` only if evaluation shows a need |
| `CLAUDE_TIMEOUT_SECONDS` | `60` | Per rating request |
| `JEV_API_URL` | `https://jevmodel.org/v1/systemone` | Only for `systemone`: Jev, or `http://laya:8000/v1/systemone` |
| `JEV_API_KEY` | `sk-…` | Only for `systemone`; secret |
| `JEV_MODEL` | `jev-latest` | Only for `systemone` |
| `PROFILE_PATH` | `/data/profile.md` | Skills profile |
| `DB_PATH` | `/data/jobs.db` | SQLite file |
| `TZ` | `Europe/Zurich` | Timestamps in the UI |
| `PORT` | `8080` | Port inside the container |

Store all timestamps in the database as UTC ISO 8601 strings; convert to local time only in the frontend.

**Per-source settings** live in `data/sources.toml`, read with Python's built-in `tomllib` (no extra dependency). One table per source; the table name is the source key stored in the database.

```toml
[jobsch]
enabled = true
adapter = "jobsch"
interval_minutes = 60
fetch_on_startup = true
request_delay_seconds = 1.0
timeout_seconds = 20
query = "Software Developer"       # the fixed search query, plain text
search_url = "https://…?query={query}"   # {query} is replaced, URL-encoded
detail_url = "https://…/{id}"

[jobsch.headers]
Accept = "application/json"
```

- Common keys (`enabled`, `adapter`, `interval_minutes`, `fetch_on_startup`, `request_delay_seconds`, `timeout_seconds`) are validated by the fetcher; all other keys are passed to the adapter, which validates them itself.
- Secrets never go into this file. A source that needs one names the variable, e.g. `api_key_env = "OTHERSITE_API_KEY"`, and the adapter reads it from the environment.
- Invalid settings disable that source with a clear error in its status; the other sources keep running.
- Changes apply after a container restart.

## Database schema

Three tables: listings, ratings (with history) and fetch runs. The jobs.ch listing ID is the primary key, which makes de-duplication a plain upsert. Enable `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` on every connection.

```sql
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
```

**Status values** (validated in the backend, one list shared with the frontend): `new`, `interested`, `applied`, `interview`, `offer`, `rejected`, `not_interested`. Status and note are never touched by the fetcher.

The current rating of a listing is its newest row in `ratings`. A rating is **stale** when its `profile_hash` differs from the hash of the current profile file.

Schema changes: keep a `schema_version` in `PRAGMA user_version` and apply numbered migrations at startup. No migration tool.

## Job sources

Each job site is its own source adapter: a small module that knows that site's API or pages and turns its results into one common listing format. The fetcher, database, rating and UI only see that common format, so adding a site means one new adapter and one new config block. jobs.ch is the first adapter.

Adapters run inside the same app, not as separate containers, which keeps the project at one process and one image. Each source still has its own settings, schedule, error handling and status, and a failing source never affects the others. If a source ever needs heavy tooling such as a headless browser, that adapter can move into its own container behind the same interface.

**Adapter interface (`sources/base.py`)**

```python
@dataclass
class ListingData:
    external_id: str               # the site's own ID
    title: str
    company: str | None
    location: str | None
    workload: str | None
    published_at: str | None       # ISO 8601
    url: str | None                # public link to the original listing
    description_text: str | None   # None when a detail request is needed
    raw: dict                      # untouched source data

class Source(Protocol):
    key: str                                   # e.g. "jobsch"
    def search(self) -> list[ListingData]: ...                    # one full result set
    def fetch_detail(self, item: ListingData) -> ListingData: ...  # fills description_text
```

Adapters only fetch and map data; they never touch the database. A registry in `sources/__init__.py` maps adapter names to classes, and `sources.toml` decides which sources are enabled.

**One fetch run (per source, generic code in `fetcher.py`)**

1. Take the source's lock and insert a `fetch_runs` row with the source key and status `running`. If that source is still running, skip.
2. Call `search()`. On any error, mark the run `failed`, store the error and stop. No listing changes.
3. Upsert each item by `(source, external_id)`. New rows get `first_seen_at`; all rows get `last_seen_at = now`, `is_active = 1` and refreshed fields. Never overwrite `status`, `note` or ratings.
4. Set `is_active = 0` for listings **of this source** that were not in the result, only after a fully successful search.
5. For new active listings without `description_text`, call `fetch_detail()` with the source's `request_delay_seconds` between calls. Failures go into `detail_error` and count in `detail_attempts`; they are retried on the next runs, at most 3 times (4 attempts in total). If a site keeps answering 429 or 5xx, the remaining details wait for the next run and no attempt is counted.
6. Run the duplicate check for new listings (see below).
7. Finish the run as `ok`, or `partial` if any detail failed, and store the counts. Log one summary line with the source key.

**Scheduling:** one APScheduler job per enabled source, each with its own `interval_minutes`, `max_instances=1` and `coalesce=True`. `POST /api/fetch` takes an optional `source` to run one source manually.

**jobs.ch adapter (`sources/jobsch.py`)**

- Search URL pattern with `{query}`, the `query` value, and a detail URL pattern with `{id}`, all from `sources.toml`. Field mapping lives in `parse_search_item` and `parse_detail`, built from the owner's sample files.
- Strip HTML from the description with the standard library (`html.parser`), keeping paragraph breaks.
- Send a browser-like `User-Agent` and `Accept: application/json`. On HTTP 429 or 5xx, back off (5 s, 15 s, 45 s), then give up for this run.
- The first run makes one detail request per listing; at 1 s apart, the 505 listings seen in the sample take about 8.5 minutes in the background.
- The search response has no public link, so `url` comes from `_links.detail_de.href` in the detail response and stays empty until the detail request succeeds. The description is `template_text` in the detail response, for paid and unpaid listings alike.
- Search results are paged: `rows` per page (at most 300 used), `page` starting at 1, and `numPages` in each response. The adapter sets `page` itself and loads every page, with `request_delay_seconds` between requests. `search_url` in `sources.toml` needs no `page`.
- A failing page, an empty page, or a page without any new listing (paging no longer working) fails the whole search, so no listing becomes inactive because of an incomplete result. A listing appearing on two pages counts once.

**Rules for scraping sources (later)**

- Prefer an official or frontend JSON API over HTML. Check the site's terms of use and `robots.txt` first, and skip the site if scraping is not allowed.
- Parse HTML with the standard library or one small parser. Use a headless browser only when there is no other way, and then in its own container.
- Keep request rates low; a few requests per minute is plenty for hourly runs.
- Expect breakage: a page layout that no longer matches must fail the run loudly, not store empty listings.

**Duplicates across sources.** The same job is often posted on several sites. Within one source, `(source, external_id)` is unique. Across sources, a new listing counts as a duplicate when its normalized company, title and location match an active listing from another source.

- Normalize by lowercasing, removing gender markers such as "(m/w/d)" and workload such as "80–100%", and collapsing whitespace.
- A duplicate gets `duplicate_of` = the ID of the listing seen first. It is not rated separately; the UI shows one row with "also on: …" links. Status and ratings live on the first listing.
- With jobs.ch alone this never triggers. Create the column now and implement the check together with the second source.

**Adding a new source**

1. Check the terms of use; put endpoints or page URLs and sample responses into `samples/<key>/`.
2. Write `sources/<key>.py` implementing `Source`, with tests against the samples.
3. Register it and add a `[<key>]` block to `sources.toml` with `enabled = true`.
4. Restart the container and check the source's status in the header bar.

## Rating with Claude

Each rating is one Messages API call to Claude Haiku 5.5. Claude extracts the listing's requirements and checks each one against the skills profile; the app then computes the 1–100 score from that list in code. Rating only ever happens on a button click.

**Why Claude is the default:** listings are unstructured German or French prose. Claude finds the requirements itself (no checklist to maintain), separates required from nice-to-have, and gives evidence for every match. Jev and Laya return a number only, and Laya would need a hand-maintained checklist (see the alternatives below).

**Access:** an API key from a separate Claude Console account, in `ANTHROPIC_API_KEY`. The Pro plan does not include API usage, and running ratings through Claude Code on the Pro login would share Pro's usage limits with chat and coding. Set a monthly spend limit in the Console.

**Request design (`rating/claude.py`)**

- Model: `CLAUDE_MODEL`, default `claude-haiku-5-5`. Switch to `claude-sonnet-5-5` only if the evaluation shows Haiku misjudging requirements.
- System prompt: the role and the rules below, followed by the full skills profile. The profile should contain a short "Target roles" line.
- User message: the listing as JSON with `title`, `company`, `location`, `workload` and the full `description_text`. No truncation is needed.
- Structured output: define one tool `submit_rating` whose input schema is the result format below, and force it with `tool_choice`. Read the tool input as the result and validate it; on invalid output retry once, then mark the listing as failed.

**Rules in the prompt**

1. List every concrete requirement: education, skills, tools, experience, languages, certifications. Skip soft skills (teamwork, reliability) and company or benefits text.
2. Split combined sentences into separate requirements. Example: "Kenntnisse in PL/SQL und Kenntnisse in Java, REST-API von Vorteil" becomes three items.
3. Mark an item `nice_to_have` when the listing signals it ("von Vorteil", "idealerweise", "wünschenswert", "vorzugsweise", tools given as "z. B." examples); otherwise `required`.
4. Judge `match` only from the profile: `yes`, `partly` or `no`. Never assume a skill the profile does not mention. Put the supporting profile phrase in `evidence` (empty when `no`).
5. List `dealbreakers`: required items the candidate clearly lacks that are central to the role.
6. Set `in_target_field` against the profile's target roles.
7. Write all output in English.

**Result format**

```json
{
  "requirements": [
    {
      "text": "Knowledge of PL/SQL",
      "category": "skill",
      "importance": "required",
      "match": "yes",
      "evidence": "5 years of Oracle PL/SQL development"
    }
  ],
  "dealbreakers": ["No experience with Avaloq"],
  "in_target_field": true,
  "summary": "Strong database background; the core platform (Avaloq) is missing."
}
```

Allowed values: `category` = education, skill, tool, experience, language, certification, other; `importance` = required, nice\_to\_have; `match` = yes, partly, no.

**Score in code (`rating/score.py`)**

```
weight:  required = 3, nice_to_have = 1
value:   yes = 1.0, partly = 0.5, no = 0.0
rating = round(1 + 99 * sum(weight * value) / sum(weight))
caps:    one dealbreaker -> at most 40, two or more -> at most 25
         in_target_field = false -> at most 30
```

Keep the weights and caps as constants so they can be tuned after the evaluation. If no requirements were extracted, store no rating and mark the attempt as failed. Also store `missing_required` (required items with `match` = no) for the table column.

**Rate one listing:** `POST /api/listings/<id>/rate` calls the selected backend synchronously (timeout `CLAUDE_TIMEOUT_SECONDS`; a call takes a few seconds) and returns the new rating. Re-rating adds a new row; old rows stay as history.

**Rate all unrated:** `POST /api/rate-batch` starts one background thread. Scope: active listings without any rating; with `{"include_stale": true}` also listings whose rating is stale. It rates sequentially, keeps progress in memory (`total`, `done`, `failed`, `running`), and allows only one batch at a time. `GET /api/rate-batch` returns progress; `DELETE /api/rate-batch` cancels after the current call.

**Error handling**

- Let the SDK retry rate-limit, overload and server errors (`max_retries=3`).
- Authentication or billing errors stop a running batch and show a banner in the UI.
- Invalid tool output: retry once, then mark the listing as failed and continue the batch.
- No profile file: rating endpoints return 409 with a message; the UI disables the rate buttons.
- Log input and output tokens per rating. Never log the API key or the profile.

**Cost:** roughly 3,000 input and 600 output tokens per listing. At Haiku 5.5's list price ($0.10 / $0.50 per million tokens for prompts up to 100,000 tokens, as of October 2026), 300 listings cost about $0.20; with Sonnet 5.5 ($2 / $10) about $3.60. Check the current [pricing page](https://platform.claude.com/docs/en/about-claude/pricing).

**Privacy:** the profile and each listing are sent to Anthropic with every rating. If that is not acceptable, use the local Laya alternative.

**Evaluation before relying on it**

1. Pick 5–6 listings you know: two clear fits, two clear misses, two in between. Include the Syntegon (Beringen) and Avaloq examples.
2. `scripts/evaluate.py` rates them with the chosen backends and models and writes a CSV; it does not write to the database.
3. Check per listing: were all requirements found, is required vs. nice-to-have right, are `match` and `evidence` correct, and does the score order match your own judgment?
4. Run the same set with Sonnet 5.5. Keep Haiku unless Sonnet is clearly better.

Sources: [Pro plan does not include API usage](https://support.claude.com/en/articles/9876003), [Agent SDK and claude -p on paid plans](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [Haiku 5.5 launch pricing](https://www.usagepricing.com/blueprint/activity/anthropic-2026-10-15-haiku-5-5-launch).

## Alternative: Jev (hosted)

Jev is kept as a documented fallback, selected with `RATING_BACKEND=systemone` and `JEV_API_URL` pointing at jevmodel.org. Each rating is one call with the skills profile and the listing as `state`, and a 10-level `score` question whose result is mapped to 1–100. It returns numbers only, no requirement list.

**What Jev is:** a decision model that returns typed answers (a choice, a score, or a yes/no probability), not text. It does not explain its answer, so the request asks a few extra sub-questions to make a score understandable. API reference: [jevmodel.org docs](https://jevmodel.org/docs/).

**API contract (as documented)**

- `POST https://jevmodel.org/v1/systemone`, header `Authorization: Bearer <JEV_API_KEY>`, JSON body `{model, state, questions}`.
- `state`: string or JSON object, at most 8,000 characters serialized. `questions`: 1–8 named questions; `instructions` at most 1,800 characters; `criteria` at most 2,000 characters.
- `score` questions take an ordered array of 2–10 levels and return a fractional `score` plus `confidence`. `choice` returns `choice`, `probabilities`, `confidence`. `noul` returns a probability of yes.
- Optional `Idempotency-Key` header (≤ 100 chars): a retry with the same key is not billed twice.
- Rate limit: 120 requests per minute per key. Errors: 401 bad key, 402 out of credits, 422 invalid request, 429 rate limit, 502 upstream failure.

**Request design**

`state` is a JSON object, built in `rating/systemone.py`:

```json
{
  "candidate_profile": "<contents of profile.md>",
  "job": {
    "title": "…", "company": "…", "location": "…",
    "workload": "…", "description": "<description_text>"
  }
}
```

Fit it into 8,000 characters by truncating `job.description` (never the profile). If the profile alone exceeds about 3,000 characters, show a warning in the UI that it leaves too little room for listings.

Questions (all in one request; they share the input cost):

| Name | Type | Purpose |
| --- | --- | --- |
| `overall_fit` | score, 10 levels | The 1–100 rating |
| `skills_match` | score, 5 levels | How many required skills the candidate has |
| `seniority` | choice: `under`, `fit`, `over` | Level of the role vs. the candidate |
| `language_ok` | noul | Does the candidate meet the language requirements? |

Draft levels for `overall_fit`, from worst to best (owner may refine): no match / different field · very weak · weak, few overlaps · partial, major gaps · partial, some gaps · decent, learnable gaps · good · strong · very strong · ideal, meets all requirements. Keep the question texts as constants in `rating/systemone.py`, and let the owner try them in the [Jev playground](https://jevmodel.org/playground/) first.

**Mapping to 1–100**

```
rating = clamp(round(1 + 99 * (raw_score - SCORE_MIN) / (SCORE_MAX - SCORE_MIN)), 1, 100)
```

The docs do not state whether the score runs from 0 to levels−1 or from 1 to levels. When this backend is built (milestone 7), Claude calls Jev with an obvious non-match and an obvious perfect match, checks the returned range, and sets `SCORE_MIN`/`SCORE_MAX` accordingly (with a unit test). Store `raw_score` too, so ratings can be remapped later.

**Rate one / rate all:** same endpoints and batch behavior as described under Rating with Claude. Keep at least 0.6 s between calls in a batch (Jev allows 120 requests per minute).

**Stored fields:** `raw_score`, `confidence` and the full answers go into `ratings`; `summary`, `requirements_json` and `missing_required` stay empty for this backend.

**Error handling**

- 429 and 502: retry up to 3 times with backoff (2 s, 8 s, 30 s), reusing the same `Idempotency-Key`.
- 401 and 402: stop immediately (also stops a running batch) and show a clear message in the UI.
- 422: log the error message, mark that listing as failed, continue the batch.
- No profile file: rating endpoints return 409 with a message; the UI disables the rate buttons.
- Never log the API key or the full profile.

**Cost:** Jev bills input tokens only, at $0.042 per million (listed on the [Jev homepage](https://jevmodel.org/)); a full-size request is about 2,500 tokens. Rating 300 listings costs roughly 750,000 tokens, about $0.03. The free 100,000 tokens cover about 40 full-size ratings. Log `usage.input_tokens` per rating; show the `X-Tokens-Remaining` response header in the UI if present.

**Privacy note:** jevmodel.org describes itself as an independent site, not affiliated with TypeSafe AI, the maker of Jev. The skills profile is sent to that service with every rating. The docs say TypeSafe's own SystemOne API accepts the same request body, so switching later only means changing `JEV_API_URL` and the key.

## Alternative: local Laya

Laya is an open-weight decision model that runs in a second container and accepts the same `POST /v1/systemone` request as Jev, so it runs through the same systemone backend as Jev, selected by changing `JEV_API_URL`. Treat it as an experiment: use it only after it agrees with your own judgment at least as often as Claude on a test set.

|  | Jev (hosted) | Laya multilingual (local) |
| --- | --- | --- |
| Where it runs | jevmodel.org | Your server, offline after first download |
| Your profile leaves the server | Yes, with every rating | No |
| Cost | Per input token | Free (Apache-2.0) |
| Speed per request | Network round trip | 193–464 ms on CPU, 32.8 ms on a GPU (short inputs) |
| Out-of-the-box accuracy | Good, per the docs | Near chance without fine-tuning on the authors' benchmark; `score` is its weakest question type |
| Input limit | 8,000 characters | 1,024 tokens by default; up to 8,192 with `max_len=8192` |

**Which checkpoint:** use `laya-multilingual` (322M parameters, \~647 MB). jobs.ch listings are mostly German or French, and the English checkpoint is for English only. Always select multilingual explicitly, since mostly-English text would otherwise be routed to the English checkpoint.

**Hardware (CPU only is enough)**

- CPU: any x86-64 or ARM64 CPU from the last few years; no GPU needed for a few hundred ratings triggered by a button.
- RAM: plan for 3–4 GB free for one checkpoint plus PyTorch (estimate; no official figure).
- Disk: 3–4 GB for weights and Python packages (estimate).
- GPU (optional): any NVIDIA card with 4 GB VRAM; set `LAYA_DEVICE=cuda` and add the GPU to the compose service.

**Extra container**

```yaml
  laya:
    build: ./laya              # python:3.12-slim + pip install "laya[serve]" (CPU PyTorch wheel)
    restart: unless-stopped
    environment:
      - LAYA_DEVICE=cpu
      - LAYA_PRELOAD=1
      - LAYA_API_KEY=${LAYA_API_KEY}
      - USE_TF=0
      - HF_HOME=/models
    volumes:
      - ./models:/models       # keeps the downloaded weights across restarts
    expose:
      - "8000"                 # internal Docker network only, never under ports:
```

The Laya server has no authentication unless `LAYA_API_KEY` is set, so set it and do not publish its port. The first start downloads the weights and takes a minute or two to load them; the app's status endpoint should report Laya as unavailable until then.

**Open item before building:** check whether `laya-serve` lets you force the multilingual checkpoint and `max_len=8192` (environment variable or request field). If it does not, write a \~40-line Flask wrapper in `laya/` that calls `Router().predict(state, questions, model="multilingual", max_len=8192)` and exposes the same `POST /v1/systemone` endpoint.

**App changes**

- Config: `JEV_API_URL=http://laya:8000/v1/systemone`, `JEV_API_KEY` = the `LAYA_API_KEY` value. Store `laya-multilingual` in `ratings.model` so ratings from both backends stay distinguishable.
- Input size: keep the 8,000-character cap on `state`. That is roughly 2,000–3,000 tokens, inside the range where the authors measured stable accuracy (up to about 4,000 tokens).
- `language_ok`: ask it as a two-option `choice` (keys `A`/`B`, the yes/no wording in the descriptions) instead of `noul`. The model card reports that `noul` can get stuck on a confident "no". Use the `choice` form for Jev too, so the code is identical.
- Score mapping: the card's example returns 1.84 for a 3-level score, which suggests a range of 0 to levels−1. Confirm with the same extreme-case test as for Jev.
- Errors: Laya returns 401 and 422 like Jev; there is no 402 or 429. Allow a longer timeout (60 s) for the first request after a container start.
- "Rate all unrated": no pause between calls needed for a local backend; keep it sequential.
- Probabilities: Laya ships over-confident, so show `confidence` in the UI but do not use it for any automatic decision.

**How to use Laya here: one check per requirement.** Laya cannot extract requirements, since it never generates text, and a single overall score is its weakest question type. Instead:

- Keep the skills profile as a checklist of 30–60 items with your level (`good` / `basic` / `none`), including common skills in your field that you lack (e.g. Avaloq).
- Per listing, one call asks for every checklist item "Does this job ask for X?" as a `choice`: required / nice to have / not mentioned.
- Code compares the answers with your levels and computes the score with the same logic as `rating/score.py`.
- Add a gate question "Is this mainly a role in \[target fields\]?", and flag a listing for manual review when "Does the job require a specific product or platform as a core skill?" is yes but no checklist product matched.

Weak spots to test: required vs. nice-to-have inside one sentence, and requirements that are not on the checklist.

**How to evaluate it**

1. Use the evaluation set from Rating with Claude (5–6 listings you rated yourself on 1–100).
2. Run `scripts/evaluate.py` with Claude and Laya on the same listings; it writes a CSV and does not touch the database.
3. Compare how far each backend is from your ratings and whether both put the same listings on top.
4. Switch to Laya only if it is clearly not worse. Otherwise keep Claude and revisit after fine-tuning.

**Fine-tuning (later, not v1):** Laya improves a lot with fine-tuning on your own labeled decisions. The authors provide a notebook that runs on Kaggle's free GPUs. Your own status changes and manual ratings could become that training data.

Sources: [Laya model card on Hugging Face](https://huggingface.co/convaiinnovations/laya), [Laya overview by brain function collapse](https://brainfunctioncollapse.com/laya/).

## Backend API

A small JSON API under `/api`; everything else serves the React build (with a fallback to `index.html`). All responses are JSON; errors use `{"error": "<message>"}` with a fitting status code.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/listings` | – | All listings without `description_text`, `search_json`, `detail_json`; each with its current rating fields (`rating`, `rated_at`, `is_stale`, summary, missing required count) |
| GET | `/api/listings/<id>` | – | One listing incl. description, the current requirement list and rating history |
| POST | `/api/listings/<id>/status` | `{"status": "applied", "note": "…"}` (note optional) | Updated listing; 400 on unknown status |
| POST | `/api/listings/<id>/rate` | – | New rating; 409 if no profile, 502/402/401 passed through as clear messages |
| POST | `/api/rate-batch` | `{"include_stale": false}` | Batch progress; 409 if a batch is already running |
| GET | `/api/rate-batch` | – | `{running, total, done, failed, started_at, last_error}` |
| DELETE | `/api/rate-batch` | – | Cancels the running batch |
| POST | `/api/fetch` | – | Starts a fetch run in the background for all enabled sources, or one with ?source=\<key>; 409 if that source is already running |
| GET | `/api/status` | – | Per source: enabled, config error, last fetch run and next scheduled run; also, profile present (yes/no, hash, length), active rating backend and model, listing counts |
| GET | `/api/meta` | – | Status values list and other constants the UI needs |

**Filtering and sorting are done in the frontend.** A few hundred to a few thousand rows is small enough to load at once, and it keeps the backend trivial. If the list ever grows past \~5,000 rows, add `?active=1` server-side first.

All write endpoints are plain POST/DELETE without auth (LAN only). Validate IDs and inputs anyway, and use parameterized SQL everywhere.

Listing IDs have the form `<source>:<external_id>` and are URL-encoded in paths. Duplicates from other sources are not returned as separate rows; the list and detail endpoints attach them to the first listing as `also_on` (source and URL). Asking for a duplicate's own ID returns 404, since status and ratings live on the first listing.

In the status endpoint, `status` is required and a missing `note` leaves the stored note unchanged. `status_updated_at` only moves when the status really changes.

## Frontend

One page: a header bar, a filter bar, a sortable table, and a detail panel that opens beside the table (below it on narrow screens). React + TypeScript with plain CSS; state in `useState`/`useReducer`, data via `fetch`. No router, no UI kit, no state library.

**Header bar**

- Last fetch per source: time, status (ok / partial / failed) and counts; red when the last run failed or is older than twice that source's interval
- "Fetch now" button
- "Rate all unrated" button with a checkbox "include stale"; while running, a progress bar (done / total, failed) and a Cancel button
- Warning banner when the profile is missing or too long, or when the rating backend reports an authentication or billing error

**Table columns:** rating (colored badge; grey "–" when unrated, marked when stale), missing required (count), title, company, source, location, workload, published, first seen, status (inline dropdown). New listings since the last visit are highlighted (remember the last visit time in `localStorage`).

**Filters** (combinable, kept in the URL query string so a filtered view can be bookmarked):

- Text search over title and company
- Status, multi-select (default: all except `not_interested` and `rejected`)
- Rating range (min / max), and "unrated only"
- "Show inactive" toggle (default off)
- Location text; source (multi-select)

**Sorting:** click a column header; toggles ascending/descending. Default: rating descending, unrated last, then first seen descending.

**Detail panel**

- Title, company, location, workload, published date, link "Open original" (new tab), plus "also on" links for duplicates from other sources
- Rating block: score, summary, dealbreakers, model, rated at, stale marker; "Rate" / "Re-rate" button with a spinner, disabled while a request runs
- Requirement list: one row per requirement with importance (required / nice to have), a match badge (yes / partly / no) and the evidence from the profile; required items you lack first
- Status dropdown and a note field, saved via `POST /api/listings/<id>/status`
- Full description as plain text
- Rating history (small list)

**Behavior**

- Poll `GET /api/rate-batch` every 2 s while a batch runs, and refresh the affected rows; poll `/api/status` every 60 s otherwise.
- Optimistic status updates; roll back and show an error toast if the POST fails.
- Keyboard: arrow up/down to move through the table, Enter to open details. Nice to have, not required for v1.
- During development, the Vite dev server proxies `/api` to Flask.

## Docker deployment

One image, two build stages: Node builds the React app, then a slim Python image runs gunicorn and serves the built files. Target image size: under 200 MB.

```dockerfile
# --- build frontend ---
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- runtime ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /src/dist ./static
RUN useradd -r -u 1000 app && mkdir /data && chown app /data
USER app
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/status')"
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8080", "app:create_app()"]
```

```yaml
services:
  jobtracker:
    build: .
    container_name: jobtracker
    restart: unless-stopped
    env_file: .env
    environment:
      - TZ=Europe/Zurich
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
```

**LAN only:** do not forward the port on the router. If the server has a public IP or several interfaces, bind explicitly, e.g. `"192.168.1.10:8080:8080"`.

**Operations**

- Start: `docker compose up -d --build`
- Logs: `docker logs -f jobtracker`
- Add or change the skills profile: edit `data/profile.md`; no restart needed (read at rating time).
- Change a source's query or settings, or add a source: edit `data/sources.toml`, then `docker compose restart`.
- Change app settings or secrets: edit `.env`, then `docker compose up -d`.

The README explains these steps in this order, plus how to run the backend and frontend locally without Docker.

## Build order and acceptance

Build in six milestones, plus two optional later ones; each ends with something the owner can run and check. Stop after each milestone and summarize what changed.

1. **Skeleton:** repo structure, Flask app factory, `GET /api/status`, Vite React app showing "hello", Dockerfile and compose. *Done when* `docker compose up` serves the page on port 8080.
2. **Sources and fetcher:** schema, `sources/base.py`, registry, `sources.toml` loading, the jobs.ch adapter built from the owner's sample files, generic `fetcher.py`, one scheduler job per source, `POST /api/fetch`. *Done when* a run fills the DB, a second run adds no duplicates, a failed search changes nothing, and a failing dummy source in the tests does not affect jobs.ch.
3. **Listings API:** list, detail, status endpoints. *Done when* status changes persist and survive the next fetch.
4. **Frontend:** header, filters, sorting, table, detail panel, status dropdown. *Done when* every filter and sort works on the real data.
5. **Claude rating:** `rating/claude.py`, `score.py`, `service.py`, single rating, requirement list in the detail panel, `scripts/evaluate.py`. *Done when* the evaluation set gives requirement lists and scores the owner agrees with.
6. **Rate all unrated:** background batch, progress, cancel, error stops. *Done when* a batch over all unrated listings finishes, shows progress, and an invalid API key stops it cleanly.
7. **Optional, later:** `rating/systemone.py` for Jev or Laya, only if the owner decides to test an alternative.
8. **Later: second source:** a new adapter plus `duplicates.py`. *Done when* the same job from two sites shows as one row with an "also on" link.

**Tests (pytest, kept small)**

- Field mapping per adapter against `samples/<key>/`; skipped when the samples are not present, since they are not in git
- Upsert keyed on `(source, external_id)`: no duplicates; `status` and `note` survive a re-fetch; missing IDs become inactive only within the same source
- Source isolation: a failing adapter or invalid config block leaves the other sources running
- Score computation: weights, partial matches, dealbreaker and target-field caps, empty requirement list
- Result validation: a valid `submit_rating` tool call, missing fields, unknown enum values
- Claude client with mocked responses: success, invalid output, authentication error, rate limit, overload

No frontend test suite in v1; check the UI by hand against the milestone list.

**Code conventions:** type hints in Python, short functions, no global DB connection (one connection per request/thread), all constants (status values, the rating prompt and result schema, score weights and caps) in one place each.

## Open points and assumptions

These are defaults chosen in this document; the owner can change any of them before the matching milestone.

- [x] jobs.ch: the owner takes responsibility for calling the API hourly for personal use; the samples needed no cookies or special headers
- [x] jobs.ch: the search response has no public listing URL; it comes from the detail response (`_links.detail_de.href`)
- [ ] Sources: which site comes second, and does it have an API or would it need scraping?
- [ ] Claude: create the Console account and API key, and set a monthly spend limit
- [ ] Claude: tune the weights and caps in `rating/score.py` after the evaluation
- [ ] Claude: keep all output in English, or requirement texts in the listing's language?
- [ ] Profile: write it in Markdown, with a short "Target roles" line
- [ ] Status list: `new`, `interested`, `applied`, `interview`, `offer`, `rejected`, `not_interested`; add or rename now, since it is stored as text
- [ ] Rating on fetch stays off; could become an option later (about $0.20 per 300 listings with Haiku)
- [ ] Inactive listings are kept forever; no cleanup in v1
- [ ] Alternatives: build the Jev or Laya backend only if privacy or cost becomes a concern
