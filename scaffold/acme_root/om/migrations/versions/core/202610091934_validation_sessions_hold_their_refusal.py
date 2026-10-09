"""A validation session holds why its check was refused, once it cannot
run here for good, so its read says so rather than waiting for ever.

Revision ID: 202610091934
Revises: 202610091933
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091934"
down_revision = "202610091933"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091934_validation_sessions_hold_their_refusal.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091934_validation_sessions_hold_their_refusal.down.sql")
