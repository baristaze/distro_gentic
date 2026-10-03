"""A line entry carries its job, for work no session runs, and an
automation's run names the station job it runs.

Revision ID: 202610035100
Revises: 202610034800
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035100"
down_revision = "202610034800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610035100_station_jobs_in_line.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610035100_station_jobs_in_line.down.sql")
