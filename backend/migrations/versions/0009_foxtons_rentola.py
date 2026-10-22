"""Add the Foxtons and Rentola sources.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UPGRADE = """
INSERT INTO sources (name, kind, enabled) VALUES ('foxtons', 'scrape', true), ('rentola', 'scrape', true)
ON CONFLICT (name) DO UPDATE SET enabled = true;
"""

DOWNGRADE = """
DELETE FROM sources WHERE name IN ('foxtons', 'rentola') AND NOT EXISTS (SELECT 1 FROM listings l WHERE l.source_id = sources.id);
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
