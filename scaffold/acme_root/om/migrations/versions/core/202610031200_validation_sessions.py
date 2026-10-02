"""The validation sessions, with their fence.

Revision ID: 202610031200
Revises: 202610030900
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610031200"
down_revision = "202610030900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610031200_validation_sessions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610031200_validation_sessions.down.sql")
