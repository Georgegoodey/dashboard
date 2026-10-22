"""Remember when each search area was last scraped on each portal.

A scrape that is stopped part-way (a portal answering HTTP 429, say) then resumes with the areas that have waited longest,
instead of starting from the same first areas every time and never reaching the rest.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE search_areas ADD COLUMN scraped_at jsonb NOT NULL DEFAULT '{}'::jsonb;   -- {"openrent": "2026-10-22T09:00:00Z", ...}
"""

DOWNGRADE = """
ALTER TABLE search_areas DROP COLUMN scraped_at;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
