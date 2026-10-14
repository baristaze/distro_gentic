"""The platform's tables of a session and its workspace name the agent:
session_* become agent_session_*, the workspaces' snapshots and bindings
agent_workspace_*, and the cloud pool's machines pool_vms; every row
stays, and the kinds of the events they announce move in place in the
outbox.

Revision ID: 202610121813
Revises: 202610121812
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121813"
down_revision = "202610121812"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121813_agent_session_and_workspace_tables.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121813_agent_session_and_workspace_tables.down.sql")
