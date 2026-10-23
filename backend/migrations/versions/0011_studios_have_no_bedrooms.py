"""Studios are stored with 0 bedrooms.

Some portals leave the bedroom count out of a studio, and a home with an unknown count slips through the bedroom filter. The
adapters now say 0; this does the same for what is already stored.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UPGRADE = """
UPDATE properties SET bedrooms = 0 WHERE bedrooms IS NULL AND lower(property_type) LIKE '%studio%';
"""

DOWNGRADE = """
SELECT 1;   -- the count was unknown before and cannot be told apart from a studio set to 0 on purpose
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
