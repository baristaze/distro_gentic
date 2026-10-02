"""The validation sessions, with their fence.

Revision ID: 202610032500
Revises: 202610032100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610032500"
down_revision = "202610032100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032500_validation_sessions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032500_validation_sessions.down.sql")
