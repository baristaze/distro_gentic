"""The platform's own tables of the activity role, on the engine's.

Revision ID: 202610041636
Revises: 202610150049
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041636"
down_revision = "202610150049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041636_folded_activity_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041636_folded_activity_revisions.down.sql")
