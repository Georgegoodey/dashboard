"""Any number of commute points, each with its own journeys, replacing the fixed home and work.

places (home | work) becomes commute_points; commute_profiles loses its fixed slugs and hangs off a point; v_properties loses
its work_am_min / work_pm_min / home_min columns, which are replaced by the long view v_commutes (one row per property,
point and journey). Existing home and work places, their journeys and the routes already fetched are kept.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE commute_points (
    id         serial PRIMARY KEY,
    label      text NOT NULL,
    address    text,
    postcode   text,
    geom       geography(Point, 4326),
    enabled    boolean NOT NULL DEFAULT true,               -- false: hidden from the views, kept so it can be switched back on
    position   int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO commute_points (id, label, address, postcode, geom, position)
SELECT id, label, address, postcode, geom, CASE kind WHEN 'work' THEN 0 ELSE 1 END FROM places;
SELECT setval(pg_get_serial_sequence('commute_points', 'id'), greatest((SELECT max(id) FROM commute_points), 1));

ALTER TABLE commute_profiles ADD COLUMN point_id int REFERENCES commute_points (id) ON DELETE CASCADE;
UPDATE commute_profiles cp SET point_id = pl.id FROM places pl WHERE pl.kind = cp.place_kind;
DELETE FROM commute_profiles WHERE point_id IS NULL;          -- journeys to a place that was never set
ALTER TABLE commute_profiles ALTER COLUMN point_id SET NOT NULL;
CREATE INDEX commute_profiles_point_idx ON commute_profiles (point_id);

DROP VIEW v_properties;
ALTER TABLE commute_profiles DROP COLUMN slug, DROP COLUMN place_kind, DROP COLUMN label;   -- the name is built in v_commutes
DROP TABLE places;

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
       ST_Y(p.geom::geometry)                                                      AS lat,
       ST_X(p.geom::geometry)                                                      AS lon
FROM properties p
JOIN act a ON a.property_id = p.id
LEFT JOIN changes c ON c.property_id = p.id
LEFT JOIN med m ON m.borough = p.borough AND m.bedrooms IS NOT DISTINCT FROM p.bedrooms;

CREATE VIEW v_commute_points AS
SELECT id AS point_id, label, postcode FROM commute_points WHERE enabled AND geom IS NOT NULL;

-- Only active points and journeys that are switched on appear, so removing or pausing a point drops its rows from here.
CREATE VIEW v_commutes AS
SELECT DISTINCT ON (r.property_id, r.profile_id)
       r.property_id,
       pt.id AS point_id,
       pt.label AS point_label,
       cp.id AS profile_id,
       (CASE cp.direction WHEN 'to_place' THEN 'To ' ELSE 'From ' END || pt.label || ', '
        || CASE cp.anchor WHEN 'arrive_by' THEN 'arriving ' ELSE 'leaving ' END || to_char(cp.local_time, 'HH24:MI')) AS journey,
       cp.direction,
       cp.anchor,
       cp.local_time,
       cp.weekday,
       r.duration_min,
       r.walk_min,
       r.transfers,
       r.fare_pence,
       r.summary,
       round((ST_Distance(p.geom, pt.geom) / 1000)::numeric, 1) AS distance_km
FROM commute_routes r
JOIN commute_profiles cp ON cp.id = r.profile_id AND cp.enabled
JOIN commute_points pt ON pt.id = cp.point_id AND pt.enabled
JOIN properties p ON p.id = r.property_id
ORDER BY r.property_id, r.profile_id, r.ref_date DESC;

COMMENT ON VIEW v_properties IS 'One row per property that currently has at least one active listing. Start here for almost every question. Commute times live in v_commutes.';
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
COMMENT ON COLUMN v_properties.lat IS 'Latitude';
COMMENT ON COLUMN v_properties.lon IS 'Longitude';

COMMENT ON VIEW v_commute_points IS 'The commute destinations currently switched on (the user can have any number). Join v_commutes on point_id.';
COMMENT ON COLUMN v_commute_points.point_id IS 'Commute point id';
COMMENT ON COLUMN v_commute_points.label IS 'Name the user gave it, e.g. Work or Gym';
COMMENT ON COLUMN v_commute_points.postcode IS 'Full postcode of the point';

COMMENT ON VIEW v_commutes IS 'Public-transport journeys already computed, one row per property, commute point and journey. A property or journey with no row has not been computed yet (not zero minutes). A point may have one journey or several (e.g. a morning and an evening one).';
COMMENT ON COLUMN v_commutes.property_id IS 'Joins to v_properties.id';
COMMENT ON COLUMN v_commutes.point_id IS 'Joins to v_commute_points.point_id';
COMMENT ON COLUMN v_commutes.point_label IS 'Name of the commute point, e.g. Work';
COMMENT ON COLUMN v_commutes.profile_id IS 'Journey id';
COMMENT ON COLUMN v_commutes.journey IS 'Journey name, e.g. To Work, arriving 09:00';
COMMENT ON COLUMN v_commutes.direction IS 'to_place = property to the point, from_place = point to the property';
COMMENT ON COLUMN v_commutes.anchor IS 'arrive_by or depart_at the local_time';
COMMENT ON COLUMN v_commutes.local_time IS 'Time of day the journey is planned for';
COMMENT ON COLUMN v_commutes.weekday IS 'Day it is planned for, 0 = Monday';
COMMENT ON COLUMN v_commutes.duration_min IS 'Door to door minutes by public transport; null when no route was found';
COMMENT ON COLUMN v_commutes.walk_min IS 'Minutes spent walking';
COMMENT ON COLUMN v_commutes.transfers IS 'Number of changes between public transport legs';
COMMENT ON COLUMN v_commutes.fare_pence IS 'Single fare in pence (divide by 100 for pounds)';
COMMENT ON COLUMN v_commutes.summary IS 'Short description of the route';
COMMENT ON COLUMN v_commutes.distance_km IS 'Straight-line distance in km to the point';

GRANT SELECT ON v_properties, v_commute_points, v_commutes TO lettings_ro;
"""

DOWNGRADE = """
-- Fixed home and work come back from the first two points; other points, and v_properties (recreate it by re-running 0002's view), are not restored.
DROP VIEW v_commutes, v_commute_points, v_properties;
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
INSERT INTO places (kind, label, address, postcode, geom)
SELECT 'work', label, address, postcode, geom FROM commute_points ORDER BY position, id LIMIT 1;
INSERT INTO places (kind, label, address, postcode, geom)
SELECT 'home', label, address, postcode, geom FROM commute_points ORDER BY position, id OFFSET 1 LIMIT 1;
DELETE FROM commute_routes;
DELETE FROM commute_profiles;
ALTER TABLE commute_profiles DROP COLUMN point_id, ADD COLUMN label text NOT NULL DEFAULT '',
    ADD COLUMN slug text UNIQUE, ADD COLUMN place_kind text NOT NULL DEFAULT 'work' CHECK (place_kind IN ('home', 'work'));
INSERT INTO commute_profiles (slug, label, place_kind, direction, anchor, local_time, weekday) VALUES
    ('work_am', 'To work, morning',    'work', 'to_place',   'arrive_by', '09:00', 1),
    ('work_pm', 'From work, evening',  'work', 'from_place', 'depart_at', '18:00', 1),
    ('home',    'To home, weekend',    'home', 'to_place',   'depart_at', '11:00', 5);
DROP TABLE commute_points CASCADE;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
