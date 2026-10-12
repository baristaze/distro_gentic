"""What a session's workspace tells its next loop, one entry an instance let
go since, with the one notice it held moved in.

Revision ID: 202610121744
Revises: 202610121743
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121744"
down_revision = "202610121743"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121744_workspace_notices.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121744_workspace_notices.down.sql")
