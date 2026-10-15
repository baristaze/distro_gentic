"""The platform's index of the queue role, on the engine's.

Revision ID: 202610035803
Revises: 202610141614
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035803"
down_revision = "202610141614"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035803_folded_queue_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035803_folded_queue_revisions.down.sql")
