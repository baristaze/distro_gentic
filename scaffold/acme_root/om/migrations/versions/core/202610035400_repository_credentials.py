"""The record that a project's repository has a fetch credential, and the
digest of the push token a session's loop holds.

Revision ID: 202610035400
Revises: 202610034800
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035400"
down_revision = "202610034800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610035400_repository_credentials.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610035400_repository_credentials.down.sql")
