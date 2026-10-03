"""What a session's workspace tells its next loop, one entry an instance let
go since, with the one notice it held moved in.

Revision ID: 202610035500
Revises: 202610034800
"""

from acme.om.storage.migrate import run_backfill, run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035500"
down_revision = "202610034800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610035500_workspace_notices.up.sql")
    run_backfill(
        DatabaseRole.CORE,
        "session_workspaces",
        "SELECT count(*) FROM core.session_workspaces WHERE notice IS NOT NULL",
        "UPDATE core.session_workspaces SET notices = jsonb_build_array(notice)"
        " WHERE notice IS NOT NULL",
    )


def downgrade() -> None:
    # The previous release holds one notice: the last one written.
    run_backfill(
        DatabaseRole.CORE,
        "session_workspaces",
        "SELECT count(*) FROM core.session_workspaces WHERE notices <> '[]'::jsonb",
        "UPDATE core.session_workspaces SET notice = notices ->> -1 WHERE notices <> '[]'::jsonb",
    )
    run_sql(DatabaseRole.CORE, "202610035500_workspace_notices.down.sql")
