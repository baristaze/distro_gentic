"""An automation's runs are found by their status, for the tick that reads
its queued runs and the admission that counts them.

Revision ID: 202610091933
Revises: 202610091932
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091933"
down_revision = "202610091932"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091933_automation_runs_by_status.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091933_automation_runs_by_status.down.sql")
