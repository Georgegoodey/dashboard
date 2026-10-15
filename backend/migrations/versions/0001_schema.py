"""Lettings schema: sources, areas, properties, listings, commutes, scheduler state.

Revision ID: 0001
Revises: 
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
-- Lettings schema v1: sources, areas, canonical properties, per-portal listings, commutes, scheduler state.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE sources (
    id      serial PRIMARY KEY,
    name    text UNIQUE NOT NULL,
    kind    text NOT NULL DEFAULT 'scrape',          -- scrape | email | manual
    enabled boolean NOT NULL DEFAULT true
);
INSERT INTO sources (name, kind, enabled) VALUES
    ('rightmove', 'scrape', true), ('onthemarket', 'scrape', false), ('openrent', 'scrape', false), ('manual', 'manual', true);

-- Postcode areas you want searched. Edited in the Settings panel; nothing is hard-coded.
CREATE TABLE search_areas (
    id         serial PRIMARY KEY,
    label      text NOT NULL,
    outcode    text UNIQUE NOT NULL,                 -- e.g. SW11
    source_ids jsonb NOT NULL DEFAULT '{}'::jsonb,   -- cached portal location ids, e.g. {"rightmove": "OUTCODE^2497"}
    enabled    boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- The canonical home. One property can be advertised on several portals (listings).
CREATE TABLE properties (
    id            bigserial PRIMARY KEY,
    uprn          text,
    address       text,                      -- display address as advertised
    address_norm  text NOT NULL,
    postcode      text,
    outcode       text,
    borough       text,
    geom          geography(Point, 4326),
    bedrooms      int,
    bathrooms     int,
    property_type text,
    floor_area_m2 numeric,
    epc_rating    text,
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX properties_geom_idx ON properties USING gist (geom);
CREATE INDEX properties_postcode_idx ON properties (postcode);
CREATE INDEX properties_address_trgm_idx ON properties USING gin (address_norm gin_trgm_ops);

-- One advert on one source.
CREATE TABLE listings (
    id                bigserial PRIMARY KEY,
    property_id       bigint NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
    source_id         int NOT NULL REFERENCES sources (id),
    source_listing_id text NOT NULL,
    url               text,
    first_seen        timestamptz NOT NULL DEFAULT now(),
    last_seen         timestamptz NOT NULL DEFAULT now(),
    status            text NOT NULL DEFAULT 'active',          -- active | withdrawn
    missed_scrapes    int NOT NULL DEFAULT 0,
    rent_pcm          numeric(10, 2),
    rent_pw           numeric(10, 2),
    deposit           numeric(10, 2),
    furnished         text,
    let_type          text,
    min_term_months   int,
    available_from    date,
    agent_name        text,
    headline          text,
    description       text,
    description_tsv   tsvector GENERATED ALWAYS AS
                      (to_tsvector('english', coalesce(headline, '') || ' ' || coalesce(description, ''))) STORED,
    key_features      jsonb,
    raw               jsonb,
    content_hash      text,
    detail_fetched_at timestamptz,
    pipeline_status   text NOT NULL DEFAULT 'scraped',         -- scraped | enriched | commuted
    UNIQUE (source_id, source_listing_id)
);
CREATE INDEX listings_property_idx ON listings (property_id);
CREATE INDEX listings_status_idx ON listings (status);
CREATE INDEX listings_tsv_idx ON listings USING gin (description_tsv);

CREATE TABLE listing_price_history (
    id          bigserial PRIMARY KEY,
    listing_id  bigint NOT NULL REFERENCES listings (id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL DEFAULT now(),
    rent_pcm    numeric(10, 2),
    status      text
);
CREATE INDEX price_history_listing_idx ON listing_price_history (listing_id, observed_at);

-- Possible duplicates across portals, awaiting a decision in the UI.
CREATE TABLE match_candidates (
    id        bigserial PRIMARY KEY,
    listing_a bigint NOT NULL REFERENCES listings (id) ON DELETE CASCADE,
    listing_b bigint NOT NULL REFERENCES listings (id) ON DELETE CASCADE,
    score     real NOT NULL,
    state     text NOT NULL DEFAULT 'pending',                 -- pending | merged | rejected
    UNIQUE (listing_a, listing_b)
);

-- Your home and work (entered in the UI).
CREATE TABLE places (
    id         serial PRIMARY KEY,
    kind       text NOT NULL CHECK (kind IN ('home', 'work')),
    label      text NOT NULL,
    address    text,
    postcode   text,
    geom       geography(Point, 4326),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX places_kind_idx ON places (kind);

-- Fixed slugs keep the views stable; time, weekday and enabled are yours to edit.
CREATE TABLE commute_profiles (
    id         serial PRIMARY KEY,
    slug       text UNIQUE NOT NULL,                           -- work_am | work_pm | home
    label      text NOT NULL,
    place_kind text NOT NULL CHECK (place_kind IN ('home', 'work')),
    direction  text NOT NULL CHECK (direction IN ('to_place', 'from_place')),
    anchor     text NOT NULL CHECK (anchor IN ('arrive_by', 'depart_at')),
    local_time time NOT NULL,
    weekday    int NOT NULL CHECK (weekday BETWEEN 0 AND 6),   -- 0 = Monday
    enabled    boolean NOT NULL DEFAULT true
);
INSERT INTO commute_profiles (slug, label, place_kind, direction, anchor, local_time, weekday) VALUES
    ('work_am', 'To work, morning',    'work', 'to_place',   'arrive_by', '09:00', 1),
    ('work_pm', 'From work, evening',  'work', 'from_place', 'depart_at', '18:00', 1),
    ('home',    'To home, weekend',    'home', 'to_place',   'depart_at', '11:00', 5);

CREATE TABLE commute_routes (
    property_id  bigint NOT NULL REFERENCES properties (id) ON DELETE CASCADE,
    profile_id   int NOT NULL REFERENCES commute_profiles (id) ON DELETE CASCADE,
    provider     text NOT NULL DEFAULT 'tfl',
    ref_date     date NOT NULL,
    duration_min int,
    walk_min     int,
    transfers    int,
    fare_pence   int,
    summary      text,
    journey      jsonb,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    PRIMARY KEY (property_id, profile_id, provider, ref_date)
);

-- Scheduler: cadence is edited in the UI; every run is recorded.
CREATE TABLE job_settings (
    job_id           text PRIMARY KEY,
    enabled          boolean NOT NULL DEFAULT true,
    interval_minutes int NOT NULL,
    active_from      time,                                     -- optional daily window, local time
    active_to        time,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE job_runs (
    id           bigserial PRIMARY KEY,
    job_id       text NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL DEFAULT 'running',              -- running | ok | error | skipped
    trigger      text,                                         -- schedule | manual | catch-up
    rows_added   int NOT NULL DEFAULT 0,
    rows_updated int NOT NULL DEFAULT 0,
    detail       jsonb,
    error        text
);
CREATE INDEX job_runs_job_idx ON job_runs (job_id, started_at DESC);

CREATE TABLE postcode_geo (
    postcode   text PRIMARY KEY,
    lat        double precision,
    lon        double precision,
    borough    text,
    lsoa       text,
    msoa       text,
    region     text,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_usage (
    provider text NOT NULL,
    day      date NOT NULL,
    calls    int NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, day)
);

CREATE TABLE app_settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

"""

DOWNGRADE = """
DROP TABLE IF EXISTS app_settings, api_usage, postcode_geo, job_runs, job_settings, commute_routes, commute_profiles,
    places, match_candidates, listing_price_history, listings, properties, search_areas, sources CASCADE;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
