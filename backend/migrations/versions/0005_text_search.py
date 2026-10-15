"""Full-text search over advert wording, for the assistant's `search_descriptions` tool.

listings.description_tsv (a generated, GIN-indexed tsvector) already exists; this exposes it through v_property_text so
the read-only role can search it. Columns are only ever appended to the view, so existing queries keep working.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE OR REPLACE VIEW v_property_text AS
SELECT p.id AS property_id,
       p.address,
       p.borough,
       l.headline,
       l.description,
       (SELECT string_agg(f, '; ') FROM jsonb_array_elements_text(coalesce(l.key_features, '[]'::jsonb)) AS f) AS key_features,
       l.description_tsv AS search
FROM properties p
JOIN LATERAL (SELECT * FROM listings x WHERE x.property_id = p.id AND x.status = 'active'
              ORDER BY x.rent_pcm NULLS LAST LIMIT 1) l ON true;

COMMENT ON COLUMN v_property_text.search IS 'tsvector over headline and description, used by the search_descriptions tool; do not select it';
"""

DOWNGRADE = """
DROP VIEW v_property_text;
CREATE VIEW v_property_text AS
SELECT p.id AS property_id,
       p.address,
       p.borough,
       l.headline,
       l.description,
       (SELECT string_agg(f, '; ') FROM jsonb_array_elements_text(coalesce(l.key_features, '[]'::jsonb)) AS f) AS key_features
FROM properties p
JOIN LATERAL (SELECT * FROM listings x WHERE x.property_id = p.id AND x.status = 'active'
              ORDER BY x.rent_pcm NULLS LAST LIMIT 1) l ON true;
COMMENT ON VIEW v_property_text IS 'Advert wording per active property. Search it with ILIKE, e.g. description ILIKE ''%garden%''. Join to v_properties on property_id = id.';
COMMENT ON COLUMN v_property_text.property_id IS 'Property id; joins to v_properties.id';
COMMENT ON COLUMN v_property_text.description IS 'Full advert description (plain text); null until the advert page has been fetched';
COMMENT ON COLUMN v_property_text.key_features IS 'Key features bullet list joined with semicolons';
GRANT SELECT ON v_property_text TO lettings_ro;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
