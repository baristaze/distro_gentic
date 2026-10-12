"""Each project's validation policy, with its fence.

Revision ID: 202610121728
Revises: 202610121727
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121728"
down_revision = "202610121727"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121728_validation_policies.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121728_validation_policies.down.sql")
