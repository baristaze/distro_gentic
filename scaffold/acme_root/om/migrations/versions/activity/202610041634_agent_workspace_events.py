"""The platform's workspaces are its agent workspaces: the kinds of the
events they announced move in place.

Revision ID: 202610041634
Revises: 202610041633
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041634"
down_revision = "202610041633"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041634_agent_workspace_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041634_agent_workspace_events.down.sql")
