"""Each session's workspace, pinned, and each project's egress allowlist,
with their fences.

Revision ID: 202610032800
Revises: 202610032500
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610032800"
down_revision = "202610032500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032800_workspaces.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032800_workspaces.down.sql")
