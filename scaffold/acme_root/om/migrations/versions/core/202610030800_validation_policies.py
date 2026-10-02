"""Each project's validation policy, with its fence.

Revision ID: 202610030800
Revises: 202610021100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610030800"
down_revision = "202610021100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030800_validation_policies.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030800_validation_policies.down.sql")
