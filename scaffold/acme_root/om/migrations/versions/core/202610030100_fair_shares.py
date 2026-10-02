"""Each tenant's fair share of the loops, with its fence.

Revision ID: 202610030100
Revises: 202610021100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610030100"
down_revision = "202610021100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030100_fair_shares.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030100_fair_shares.down.sql")
