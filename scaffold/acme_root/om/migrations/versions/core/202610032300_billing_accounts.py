"""The billing accounts, with their fence.

Revision ID: 202610032300
Revises: 202610032200
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610032300"
down_revision = "202610032200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032300_billing_accounts.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032300_billing_accounts.down.sql")
