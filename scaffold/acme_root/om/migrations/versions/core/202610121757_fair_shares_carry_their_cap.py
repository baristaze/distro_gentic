"""A share's concurrency takes a default, and each share marks whether the
sweep carried it into the tenant's own cap.

Revision ID: 202610121757
Revises: 202610121756
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121757"
down_revision = "202610121756"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121757_fair_shares_carry_their_cap.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121757_fair_shares_carry_their_cap.down.sql")
