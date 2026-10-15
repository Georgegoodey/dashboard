# Agent Dashboard: lettings finder

A personal tool for finding rentals. It scrapes listings from Rightmove, stores them in Postgres, works out
public-transport commutes to your work and home with the TfL journey planner, and lets you explore everything in a
dockable web UI or by asking questions in plain English (text to SQL).

Everything you choose (search areas, home and work, commute times, price and bedroom limits, how often jobs run) is
entered in the UI and stored in the database. Nothing is hard-coded.

```
Rightmove ──► scraper ──► Postgres + PostGIS ──► curated SQL views ──► UI, charts, chat agent
   TfL    ──► commutes ─┘            ▲
                          scheduler (inside the backend) runs every job
```

## Requirements

- Windows with PowerShell (the commands below are PowerShell), Docker Desktop, Python 3.12, Node 20+
- Optional: [Ollama](https://ollama.com) for a local chat model, or an Anthropic API key

## Quick start

```powershell
Copy-Item .env.example .env              # then edit .env (see Configuration)

docker compose up -d db                  # Postgres 16 + PostGIS; Docker Desktop must be running

cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` and `/health` to port 8000.

The backend applies database migrations on startup, creates the scheduler's tables, and starts the jobs. If Postgres
is not running the API still starts, `/health` reports `database_ok: false`, and the Properties panel says so.

## Using the app

1. **Settings**
   - **Home and work:** a full UK postcode for each. It is geocoded with postcodes.io.
   - **Commute times:** the weekday and time for each journey: morning *arrive by*, evening *leave at*, and a weekend
     trip home. Changing one recomputes its journeys.
   - **Search filters:** minimum and maximum bedrooms and maximum rent (£ per month). They are sent to Rightmove, re-checked
     on what comes back, and applied to homes already stored: homes outside the limits are hidden, not deleted, and come
     back if you loosen a limit.
   - **Search areas:** postcode areas (outcodes) such as `SW11 SW18 TW9`. Rightmove caps one search at about 1,050
     results, which is why searches are per outcode.
2. **Jobs** (the scheduler runs inside the backend): *Run now* fetches immediately. Cadence, daily active hours and
   on/off are editable per job, and every run is recorded with its counts and any error.
3. **Properties:** filter and sort by rent, bedrooms and commute. Click a row for the journey legs, advert and rent history.
4. **Chat** (open from the Assistant menu): ask things like "cheapest 2 beds under 40 minutes to work". The agent writes SQL
   against the curated views only. Each successful query appears above the reply as a chart or table you can switch
   and customise.
5. **SQL Console** and **Vega-Lite** panels: run read-only SQL yourself, as a table or an inferred chart.

## How it works

### Jobs

| Job | Default cadence | Does |
|---|---|---|
| `scrape_rightmove` | every 3 h, 07:00 to 22:00 | Searches each enabled area; stores new listings from the search data, tracks rent changes, withdraws listings missing from 3 complete scrapes |
| `details_rightmove` | every 10 min, 07:00 to 23:00 | Fetches advert pages for new listings (exact postcode, deposit, furnished status, description) in short, time-boxed batches |
| `enrich_pending` | every 30 min | Looks up borough and area codes for new postcodes (postcodes.io) |
| `commute_pending` | every 15 min | Works out TfL journeys for each home and profile that has none yet. Anonymous access is paced at 1 request a second, 5 with a key |

Each job only processes what is pending, so a missed run just means a bigger batch next time. If the PC sleeps or the app
is closed, anything overdue runs once on start ("catch-up"). Scraping is polite: 2 to 4 seconds between requests, and
the job stops on a challenge instead of retrying.

### Data model and the SQL agent

Properties (`properties`) are the canonical homes; each portal advert (`listings`) links to one. Two adverts from the same
portal are never merged, because a development lists many different flats under one address.

The chat agent, SQL console and charts run as the `lettings_ro` role. It can read only these views, in a read-only
transaction with a 10 second timeout:

| View | Contains |
|---|---|
| `v_properties` | One row per active property: rent, bedrooms, borough, days on market, rent against the borough median, commute minutes and fares, distances |
| `v_price_changes` | Every observed rent change |
| `v_property_text` | Advert wording, for searches such as `description ILIKE '%garden%'` |
| `v_job_runs` | Recent scheduler runs |

Column comments in the migrations are read into the model's schema context, so units and meanings are never guessed.

### Charts: one pipeline

`POST /api/chart` runs read-only SQL and returns the rows, column types, column roles (measure, temporal, dimension,
label), per-measure formats and an inferred chart spec (`backend/app/charts/infer.py`). One generic renderer
(`frontend/src/features/charts/auto-chart/`) draws any spec: bar, line, area, combo with a second axis, donut, scatter or
table. The spec editor changes it, and "Reset to inferred" undoes the edits.

To chart something new, write the SQL. Column names are the contract: `rent`, `price`, `amount` format as money; `pct` as
percentage points; `rate`, `discount`, `share` (0 to 1) as percentages; `avg`, `moving`, `rolling` mark a derived line; `*_id`
columns become labels. Add an entry to `features/charts/gallery/gallery.ts` to put it in the Vega-Lite panel.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER`, `LLM_MODEL` | `anthropic` (needs `ANTHROPIC_API_KEY`) or `ollama` |
| `LLM_BASE_URL`, `LLM_NUM_CTX` | Ollama server address and context window (default `http://localhost:11434`, 8192) |
| `DATABASE_URL`, `READONLY_DATABASE_URL` | Postgres connections (read/write and the read-only role). Use `127.0.0.1`, not `localhost` |
| `TFL_APP_KEY` | Optional free key from api-portal.tfl.gov.uk; raises commute lookups from 1 to 5 a second |
| `CORS_ORIGINS` | Allowed browser origins (default `http://localhost:5173`) |
| `DUCKDB_PATH`, `UPLOAD_DIR`, `EMBEDDING_*` | Legacy, only used by the Datasets panel (see Known limitations) |

`GET /health` reports `database_ok`, `llm_configured`, `llm_provider`, `llm_model`, `tfl_key_configured` and, when
something is wrong, the reason.

### Running the chat on a local model (Ollama)

Tested target: RTX 3080 with 10 GB.

```powershell
winget install Ollama.Ollama
ollama pull qwen3:8b
```

Optionally set `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` as user environment variables, then fully quit and
restart Ollama. In `.env` set `LLM_PROVIDER=ollama` and `LLM_MODEL=qwen3:8b` (a commented block is in `.env.example`) and
restart the backend.

| Model | Notes |
|---|---|
| `qwen3:8b` | Recommended: good tool calling, fits 10 GB at 8k context |
| `qwen2.5-coder:7b` | Strong at SQL, weaker at multi-step tool use |
| `llama3.1:8b` | Reliable tool calling, plainer SQL |
| `qwen3:14b` | Only with about 4k context (`LLM_NUM_CTX=4096`); it barely fits 10 GB |

## Project layout

```
backend/
  migrations/      numbered .sql files, applied in order on startup
  tests/           unit tests and real captured Rightmove responses
  app/
    main.py        app startup and shutdown, /health
    scheduler.py   APScheduler wiring (jobs stored in Postgres)
    core/          settings
    db/            Postgres pools and migrations, SQL guard, schema context for the agent
    sources/       one adapter per portal behind a shared interface (Rightmove)
    pipeline/      normalising, ingest, enrichment, search filters
    commute/       TfL journey client and the commute service
    jobs/          job bookkeeping and the jobs themselves
    api/           REST endpoints
    agents/        text-to-SQL chat agent (LangGraph), model factory, tools
    charts/        chart-spec inference
    rag/, db/database.py, db/datasets.py   legacy DuckDB and vector code (see Known limitations)
frontend/src/
  app/             shell: header, dockable workspace, panel registry
  components/      shared UI components
  features/        lettings, charts, chat, sql, trace, datasets (legacy)
  hooks/, lib/, styles/
docker-compose.yml   Postgres + PostGIS
scripts/ci/          pipeline scripts
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /api/status` | Health and counts |
| `/api/areas`, `/api/places/{home\|work}`, `/api/profiles/{slug}`, `/api/filters` | The settings above |
| `GET /api/jobs`, `PUT /api/jobs/{id}`, `POST /api/jobs/{id}/run`, `GET /api/jobs/runs` | Scheduler |
| `GET /api/properties`, `GET /api/properties/{id}` | Filterable list and detail |
| `POST /api/sql`, `POST /api/chart` | Read-only SQL, and SQL with an inferred chart |
| `POST /api/chat` | Streaming chat (server-sent events) |

## Development

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests    # unit tests (parsers, normalisers, TfL, filters, chart inference)
cd frontend; npx tsc -b                                      # type-check
cd frontend; npm run build                                   # production build
```

Add a migration by creating the next numbered file in `backend/migrations/`; it runs on the next backend start. Interactive API
docs are at http://localhost:8000/docs.

## Troubleshooting

- **Slow or stalling database connections:** use `127.0.0.1`, not `localhost`. Docker Desktop maps IPv4 only and `localhost`
  tries IPv6 first.
- **"Database unavailable":** start Docker Desktop, then `docker compose up -d db`.
- **No commutes:** set your work address in Settings and check the *Commutes* job. Without `TFL_APP_KEY` it runs at 1 request
  a second, so a few thousand homes take a while.
- **A job shows "blocked":** Rightmove served a challenge. The job stops by design; try again later and keep the pace polite.
- **Chat says the model is unavailable:** check `GET /health` for `llm_reason`.

## Known limitations

- Only Rightmove has an adapter. OnTheMarket and OpenRent are planned through the same interface, and cross-portal duplicate
  matching is exact only (no fuzzy pass or review queue yet).
- The SQL guard is a keyword check. The real protection is the read-only database role. There is no authentication, so
  keep the API on your own machine.
- The Datasets panel and `/api/datasets`, `/api/documents` and `/api/search` are legacy (DuckDB and vector search from the
  original dashboard). The lettings app does not use them.
- Scraping a portal can breach its terms of use. This is a personal, non-profit tool; keep the request pace polite.
