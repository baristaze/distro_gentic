"""What the benchmark job showed of a candidate against its baseline,
written once.

Revision ID: 202610091918
Revises: 202610091917
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091918"
down_revision = "202610091917"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091918_benchmarks.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091918_benchmarks.down.sql")
