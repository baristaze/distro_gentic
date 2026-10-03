"""The ledger's holds indexed by their kind and the time they were opened,
so the sweep reads the holds no settlement closed one slice of time at a
time, across tenants.

Revision ID: 202610033900
Revises: 202610033800
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610033900"
down_revision = "202610033800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610033900_open_ledger_holds_by_their_time.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610033900_open_ledger_holds_by_their_time.down.sql")
