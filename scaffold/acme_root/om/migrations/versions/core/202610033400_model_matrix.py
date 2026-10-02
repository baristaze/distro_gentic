"""The model matrix: its versions, benchmark results, and retirements, and
each tenant's pins and choices, with their fence.

Revision ID: 202610033400
Revises: 202610033200
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610033400"
down_revision = "202610033200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610033400_model_matrix.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610033400_model_matrix.down.sql")
