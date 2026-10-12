"""A validation session names its project, the commit it runs at, and the
commit its checks come from; its lab leaves the mapping.

Revision ID: 202610121746
Revises: 202610121745
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121746"
down_revision = "202610121745"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121746_validation_sessions_run_on_the_executor.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121746_validation_sessions_run_on_the_executor.down.sql")
