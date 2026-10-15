-- The semantic layer: the only things the chat agent and the SQL console can see.
-- Anything awkward (distances, commute minutes, rent versus area) is precomputed here so generated SQL stays simple.

CREATE VIEW v_properties AS
WITH act AS (
    SELECT l.property_id,
           min(l.rent_pcm)                                      AS rent_pcm,
           max(l.deposit)                                       AS deposit,
           min(l.first_seen)                                    AS first_listed,
           string_agg(DISTINCT s.name, ', ' ORDER BY s.name)    AS sources,
           (array_agg(l.url ORDER BY l.rent_pcm NULLS LAST))[1] AS url,
           max(l.headline)                                      AS headline,
           max(l.furnished)                                     AS furnished,
           max(l.let_type)                                      AS let_type,
           max(l.available_from)                                AS available_from
    FROM listings l JOIN sources s ON s.id = l.source_id
    WHERE l.status = 'active'
    GROUP BY l.property_id
), changes AS (
    SELECT l.property_id, greatest(count(DISTINCT h.rent_pcm) - 1, 0) AS price_changes
    FROM listings l JOIN listing_price_history h ON h.listing_id = l.id
    GROUP BY l.property_id
), med AS (
    SELECT p.borough, p.bedrooms, percentile_cont(0.5) WITHIN GROUP (ORDER BY a.rent_pcm) AS median_rent
    FROM properties p JOIN act a ON a.property_id = p.id
    WHERE p.borough IS NOT NULL
    GROUP BY p.borough, p.bedrooms
), latest AS (
    SELECT DISTINCT ON (r.property_id, r.profile_id)
           r.property_id, cp.slug, r.duration_min, r.walk_min, r.transfers, r.fare_pence
    FROM commute_routes r JOIN commute_profiles cp ON cp.id = r.profile_id
    ORDER BY r.property_id, r.profile_id, r.ref_date DESC
), cm AS (
    SELECT property_id,
           max(duration_min) FILTER (WHERE slug = 'work_am') AS work_am_min,
           max(transfers)    FILTER (WHERE slug = 'work_am') AS work_am_transfers,
           max(walk_min)     FILTER (WHERE slug = 'work_am') AS work_am_walk_min,
           max(duration_min) FILTER (WHERE slug = 'work_pm') AS work_pm_min,
           max(transfers)    FILTER (WHERE slug = 'work_pm') AS work_pm_transfers,
           max(fare_pence)   FILTER (WHERE slug = 'work_am') AS work_fare_pence,
           max(duration_min) FILTER (WHERE slug = 'home')    AS home_min
    FROM latest GROUP BY property_id
)
SELECT p.id,
       a.url,
       p.address,
       a.headline,
       a.sources,
       a.rent_pcm,
       a.deposit,
       p.bedrooms,
       p.bathrooms,
       p.property_type,
       a.furnished,
       a.let_type,
       a.available_from,
       p.postcode,
       p.outcode,
       p.borough,
       greatest(extract(day FROM now() - a.first_listed)::int, 0)                  AS days_on_market,
       coalesce(c.price_changes, 0)::int                                           AS price_changes,
       CASE WHEN m.median_rent > 0 THEN round((100 * (a.rent_pcm / m.median_rent - 1))::numeric, 1) END AS rent_vs_median_pct,
       cm.work_am_min,
       cm.work_am_transfers,
       cm.work_am_walk_min,
       cm.work_pm_min,
       cm.work_pm_transfers,
       cm.work_fare_pence,
       cm.home_min,
       round((ST_Distance(p.geom, (SELECT geom FROM places WHERE kind = 'home')) / 1000)::numeric, 1) AS distance_to_home_km,
       round((ST_Distance(p.geom, (SELECT geom FROM places WHERE kind = 'work')) / 1000)::numeric, 1) AS distance_to_work_km,
       ST_Y(p.geom::geometry)                                                      AS lat,
       ST_X(p.geom::geometry)                                                      AS lon
FROM properties p
JOIN act a ON a.property_id = p.id
LEFT JOIN changes c ON c.property_id = p.id
LEFT JOIN med m ON m.borough = p.borough AND m.bedrooms IS NOT DISTINCT FROM p.bedrooms
LEFT JOIN cm ON cm.property_id = p.id;

CREATE VIEW v_price_changes AS
SELECT p.id AS property_id, p.address, p.postcode, p.borough, s.name AS source, l.url,
       h.observed_at, h.prev_rent_pcm, h.rent_pcm AS new_rent_pcm,
       round((100 * (h.rent_pcm / h.prev_rent_pcm - 1))::numeric, 1) AS change_pct
FROM (SELECT *, lag(rent_pcm) OVER (PARTITION BY listing_id ORDER BY observed_at) AS prev_rent_pcm
      FROM listing_price_history) h
