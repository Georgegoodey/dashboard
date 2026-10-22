"""Switch on the OnTheMarket and OpenRent sources, now that they have adapters.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UPGRADE = """
UPDATE sources SET enabled = true WHERE name IN ('onthemarket', 'openrent');
"""

DOWNGRADE = """
UPDATE sources SET enabled = false WHERE name IN ('onthemarket', 'openrent');
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE.replace("%", "%%"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE.replace("%", "%%"))
