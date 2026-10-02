"""The one ledger's entries and counts, with their fences, and the entries
kept to SELECT and INSERT for the serving logins.

Revision ID: 202610032301
Revises: 202610030801
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610032301"
down_revision = "202610030801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610032301_money_ledger.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610032301_money_ledger.down.sql")
