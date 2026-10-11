"""The cloud pool runs a machine per session: its machines, each session's
pool of one, and the snapshots its machines' store keeps.

Revision ID: 202610110914
Revises: 202610110736
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610110914"
down_revision = "202610110736"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610110914_the_cloud_pool_runs_a_machine_per_session.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610110914_the_cloud_pool_runs_a_machine_per_session.down.sql")
