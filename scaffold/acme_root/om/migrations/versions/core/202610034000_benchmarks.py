"""What the benchmark job showed of a candidate against its baseline,
written once.

Revision ID: 202610034000
Revises: 202610033400
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610034000"
down_revision = "202610033400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034000_benchmarks.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034000_benchmarks.down.sql")
