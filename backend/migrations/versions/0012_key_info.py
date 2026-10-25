"""Key information read from what is stored about each advert: furnishing, shared, pets, bills, garden, parking, balcony.

Portals state these in different ways: a furnishing field with a dozen wordings, or a phrase in the description or the bullet
points. `listing_key_info` reads all of them into one small JSON object, and a generated column keeps it up to date whenever an
advert is stored or its details arrive, so nothing has to be recomputed per query. v_properties then carries the result.

The patterns are plain regular expressions in the function below; to change one, replace the function and re-add the column.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE FUNCTION listing_key_info(furnished text, description text, features jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
WITH t AS (
    SELECT lower(coalesce(description, '') || ' ' || coalesce(features::text, '')) AS txt, lower(coalesce(furnished, '')) AS f
)
SELECT jsonb_build_object(
    'furnish', CASE
        WHEN f ~ 'or unfurnished|tenant choice|flexible' THEN 'flexible'
        WHEN f ~ 'part' THEN 'part_furnished'
        WHEN f ~ 'unfurnished' THEN 'unfurnished'
        WHEN f ~ 'furnished' THEN 'furnished'
        WHEN txt ~ 'furnished ?(or|/) ?unfurnished|unfurnished ?(or|/) ?furnished|furnished or not' THEN 'flexible'
        WHEN txt ~ 'part[- ]furnished' THEN 'part_furnished'
        WHEN txt ~ '\munfurnished' THEN 'unfurnished'
        WHEN txt ~ '(?<!un)(?<!part[- ])\mfurnished' THEN 'furnished'
    END,
    'pets', txt ~ 'pets? (are )?(allowed|considered|welcome|accepted)|pet[- ]friendly|pets? by (prior )?arrangement'
            AND txt !~ 'no pets|pets? (are )?not (allowed|permitted|accepted)',
    'bills', txt ~ '(all )?bills (are )?included|inclusive of (all )?bills|including (all )?bills|bills inclusive|bills incl',
    'garden', txt ~ 'garden' AND txt !~ 'no (private )?garden',
    'parking', txt ~ 'parking|garage|driveway' AND txt !~ 'no (off[- ]street )?parking|parking (is )?not',
    'balcony', txt ~ 'balcon|terrace|roof garden',
    'shared', txt ~ 'house ?share|flat ?share|shared (house|flat|accommodation|property)|rooms? (to rent|available)|rooms? in a (shared )?(house|flat)'
) FROM t
$fn$;

ALTER TABLE listings ADD COLUMN key_info jsonb GENERATED ALWAYS AS (listing_key_info(furnished, description, key_features)) STORED;

CREATE OR REPLACE VIEW v_properties AS
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
           max(l.available_from)                                AS available_from,
           (array_agg(l.key_info ->> 'furnish' ORDER BY (l.key_info ->> 'furnish') IS NULL, l.rent_pcm))[1] AS furnish_type,
           coalesce(bool_or((l.key_info ->> 'shared')::boolean), false)  AS shared,
           coalesce(bool_or((l.key_info ->> 'pets')::boolean), false)    AS pets_allowed,
           coalesce(bool_or((l.key_info ->> 'bills')::boolean), false)   AS bills_included,
           coalesce(bool_or((l.key_info ->> 'garden')::boolean), false)  AS has_garden,
           coalesce(bool_or((l.key_info ->> 'parking')::boolean), false) AS has_parking,
           coalesce(bool_or((l.key_info ->> 'balcony')::boolean), false) AS has_balcony
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
       ST_X(p.geom::geometry)                                                      AS lon,
       a.furnish_type,
       (a.shared OR coalesce(p.property_type ~* 'share', false))                   AS is_shared,
       a.pets_allowed,
       a.bills_included,
       a.has_garden,
       a.has_parking,
       a.has_balcony
FROM properties p
JOIN act a ON a.property_id = p.id
LEFT JOIN changes c ON c.property_id = p.id
LEFT JOIN med m ON m.borough = p.borough AND m.bedrooms IS NOT DISTINCT FROM p.bedrooms;

COMMENT ON COLUMN v_properties.furnish_type IS 'furnished, part_furnished, unfurnished or flexible (the landlord will do either); null when the advert does not say';
COMMENT ON COLUMN v_properties.is_shared IS 'True for a room in a shared house or flat';
COMMENT ON COLUMN v_properties.pets_allowed IS 'True when an advert says pets are allowed or considered (false means not stated, not forbidden)';
COMMENT ON COLUMN v_properties.bills_included IS 'True when an advert says bills are included (false means not stated)';
COMMENT ON COLUMN v_properties.has_garden IS 'True when an advert mentions a garden (private or communal)';
COMMENT ON COLUMN v_properties.has_parking IS 'True when an advert mentions parking, a garage or a driveway';
COMMENT ON COLUMN v_properties.has_balcony IS 'True when an advert mentions a balcony, terrace or roof garden';
"""

DOWNGRADE = r"""
-- v_properties without the new columns (a view cannot lose columns in place)
DROP VIEW v_properties;
CREATE VIEW v_properties AS
WITH act AS (
    SELECT l.property_id, min(l.rent_pcm) AS rent_pcm, max(l.deposit) AS deposit, min(l.first_seen) AS first_listed,
           string_agg(DISTINCT s.name, ', ' ORDER BY s.name) AS sources,
           (array_agg(l.url ORDER BY l.rent_pcm NULLS LAST))[1] AS url, max(l.headline) AS headline,
           max(l.furnished) AS furnished, max(l.let_type) AS let_type, max(l.available_from) AS available_from
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
SELECT p.id, a.url, p.address, a.headline, a.sources, a.rent_pcm, a.deposit, p.bedrooms, p.bathrooms, p.property_type, a.furnished,
       a.let_type, a.available_from, p.postcode, p.outcode, p.borough,
       greatest(extract(day FROM now() - a.first_listed)::int, 0) AS days_on_market,
       coalesce(c.price_changes, 0)::int AS price_changes,
       CASE WHEN m.median_rent > 0 THEN round((100 * (a.rent_pcm / m.median_rent - 1))::numeric, 1) END AS rent_vs_median_pct,
       ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lon
FROM properties p JOIN act a ON a.property_id = p.id
LEFT JOIN changes c ON c.property_id = p.id
LEFT JOIN med m ON m.borough = p.borough AND m.bedrooms IS NOT DISTINCT FROM p.bedrooms;
GRANT SELECT ON v_properties TO lettings_ro;
ALTER TABLE listings DROP COLUMN key_info;
DROP FUNCTION listing_key_info(text, text, jsonb);
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
