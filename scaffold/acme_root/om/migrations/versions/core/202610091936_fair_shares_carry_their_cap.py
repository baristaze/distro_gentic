"""A share's concurrency takes a default, and each share marks whether the
sweep carried it into the tenant's own cap.

Revision ID: 202610091936
Revises: 202610091935
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091936"
down_revision = "202610091935"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091936_fair_shares_carry_their_cap.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091936_fair_shares_carry_their_cap.down.sql")
