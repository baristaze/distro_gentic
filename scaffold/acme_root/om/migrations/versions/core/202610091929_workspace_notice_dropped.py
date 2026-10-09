"""The one notice a session's workspace held leaves the table, a release
after it left the mapping, and its notices list loses the default the
release before leaned on.

Revision ID: 202610091929
Revises: 202610091928
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091929"
down_revision = "202610091928"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091929_workspace_notice_dropped.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091929_workspace_notice_dropped.down.sql")
