# Job Tracker

Personal, single-user web app for the home network. It fetches job listings (jobs.ch first), stores them in SQLite, and shows them in a React UI where each listing can be rated 1–100 against a skills profile using Claude.

The full specification is in [`project-instructions.md`](project-instructions.md).

## Run with Docker

1. Copy the example configs:
   ```bash
   cp .env.example .env
   mkdir -p data && cp sources.example.toml data/sources.toml
   ```
2. Fill in `.env` (API key, later) and `data/sources.toml` (jobs.ch URLs, later).
3. Start: `docker compose up -d --build`
4. Open `http://<server>:8080`.
5. Logs: `docker logs -f jobtracker`

**LAN only:** do not forward port 8080 on the router. If the server has a public IP or several interfaces, bind explicitly in `docker-compose.yml`, e.g. `"192.168.1.10:8080:8080"`.

## Operations

- **Skills profile:** edit `data/profile.md`. No restart needed (read at rating time).
- **Source settings or a new source:** edit `data/sources.toml`, then `docker compose restart`.
- **App settings or secrets:** edit `.env`, then `docker compose up -d`.

## Local development (without Docker)

Backend (from `backend/`):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app:create_app run --port 8080 --no-reload
.venv/bin/pytest
```

Use `--no-reload`: the reloader would start the scheduler twice. Set `DB_PATH`, `PROFILE_PATH` and `SOURCES_CONFIG` to local paths (defaults point to `/data`).

Frontend (from `frontend/`; the dev server proxies `/api` to port 8080):

```bash
npm install
npm run dev
npm run build
```
