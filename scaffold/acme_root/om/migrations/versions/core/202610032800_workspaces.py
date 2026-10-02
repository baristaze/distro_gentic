"""Each session's workspace, pinned, and each project's egress allowlist,
with their fences.

Revision ID: 202610030400
Revises: 202610030100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610030400"
down_revision = "202610030100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030400_workspaces.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030400_workspaces.down.sql")
