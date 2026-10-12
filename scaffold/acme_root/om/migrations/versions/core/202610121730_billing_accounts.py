"""The billing accounts, with their fence.

Revision ID: 202610121730
Revises: 202610121729
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121730"
down_revision = "202610121729"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121730_billing_accounts.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121730_billing_accounts.down.sql")
