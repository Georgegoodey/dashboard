# Lettings Finder

A personal tool for finding rentals. It scrapes Rightmove, stores listings in Postgres, works out public-transport commutes to
your home and work with TfL, and lets you explore everything in a dockable web UI or by asking questions in plain English.
Search areas, addresses, filters and job schedules are all set in the UI and stored in the database.

## Requirements

- Windows with PowerShell, Docker Desktop, Python 3.11+, [uv](https://docs.astral.sh/uv/) (`winget install --id astral-sh.uv`), Node 20+
- Optional: [Ollama](https://ollama.com) for a local chat model, or an Anthropic API key

## Run it

```powershell
Copy-Item .env.example .env              # then edit it (see Configuration)
docker compose up -d db                  # Postgres + PostGIS; Docker Desktop must be running
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Migrations and the job scheduler start with the backend.

## Use it

1. **Settings:** home and work postcodes, commute times, bedroom and rent limits, search areas such as `SW11 SW18`.
2. **Jobs:** *Run now*, or edit each job's schedule. Cadence and active hours are per job.
3. **Properties** and **Map:** filter and sort; click a row for journey legs and rent history.
4. **Chat** (Analysis menu): ask in plain English, for example "cheapest 2 beds under 40 minutes to work".
5. **SQL Console** and **Market Analysis:** read-only SQL, and charts of rent, supply and commutes.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER`, `LLM_MODEL` | `anthropic` (needs `ANTHROPIC_API_KEY`) or `ollama` |
| `LLM_BASE_URL`, `LLM_NUM_CTX` | Ollama address and context window (default `http://localhost:11434`, 8192) |
| `ENVIRONMENT` | `development` (default) or `production`; production needs both database URLs and hides the API docs |
| `DATABASE_URL`, `READONLY_DATABASE_URL` | Postgres connections. Use `127.0.0.1`, not `localhost`. The read-only user must be `lettings_ro` |
| `TFL_APP_KEY` | Optional free TfL key; raises commute lookups from 1 to 5 a second |
| `CORS_ORIGINS` | Allowed browser origins (default `http://localhost:5173`) |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO` and `text` by default; `json` for structured logs |

`GET /health` reports the database, model and TfL key status, with a reason when something is wrong.

## Local chat model (Ollama)

```powershell
winget install Ollama.Ollama
ollama pull qwen3:8b
```

In `.env` set `LLM_PROVIDER=ollama` and `LLM_MODEL=qwen3:8b`, then restart the backend. `qwen3:8b` fits a 10 GB GPU at 8k context.

## Raspberry Pi

To run the app on a Pi, reachable over Tailscale and deployed automatically on merge to `main`, see [deploy/README.md](deploy/README.md).

## Layout

```
backend/app/    api, agents (chat), db, jobs, repositories, services, sources (Rightmove), commute (TfL), charts
backend/migrations/, backend/tests/
frontend/src/   app (shell), components, features (lettings, charts, chat, sql, trace, database), hooks, lib, styles
deploy/         Raspberry Pi set-up
scripts/ci/     checks and release packaging
```

## Develop

From `backend/`:

```powershell
uv run ruff check .
uv run mypy
uv run pytest -m "not integration"     # unit tests, no Docker
uv run pytest                          # everything; integration tests start a throwaway PostGIS container
```

```powershell
cd ..\frontend; npx tsc -b; npm run build
.\scripts\ci\check.ps1                 # all of the above (-Fast skips Docker and the build)
```

Dependencies: edit `backend/pyproject.toml`, then `uv lock` and `uv sync`.
New migration: `uv run alembic revision -m "describe the change"` (SQL in `UPGRADE` and `DOWNGRADE`); it applies on the next start.
Interactive API docs (development only): http://localhost:8000/docs.

## Troubleshooting

- **Slow database connections:** use `127.0.0.1`, not `localhost`.
- **"Database unavailable":** start Docker Desktop, then `docker compose up -d db`.
- **No commutes:** set your work address in Settings and check the commute job; without `TFL_APP_KEY` it is slow.
- **A job shows "blocked":** Rightmove served a challenge. Try again later.
- **Chat says the model is unavailable:** check `GET /health` for `llm_reason`.

## Limitations

- Only Rightmove has an adapter.
- Generated SQL runs as a read-only role limited to four views. There is no login, so keep the API on your own machine or tailnet.
- Chat memory lives in the running backend and clears on restart.
- Scraping may breach a portal's terms. This is a personal, non-profit tool; keep the request pace polite.
