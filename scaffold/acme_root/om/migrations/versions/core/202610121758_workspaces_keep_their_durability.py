"""A session's workspace keeps its durability and its base, a project says
whether its sessions' workspaces may be kept by snapshots, and each
snapshot a session keeps is recorded where it lives.

Revision ID: 202610121758
Revises: 202610121757
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121758"
down_revision = "202610121757"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121758_workspaces_keep_their_durability.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121758_workspaces_keep_their_durability.down.sql")
