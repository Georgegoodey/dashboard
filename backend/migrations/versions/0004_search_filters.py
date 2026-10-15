"""Starting values for the search filters.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = '0003'
branch_labels = None
depends_on = None

UPGRADE = """
-- Search filters: which listings the scrapers keep. Edited in the Settings panel; these are only the starting values.
INSERT INTO app_settings (key, value) VALUES
    ('search_filters', '{"min_bedrooms": 1, "max_bedrooms": 4, "max_rent": 3500}'::jsonb)
ON CONFLICT (key) DO NOTHING;

"""

DOWNGRADE = """DELETE FROM app_settings WHERE key = 'search_filters';"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
