"""What the benchmark job showed of a candidate against its baseline,
written once.

Revision ID: 202610034400
Revises: 202610034200
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610034400"
down_revision = "202610034200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034400_benchmarks.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034400_benchmarks.down.sql")
