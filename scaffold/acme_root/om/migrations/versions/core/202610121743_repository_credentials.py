"""The record that a project's repository has a fetch credential, and the
digest of the push token a session's loop holds.

Revision ID: 202610121743
Revises: 202610121742
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121743"
down_revision = "202610121742"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121743_repository_credentials.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121743_repository_credentials.down.sql")
