"""The engine's holds indexed by the time they were opened, so the sweep
reads the holds no settlement closed one slice of time at a time.

Revision ID: 202610033800
Revises: 202610032301
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610033800"
down_revision = "202610032301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610033800_open_holds_by_their_time.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610033800_open_holds_by_their_time.down.sql")
