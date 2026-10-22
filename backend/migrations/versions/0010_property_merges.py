"""A record of properties merged because they were the same home advertised on several portals.

Each row holds the properties that were absorbed (their columns, coordinates and listing ids), so a merge can be reversed by
hand if it turns out to be wrong.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE property_merges (
    id          bigserial PRIMARY KEY,
    merged_at   timestamptz NOT NULL DEFAULT now(),
    survivor_id bigint NOT NULL,              -- not a foreign key: the survivor may itself be merged away later
    absorbed    jsonb NOT NULL                -- [{property, lat, lon, listing_ids}, ...]
);
CREATE INDEX property_merges_survivor_idx ON property_merges (survivor_id);
"""

DOWNGRADE = """
DROP TABLE property_merges;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
