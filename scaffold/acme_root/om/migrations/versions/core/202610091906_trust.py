"""The trust swimlane's rows, each with its fence: secrets by name, provider
keys by reference, and operators' content grants.

Revision ID: 202610091906
Revises: 202610091905
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091906"
down_revision = "202610091905"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091906_trust.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091906_trust.down.sql")
