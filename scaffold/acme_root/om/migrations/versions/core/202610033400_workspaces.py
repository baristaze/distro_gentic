"""Each session's workspace, pinned, and each project's egress allowlist,
with their fences.

Revision ID: 202610033400
Revises: 202610033300
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610033400"
down_revision = "202610033300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610033400_workspaces.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610033400_workspaces.down.sql")
