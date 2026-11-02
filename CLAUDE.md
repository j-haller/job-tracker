# Job Tracker

Personal, single-user web app on a home server (LAN only, one Docker container). It fetches job listings from job sites through one adapter per source (jobs.ch first), stores them in SQLite, and shows them in a React UI. On a button click, Claude (Anthropic API) extracts each listing's requirements, checks them against the owner's skills profile, and the app computes a 1–100 fit score.

## Source of truth

- `project-instructions.md` is the full specification: architecture, schema, API, UI, rating, build order. Read the relevant section before starting any piece of work.
- Build milestone by milestone, in the order of "Build order and acceptance". Stop after each milestone and summarize what changed and how the owner can verify it.
- Items under "Open points and assumptions" are not decided. Ask the owner instead of guessing.
- If the code needs to deviate from the spec, say so and ask. When the owner agrees to a change, update `project-instructions.md` in the same piece of work.

## Stack

- Backend: Python 3.12, Flask, gunicorn (`--workers 1 --threads 4`), APScheduler, `requests`, `anthropic`, SQLite via the standard `sqlite3` module.
- Frontend: React + TypeScript, built with Vite, plain CSS. Served as static files by Flask.
- Config: `.env` for app-wide settings and secrets; `data/sources.toml` for per-source settings (read with `tomllib`).
- Deployment: one multi-stage Dockerfile, `docker-compose.yml`, data volume at `/data`.

## Commands

These are the intended commands. Update this section when they exist or change.

```bash
# Backend (from backend/)
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app:create_app run --port 8080 --no-reload
.venv/bin/pytest

# Frontend (from frontend/), dev server proxies /api to :8080
npm install
npm run dev
npm run build

# Whole app
docker compose up -d --build
docker logs -f jobtracker
```

## Hard rules

- **Stay lightweight.** Do not add dependencies beyond the stack above without asking: no ORM, no task queue, no UI kit, no router or state library, no YAML parser.
- **One process.** The scheduler and the "rate all" batch run in-process; never raise gunicorn workers above 1. With the Flask dev server, use `--no-reload` (the reloader would start the scheduler twice).
- **Sources are isolated.** Adapters in `backend/app/sources/` only fetch and map data into `ListingData`; they never touch the database. No source-specific code in the fetcher, API or UI. A failing source must never affect another source.
- **The fetcher never overwrites** `status`, `note` or ratings. Listings become inactive only within their own source, and only after a fully successful search.
- **Rating happens only on an explicit user action** ("Rate" or "Rate all unrated"), never automatically. The 1–100 score is computed in `rating/score.py` from the requirement list, never taken from the model directly.
- **No real external calls without asking.** Tests use fixtures from `samples/<key>/` and mocked HTTP and Anthropic responses. Ask the owner before calling jobs.ch, any other job site, or the Anthropic API, even for a quick check.
- **Secrets:** never commit `.env`, `data/` or API keys; never log API keys or the skills profile; never send keys to the frontend. Do not export `ANTHROPIC_API_KEY` in the shell; the app reads it from `.env`.
- **Data safety:** never delete `data/jobs.db` or run destructive SQL without asking. Schema changes go through numbered migrations tracked in `PRAGMA user_version`.

## Conventions

- Python: type hints, dataclasses, short functions; one SQLite connection per request or thread; parameterized SQL only.
- Store timestamps as UTC ISO 8601 strings; convert to local time (`Europe/Zurich`) only in the frontend.
- Keep each set of constants in one place: status values, the rating prompt and result schema, score weights and caps.
- Listing IDs have the form `<source>:<external_id>` (e.g. `jobsch:12345`); URL-encode them in paths.
- TypeScript in strict mode; all API calls go through one small fetch wrapper.
- Code, comments, UI text and docs are in English. Listing content is usually German or French.
- Never write the German `ß`; always use `ss` (e.g. `Strasse`, `muss`), and convert `ß` to `ss` in any text you write. Raw sample data in `samples/` stays untouched.

## Gotchas

- The first jobs.ch run makes one detail request per listing at `request_delay_seconds` apart (about 8.5 minutes for the 505 listings seen in the sample). Do not lower the delay to speed up development; use the sample files instead.
- The rating call forces the `submit_rating` tool to get structured output. Validate the tool input; retry once on invalid output, then mark the listing as failed.
- Let the Anthropic SDK handle retries (`max_retries=3`). Authentication or billing errors must stop a running batch.
- A rating is stale when its `profile_hash` differs from the hash of the current `data/profile.md`.
