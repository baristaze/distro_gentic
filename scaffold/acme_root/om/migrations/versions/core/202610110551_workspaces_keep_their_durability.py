"""A session's workspace keeps its durability and its base, a project says
whether its sessions' workspaces may be kept by snapshots, and each
snapshot a session keeps is recorded where it lives.

Revision ID: 202610110551
Revises: 202610091936
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610110551"
down_revision = "202610091936"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610110551_workspaces_keep_their_durability.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610110551_workspaces_keep_their_durability.down.sql")
