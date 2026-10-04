"""A job's hold names the job's deadline, which it lives to, so the sweep
reads it by that deadline, and every other hold by its opening time.

Revision ID: 202610034000
Revises: 202610033900
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610034000"
down_revision = "202610033900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610034000_a_jobs_hold_lives_to_its_deadline.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610034000_a_jobs_hold_lives_to_its_deadline.down.sql")
