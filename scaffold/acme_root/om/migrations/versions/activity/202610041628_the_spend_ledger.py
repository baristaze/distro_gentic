"""Agent billing's ledger is the spend ledger: its two tables and their
indexes take the name, every entry and count stays, a hold names the
unit plan it drew on, and the events' kinds move in place.

Revision ID: 202610041628
Revises: 202610041627
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041628"
down_revision = "202610041627"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041628_the_spend_ledger.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041628_the_spend_ledger.down.sql")
