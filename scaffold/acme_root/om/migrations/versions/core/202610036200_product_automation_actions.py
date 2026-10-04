"""A run of a product's own automation action keeps the work it started and
how that work ended, as the product's check said.

Revision ID: 202610036200
Revises: 202610036100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610036200"
down_revision = "202610036100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610036200_product_automation_actions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610036200_product_automation_actions.down.sql")