JOIN listings l ON l.id = h.listing_id
JOIN properties p ON p.id = l.property_id
JOIN sources s ON s.id = l.source_id
WHERE h.prev_rent_pcm IS NOT NULL AND h.prev_rent_pcm <> h.rent_pcm;

CREATE VIEW v_job_runs AS
SELECT job_id, started_at, finished_at, status, trigger, rows_added, rows_updated, error,
       round(extract(epoch FROM finished_at - started_at)::numeric) AS duration_s
FROM job_runs ORDER BY started_at DESC LIMIT 200;

-- Column documentation: read into the agent's schema context, so units and meaning are never guessed.
COMMENT ON VIEW v_properties IS 'One row per property that currently has at least one active listing. Start here for almost every question.';
COMMENT ON COLUMN v_properties.id IS 'Property id';
COMMENT ON COLUMN v_properties.url IS 'Link to the cheapest active advert';
COMMENT ON COLUMN v_properties.address IS 'Address as advertised';
COMMENT ON COLUMN v_properties.headline IS 'Advert headline';
COMMENT ON COLUMN v_properties.sources IS 'Portals advertising it, comma separated (rightmove, onthemarket, openrent)';
COMMENT ON COLUMN v_properties.rent_pcm IS 'Monthly rent in GBP per calendar month; the lowest across portals';
COMMENT ON COLUMN v_properties.deposit IS 'Deposit in GBP; 0 or null when not stated';
COMMENT ON COLUMN v_properties.bedrooms IS 'Number of bedrooms (0 = studio)';
COMMENT ON COLUMN v_properties.bathrooms IS 'Number of bathrooms';
COMMENT ON COLUMN v_properties.property_type IS 'e.g. Flat, Apartment, House, Terraced, Maisonette';
COMMENT ON COLUMN v_properties.furnished IS 'Furnished, Unfurnished, Part furnished, or null when not stated';
COMMENT ON COLUMN v_properties.let_type IS 'e.g. Long term, Short term';
COMMENT ON COLUMN v_properties.available_from IS 'Date it can be moved into; null means "ask agent" or now';
COMMENT ON COLUMN v_properties.postcode IS 'Full postcode, e.g. SW11 7FD';
COMMENT ON COLUMN v_properties.outcode IS 'Outward postcode, e.g. SW11';
COMMENT ON COLUMN v_properties.borough IS 'London borough or local authority name';
COMMENT ON COLUMN v_properties.days_on_market IS 'Days since first seen advertised';
COMMENT ON COLUMN v_properties.price_changes IS 'Number of times the rent has changed since first seen';
COMMENT ON COLUMN v_properties.rent_vs_median_pct IS 'Percent above (+) or below (-) the median rent of active properties with the same bedrooms in the same borough';
COMMENT ON COLUMN v_properties.work_am_min IS 'Door to door minutes by public transport to work, arriving by the morning time set in Settings';
COMMENT ON COLUMN v_properties.work_am_transfers IS 'Number of changes between public transport legs on the morning work journey';
COMMENT ON COLUMN v_properties.work_am_walk_min IS 'Minutes spent walking on the morning work journey';
COMMENT ON COLUMN v_properties.work_pm_min IS 'Door to door minutes by public transport from work, leaving at the evening time set in Settings';
COMMENT ON COLUMN v_properties.work_pm_transfers IS 'Number of changes on the evening journey home from work';
COMMENT ON COLUMN v_properties.work_fare_pence IS 'Single fare in pence for the morning work journey (divide by 100 for pounds)';
COMMENT ON COLUMN v_properties.home_min IS 'Door to door minutes by public transport to your home place';
COMMENT ON COLUMN v_properties.distance_to_home_km IS 'Straight-line distance in km to your home place';
COMMENT ON COLUMN v_properties.distance_to_work_km IS 'Straight-line distance in km to your work place';
COMMENT ON COLUMN v_properties.lat IS 'Latitude';
COMMENT ON COLUMN v_properties.lon IS 'Longitude';
COMMENT ON VIEW v_price_changes IS 'Every rent change observed on a listing (drops and rises).';
COMMENT ON COLUMN v_price_changes.change_pct IS 'Percent change in rent; negative is a price drop';
COMMENT ON VIEW v_job_runs IS 'Recent scheduler runs: use it to answer when data was last refreshed.';

-- Read-only role used by the SQL console, charts and the chat agent: it can see only the views above.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lettings_ro') THEN
        CREATE ROLE lettings_ro LOGIN PASSWORD 'lettings_ro';
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO lettings_ro', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO lettings_ro;
GRANT SELECT ON v_properties, v_price_changes, v_job_runs TO lettings_ro;
ALTER ROLE lettings_ro SET default_transaction_read_only = on;
ALTER ROLE lettings_ro SET statement_timeout = '10s';
